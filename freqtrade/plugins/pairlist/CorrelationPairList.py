"""
Correlation PairList Filter

Finds and adds pairs highly correlated to the base pairlist.
Runs as a filter after a pairlist generator (e.g., StaticPairList).
"""

import logging
from pathlib import Path

from cachetools import TTLCache
from pandas import DataFrame

from freqtrade.data.history import load_data
from freqtrade.enums import CandleType
from freqtrade.exchange.exchange_types import Tickers
from freqtrade.plugins.pairlist.IPairList import IPairList, PairlistParameter, SupportsBacktesting
from freqtrade.util import dt_now


logger = logging.getLogger(__name__)


class CorrelationPairList(IPairList):
    """
    PairList filter that adds correlated pairs to the whitelist.

    For each pair in the incoming pairlist (base pairs), finds the top N
    most correlated pairs above a threshold and adds them to the whitelist.

    Configuration:
        correlation_threshold: Minimum Pearson correlation (default: 0.7)
        max_correlated_per_base: Max correlated pairs per base pair (default: 3)
        lookback_days: Days of history to analyze (default: 30)
        min_correlation_periods: Minimum overlapping candles required (default: 100)
        refresh_period: Cache TTL in seconds for live mode (default: 3600)
    """

    is_pairlist_generator = False
    supports_backtesting = SupportsBacktesting.YES

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._threshold = self._pairlistconfig.get("correlation_threshold", 0.7)
        self._max_per_base = self._pairlistconfig.get("max_correlated_per_base", 3)
        self._lookback_days = self._pairlistconfig.get("lookback_days", 30)
        self._min_periods = self._pairlistconfig.get("min_correlation_periods", 100)
        self._refresh_period = self._pairlistconfig.get("refresh_period", 3600)

        self._correlation_cache: TTLCache = TTLCache(maxsize=1, ttl=self._refresh_period)
        self._stake_currency = self._config["stake_currency"]
        self._timeframe = self._config["timeframe"]
        self._candle_type = self._config.get("candle_type_def", CandleType.SPOT)
        self._datadir = Path(self._config["datadir"])

    @property
    def needstickers(self) -> bool:
        """Boolean property defining if tickers are necessary."""
        return False

    def short_desc(self) -> str:
        """Short whitelist method description - used for startup-messages"""
        return f"{self.name} - threshold: {self._threshold}, max_per_base: {self._max_per_base}"

    @staticmethod
    def description() -> str:
        return "Adds correlated pairs to the whitelist based on price correlation."

    @staticmethod
    def available_parameters() -> dict[str, PairlistParameter]:
        return {
            "correlation_threshold": {
                "type": "number",
                "default": 0.7,
                "description": "Correlation threshold",
                "help": "Minimum Pearson correlation coefficient to include a pair (0.0 to 1.0).",
            },
            "max_correlated_per_base": {
                "type": "number",
                "default": 3,
                "description": "Max correlated per base",
                "help": "Maximum number of correlated pairs to add per base pair.",
            },
            "lookback_days": {
                "type": "number",
                "default": 30,
                "description": "Lookback days",
                "help": "Number of days of historical data to use for correlation calculation.",
            },
            "min_correlation_periods": {
                "type": "number",
                "default": 100,
                "description": "Min correlation periods",
                "help": "Minimum number of overlapping candles required for valid correlation.",
            },
            **IPairList.refresh_period_parameter(),
        }

    def filter_pairlist(self, pairlist: list[str], tickers: Tickers) -> list[str]:
        """
        Filters and sorts pairlist and returns the whitelist again.

        :param pairlist: pairlist to filter or sort (base pairs from generator)
        :param tickers: Tickers (from exchange.get_tickers). Not used by this filter.
        :return: new whitelist with correlated pairs added
        """
        if not self._enabled:
            return pairlist

        # Get correlation mapping: {base_pair: [correlated_pair, ...]}
        correlation_map = self._get_correlation_map()

        # Build expanded pairlist preserving order and deduplicating
        expanded = list(pairlist)  # Start with base pairs
        seen = set(expanded)

        for base_pair in pairlist:
            correlated = correlation_map.get(base_pair, [])
            for corr_pair in correlated[: self._max_per_base]:
                if corr_pair not in seen:
                    expanded.append(corr_pair)
                    seen.add(corr_pair)

        self.log_once(
            f"CorrelationPairList: {len(pairlist)} base pairs -> {len(expanded)} total pairs "
            f"({len(expanded) - len(pairlist)} correlated added)",
            logger.info,
        )

        return expanded

    def _get_correlation_map(self) -> dict[str, list[str]]:
        """
        Get or compute the correlation map.

        Returns: {base_pair: [correlated_pair1, correlated_pair2, ...], ...}
        Sorted by correlation descending.
        """
        cache_key = f"corr_{self._threshold}_{self._max_per_base}_{self._lookback_days}"
        cached = self._correlation_cache.get(cache_key)
        if cached is not None:
            return cached

        # Load price data for all candidate pairs
        price_data = self._load_price_data()
        if not price_data:
            self._correlation_cache[cache_key] = {}
            return {}

        # Calculate correlation matrix
        corr_matrix = self._calculate_correlation_matrix(price_data)
        if corr_matrix.empty:
            self._correlation_cache[cache_key] = {}
            return {}

        # Build mapping for each base pair
        correlation_map: dict[str, list[str]] = {}
        base_pairs = set(price_data.keys())

        for base_pair in base_pairs:
            if base_pair not in corr_matrix.index:
                continue

            # Get correlations for this base pair, exclude self
            correlations = corr_matrix.loc[base_pair].drop(base_pair, errors="ignore")

            # Filter by threshold and minimum periods (already enforced in matrix)
            qualified = correlations[correlations >= self._threshold]

            # Sort by correlation descending
            sorted_pairs = qualified.sort_values(ascending=False).index.tolist()

            correlation_map[base_pair] = sorted_pairs

        self._correlation_cache[cache_key] = correlation_map
        return correlation_map

    def _load_price_data(self) -> dict[str, DataFrame]:
        """
        Load close price data for all active markets with the same stake currency.

        Returns: {pair: DataFrame with 'close' column indexed by date}
        """
        # Get all active markets with matching stake currency
        markets = self._exchange.get_markets(
            quote_currencies=[self._stake_currency], tradable_only=True, active_only=True
        )

        if not markets:
            logger.warning(f"No active markets found for stake currency {self._stake_currency}")
            return {}

        candidate_pairs = list(markets.keys())

        # Determine timerange based on mode
        if self._config["runmode"].value in ("backtest", "hyperopt", "edge"):
            # Backtesting: use the timerange from config
            from freqtrade.configuration import TimeRange

            timerange = TimeRange.parse_timerange(self._config.get("timerange"))
        else:
            # Live/dry-run: fetch recent data
            from datetime import timedelta

            from freqtrade.configuration import TimeRange

            since = dt_now() - timedelta(days=self._lookback_days)
            timerange = TimeRange.parse_timerange(f"{since.strftime('%Y%m%d')}-")

        # Load data for all candidate pairs
        try:
            data = load_data(
                datadir=self._datadir,
                pairs=candidate_pairs,
                timeframe=self._timeframe,
                timerange=timerange,
                startup_candles=0,
                fail_without_data=False,
                data_format=self._config["dataformat_ohlcv"],
                candle_type=self._candle_type,
            )
        except (OSError, ValueError) as e:
            logger.warning(f"Failed to load correlation data: {e}")
            return {}

        # Extract close prices, ensure minimum data
        price_data: dict[str, DataFrame] = {}
        for pair, df in data.items():
            if len(df) >= self._min_periods:
                # Create DataFrame with close prices indexed by date
                close_df = df[["date", "close"]].copy()
                close_df = close_df.set_index("date")
                close_df.columns = [pair]
                price_data[pair] = close_df

        return price_data

    def _calculate_correlation_matrix(self, price_data: dict[str, DataFrame]) -> DataFrame:
        """
        Calculate Pearson correlation matrix on returns.

        :param price_data: {pair: DataFrame with 'close' column indexed by date}
        :return: Correlation matrix DataFrame
        """
        if not price_data:
            return DataFrame()

        # Combine all close prices into a single DataFrame
        combined = DataFrame()
        for df in price_data.values():
            combined = combined.join(df, how="outer")

        if combined.empty or len(combined.columns) < 2:
            return DataFrame()

        # Calculate returns (percentage change)
        returns = combined.pct_change(fill_method=None).dropna()

        if len(returns) < self._min_periods:
            return DataFrame()

        # Calculate Pearson correlation matrix
        corr_matrix = returns.corr(method="pearson", min_periods=self._min_periods)

        return corr_matrix

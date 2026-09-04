"""
Unit tests for CorrelationPairList
"""

import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from freqtrade.constants import Config
from freqtrade.enums import CandleType, RunMode
from freqtrade.plugins.pairlist.CorrelationPairList import CorrelationPairList


# Get the module for patching
corr_module = sys.modules["freqtrade.plugins.pairlist.CorrelationPairList"]


@pytest.fixture
def mock_config() -> Config:
    """Create a mock config for testing."""
    return {
        "stake_currency": "USDC",
        "timeframe": "5m",
        "candle_type_def": CandleType.SPOT,
        "datadir": "/tmp/test_data",  # noqa: S108
        "dataformat_ohlcv": "feather",
        "runmode": RunMode.BACKTEST,
        "timerange": None,
        "exchange": {
            "name": "binance",
            "pair_whitelist": ["BTC/USDC", "ETH/USDC", "XRP/USDC"],
            "pair_blacklist": [],
        },
        "freqai": {"enabled": False},
        "pairlists": [
            {"method": "StaticPairList"},
            {
                "method": "CorrelationPairList",
                "correlation_threshold": 0.7,
                "max_correlated_per_base": 2,
            },
        ],
    }


@pytest.fixture
def mock_exchange():
    """Create a mock exchange."""
    exchange = MagicMock()
    exchange.name = "binance"
    exchange.get_markets.return_value = {
        "BTC/USDC": {"active": True, "quote": "USDC"},
        "ETH/USDC": {"active": True, "quote": "USDC"},
        "XRP/USDC": {"active": True, "quote": "USDC"},
        "DOGE/USDC": {"active": True, "quote": "USDC"},
        "SOL/USDC": {"active": True, "quote": "USDC"},
        "ADA/USDC": {"active": True, "quote": "USDC"},
    }
    return exchange


@pytest.fixture
def mock_pairlistmanager(mock_exchange, mock_config):
    """Create a mock pairlist manager."""
    manager = MagicMock()
    manager._dataprovider = None
    manager._exchange = mock_exchange
    manager._config = mock_config
    return manager


@pytest.fixture
def correlation_pairlist(mock_exchange, mock_pairlistmanager, mock_config):
    """Create a CorrelationPairList instance for testing."""
    pairlist = CorrelationPairList(
        exchange=mock_exchange,
        pairlistmanager=mock_pairlistmanager,
        config=mock_config,
        pairlistconfig={
            "correlation_threshold": 0.7,
            "max_correlated_per_base": 2,
            "lookback_days": 30,
            "min_correlation_periods": 100,
            "refresh_period": 3600,
        },
        pairlist_pos=1,
    )
    return pairlist


class TestCorrelationPairList:
    """Tests for CorrelationPairList."""

    def test_initialization(self, correlation_pairlist):
        """Test that the pairlist initializes with correct defaults."""
        assert correlation_pairlist._threshold == 0.7
        assert correlation_pairlist._max_per_base == 2
        assert correlation_pairlist._lookback_days == 30
        assert correlation_pairlist._min_periods == 100
        assert correlation_pairlist._refresh_period == 3600
        assert correlation_pairlist._stake_currency == "USDC"
        assert correlation_pairlist._timeframe == "5m"
        assert not correlation_pairlist.is_pairlist_generator
        assert correlation_pairlist.supports_backtesting.value == "yes"

    def test_needstickers(self, correlation_pairlist):
        """Test that needstickers returns False."""
        assert correlation_pairlist.needstickers is False

    def test_short_desc(self, correlation_pairlist):
        """Test short description."""
        desc = correlation_pairlist.short_desc()
        assert "CorrelationPairList" in desc
        assert "0.7" in desc
        assert "2" in desc

    def test_description(self):
        """Test static description."""
        desc = CorrelationPairList.description()
        assert "correlated" in desc.lower()

    def test_available_parameters(self):
        """Test available parameters."""
        params = CorrelationPairList.available_parameters()
        assert "correlation_threshold" in params
        assert "max_correlated_per_base" in params
        assert "lookback_days" in params
        assert "min_correlation_periods" in params
        assert "refresh_period" in params

    @patch.object(corr_module, "load_data", new_callable=MagicMock)
    def test_load_price_data_backtest(self, mock_load_data, correlation_pairlist):
        """Test loading price data in backtest mode."""
        # Create mock data
        dates = pd.date_range(start="2024-01-01", periods=200, freq="5min")
        df1 = pd.DataFrame({"date": dates, "close": [100 + i * 0.1 for i in range(200)]})
        df2 = pd.DataFrame({"date": dates, "close": [200 + i * 0.2 for i in range(200)]})
        df3 = pd.DataFrame({"date": dates, "close": [50 + i * 0.05 for i in range(200)]})

        mock_load_data.return_value = {
            "BTC/USDC": df1,
            "ETH/USDC": df2,
            "XRP/USDC": df3,
        }

        correlation_pairlist._config["runmode"] = RunMode.BACKTEST
        price_data = correlation_pairlist._load_price_data()

        assert len(price_data) == 3
        assert "BTC/USDC" in price_data
        assert "ETH/USDC" in price_data
        assert "XRP/USDC" in price_data
        # Check that dataframes have correct structure
        for pair, df in price_data.items():
            assert pair in df.columns
            assert len(df) >= correlation_pairlist._min_periods

    @patch.object(corr_module, "load_data", new_callable=MagicMock)
    def test_load_price_data_live(self, mock_load_data, correlation_pairlist):
        """Test loading price data in live mode."""
        dates = pd.date_range(start="2024-01-01", periods=200, freq="5min")
        df1 = pd.DataFrame({"date": dates, "close": [100 + i * 0.1 for i in range(200)]})
        df2 = pd.DataFrame({"date": dates, "close": [200 + i * 0.2 for i in range(200)]})

        mock_load_data.return_value = {
            "BTC/USDC": df1,
            "ETH/USDC": df2,
        }

        correlation_pairlist._config["runmode"] = RunMode.DRY_RUN
        price_data = correlation_pairlist._load_price_data()

        assert len(price_data) == 2

    @patch.object(corr_module, "load_data", new_callable=MagicMock)
    def test_load_price_data_insufficient_data(self, mock_load_data, correlation_pairlist):
        """Test that pairs with insufficient data are filtered out."""
        dates = pd.date_range(
            start="2024-01-01", periods=50, freq="5min"
        )  # Less than min_periods (100)
        df1 = pd.DataFrame({"date": dates, "close": [100 + i * 0.1 for i in range(50)]})

        dates2 = pd.date_range(start="2024-01-01", periods=200, freq="5min")
        df2 = pd.DataFrame({"date": dates2, "close": [200 + i * 0.2 for i in range(200)]})

        mock_load_data.return_value = {
            "BTC/USDC": df1,  # Insufficient data
            "ETH/USDC": df2,  # Sufficient data
        }

        price_data = correlation_pairlist._load_price_data()

        assert len(price_data) == 1
        assert "ETH/USDC" in price_data
        assert "BTC/USDC" not in price_data

    def test_calculate_correlation_matrix(self, correlation_pairlist):
        """Test correlation matrix calculation."""
        # Create perfectly correlated data
        dates = pd.date_range(start="2024-01-01", periods=200, freq="5min")
        base_prices = [100 + i * 0.1 for i in range(200)]
        corr_prices = [200 + i * 0.2 for i in range(200)]  # Perfectly correlated

        df1 = pd.DataFrame({"date": dates, "close": base_prices}).set_index("date")
        df1.columns = ["BTC/USDC"]
        df2 = pd.DataFrame({"date": dates, "close": corr_prices}).set_index("date")
        df2.columns = ["ETH/USDC"]

        price_data = {"BTC/USDC": df1, "ETH/USDC": df2}

        corr_matrix = correlation_pairlist._calculate_correlation_matrix(price_data)

        assert not corr_matrix.empty
        assert corr_matrix.shape == (2, 2)
        # Perfect correlation should be 1.0
        assert abs(corr_matrix.loc["BTC/USDC", "ETH/USDC"] - 1.0) < 0.01
        assert abs(corr_matrix.loc["ETH/USDC", "BTC/USDC"] - 1.0) < 0.01

    def test_calculate_correlation_matrix_insufficient_data(self, correlation_pairlist):
        """Test correlation matrix with insufficient overlapping data."""
        dates1 = pd.date_range(start="2024-01-01", periods=50, freq="5min")
        dates2 = pd.date_range(start="2024-02-01", periods=50, freq="5min")  # No overlap

        df1 = pd.DataFrame({"date": dates1, "close": [100 + i * 0.1 for i in range(50)]}).set_index(
            "date"
        )
        df1.columns = ["BTC/USDC"]
        df2 = pd.DataFrame({"date": dates2, "close": [200 + i * 0.2 for i in range(50)]}).set_index(
            "date"
        )
        df2.columns = ["ETH/USDC"]

        price_data = {"BTC/USDC": df1, "ETH/USDC": df2}

        corr_matrix = correlation_pairlist._calculate_correlation_matrix(price_data)

        assert corr_matrix.empty

    @patch.object(CorrelationPairList, "_get_correlation_map")
    def test_filter_pairlist(self, mock_get_corr_map, correlation_pairlist):
        """Test filter_pairlist adds correlated pairs."""
        mock_get_corr_map.return_value = {
            "BTC/USDC": ["ETH/USDC", "XRP/USDC", "DOGE/USDC"],
            "ETH/USDC": ["BTC/USDC", "SOL/USDC"],
        }

        pairlist = ["BTC/USDC", "ETH/USDC"]
        result = correlation_pairlist.filter_pairlist(pairlist, {})

        # Base pairs + top 2 correlated per base (max_per_base=2)
        # BTC/USDC -> ETH/USDC, XRP/USDC (ETH already in base)
        # ETH/USDC -> BTC/USDC (already in), SOL/USDC
        expected = ["BTC/USDC", "ETH/USDC", "XRP/USDC", "SOL/USDC"]
        assert result == expected

    @patch.object(CorrelationPairList, "_get_correlation_map")
    def test_filter_pairlist_deduplication(self, mock_get_corr_map, correlation_pairlist):
        """Test that filter_pairlist deduplicates correctly."""
        # max_per_base is 2, so only first 2 correlated per base are considered
        mock_get_corr_map.return_value = {
            "BTC/USDC": ["ETH/USDC", "XRP/USDC"],
            "ETH/USDC": ["BTC/USDC", "XRP/USDC"],  # XRP appears for both, DOGE is 3rd so ignored
        }

        pairlist = ["BTC/USDC", "ETH/USDC"]
        result = correlation_pairlist.filter_pairlist(pairlist, {})

        # XRP/USDC should only appear once
        assert result.count("XRP/USDC") == 1
        assert len(result) == 3  # BTC, ETH, XRP (DOGE is 3rd for ETH, max_per_base=2)

    @patch.object(CorrelationPairList, "_get_correlation_map")
    def test_filter_pairlist_disabled(self, mock_get_corr_map, correlation_pairlist):
        """Test filter_pairlist when disabled."""
        correlation_pairlist._enabled = False
        pairlist = ["BTC/USDC", "ETH/USDC"]
        result = correlation_pairlist.filter_pairlist(pairlist, {})

        assert result == pairlist
        mock_get_corr_map.assert_not_called()

    @patch.object(CorrelationPairList, "_load_price_data")
    def test_get_correlation_map_caching(self, mock_load_price_data, correlation_pairlist):
        """Test that correlation map is cached."""
        dates = pd.date_range(start="2024-01-01", periods=200, freq="5min")
        df1 = pd.DataFrame({"date": dates, "close": [100 + i * 0.1 for i in range(200)]}).set_index(
            "date"
        )
        df1.columns = ["BTC/USDC"]
        df2 = pd.DataFrame({"date": dates, "close": [200 + i * 0.2 for i in range(200)]}).set_index(
            "date"
        )
        df2.columns = ["ETH/USDC"]

        mock_load_price_data.return_value = {"BTC/USDC": df1, "ETH/USDC": df2}

        # First call
        corr_map1 = correlation_pairlist._get_correlation_map()
        # Second call should use cache
        corr_map2 = correlation_pairlist._get_correlation_map()

        assert corr_map1 == corr_map2
        # load_price_data should only be called once due to caching
        assert mock_load_price_data.call_count == 1

    def test_correlation_threshold_filtering(self, correlation_pairlist):
        """Test that only pairs above threshold are included."""
        # Create data with known correlations
        dates = pd.date_range(start="2024-01-01", periods=200, freq="5min")

        # BTC and ETH: high correlation (~0.9)
        btc_prices = [100 + i * 0.1 + (i % 10) * 0.01 for i in range(200)]
        eth_prices = [200 + i * 0.2 + (i % 10) * 0.02 for i in range(200)]

        # XRP: low correlation with BTC (~0.1)
        xrp_prices = [50 + (i * 0.05 * (1 if i % 2 == 0 else -1)) for i in range(200)]

        df_btc = pd.DataFrame({"date": dates, "close": btc_prices}).set_index("date")
        df_btc.columns = ["BTC/USDC"]
        df_eth = pd.DataFrame({"date": dates, "close": eth_prices}).set_index("date")
        df_eth.columns = ["ETH/USDC"]
        df_xrp = pd.DataFrame({"date": dates, "close": xrp_prices}).set_index("date")
        df_xrp.columns = ["XRP/USDC"]

        price_data = {"BTC/USDC": df_btc, "ETH/USDC": df_eth, "XRP/USDC": df_xrp}
        corr_matrix = correlation_pairlist._calculate_correlation_matrix(price_data)

        # Get correlations for BTC
        btc_corrs = corr_matrix.loc["BTC/USDC"].drop("BTC/USDC")

        # ETH should be above threshold (0.7), XRP should be below
        assert btc_corrs["ETH/USDC"] >= 0.7
        assert btc_corrs["XRP/USDC"] < 0.7


class TestCorrelationPairListIntegration:
    """Integration tests for CorrelationPairList."""

    @patch.object(corr_module, "load_data", new_callable=MagicMock)
    def test_full_flow_backtest(self, mock_load_data, correlation_pairlist, mock_pairlistmanager):
        """Test full flow in backtest mode."""
        # Setup mock data
        dates = pd.date_range(start="2024-01-01", periods=200, freq="5min")
        df_btc = pd.DataFrame({"date": dates, "close": [100 + i * 0.1 for i in range(200)]})
        df_eth = pd.DataFrame({"date": dates, "close": [200 + i * 0.2 for i in range(200)]})
        df_xrp = pd.DataFrame({"date": dates, "close": [50 + i * 0.05 for i in range(200)]})
        df_doge = pd.DataFrame({"date": dates, "close": [10 + i * 0.01 for i in range(200)]})

        mock_load_data.return_value = {
            "BTC/USDC": df_btc,
            "ETH/USDC": df_eth,
            "XRP/USDC": df_xrp,
            "DOGE/USDC": df_doge,
        }

        correlation_pairlist._config["runmode"] = RunMode.BACKTEST

        # Base pairlist from StaticPairList
        base_pairs = ["BTC/USDC", "ETH/USDC"]
        result = correlation_pairlist.filter_pairlist(base_pairs, {})

        # Should have base pairs + correlated pairs
        assert "BTC/USDC" in result
        assert "ETH/USDC" in result
        # With perfect correlation, XRP and DOGE might be added depending on threshold
        assert len(result) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

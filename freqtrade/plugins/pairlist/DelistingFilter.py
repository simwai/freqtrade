"""
Filter pairs announced as delisted by Binance.
"""

import json
import logging
import re
import time
from pathlib import Path

import requests

from freqtrade.enums import RunMode
from freqtrade.exchange.exchange_types import Tickers
from freqtrade.plugins.pairlist.IPairList import IPairList, PairlistParameter, SupportsBacktesting


logger = logging.getLogger(__name__)

BINANCE_DELISTING_URL = (
    "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    "?type=1&catalogId=161&pageNo=1&pageSize=20"
)
BINANCE_ARTICLE_DETAIL_URL = (
    "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query?articleCode={code}"
)


class DelistingFilter(IPairList):
    """
    Remove pairs found in new Binance delisting announcements.

    Live-announcement data cannot be reconstructed historically, so the filter
    disables itself during backtesting/hyperopt instead of introducing
    lookahead bias. Existing trades remain in the active whitelist so Freqtrade
    can continue to manage their exits.
    """

    supports_backtesting = SupportsBacktesting.NO_ACTION

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._url = self._pairlistconfig.get("url", BINANCE_DELISTING_URL)
        self._article_detail_url = self._pairlistconfig.get(
            "article_detail_url", BINANCE_ARTICLE_DETAIL_URL
        )
        self._read_timeout = self._pairlistconfig.get("read_timeout", 15)
        self._initial_scan = self._pairlistconfig.get("initial_scan", True)
        state_file = self._pairlistconfig.get("state_file")
        self._state_file = (
            Path(state_file)
            if state_file
            else Path(self._config.get("user_data_dir", Path("user_data"))) / "delisting_state.json"
        )

        self._article_ids: set[str] = set()
        self._delisted_pairs: set[str] = set()
        self._next_refresh = 0.0
        self._load_state()

    @property
    def needstickers(self) -> bool:
        return False

    def short_desc(self) -> str:
        return f"{self.name} - {len(self._delisted_pairs)} delisted pairs"

    @staticmethod
    def description() -> str:
        return "Filter pairs found in Binance delisting announcements."

    @staticmethod
    def available_parameters() -> dict[str, PairlistParameter]:
        return {
            "url": {
                "type": "string",
                "default": BINANCE_DELISTING_URL,
                "description": "Announcement listing API URL",
                "help": "Binance CMS API URL containing the exchange delisting announcements.",
            },
            "article_detail_url": {
                "type": "string",
                "default": BINANCE_ARTICLE_DETAIL_URL,
                "description": "Announcement detail API URL",
                "help": "Binance CMS API URL containing `{code}` for the article code.",
            },
            **IPairList.refresh_period_parameter(),
            "read_timeout": {
                "type": "number",
                "default": 15,
                "description": "Request timeout",
                "help": "HTTP timeout in seconds for announcement requests.",
            },
            "initial_scan": {
                "type": "boolean",
                "default": True,
                "description": "Process announcements already on the page",
                "help": "Process current announcements when no state file exists.",
            },
            "state_file": {
                "type": "string",
                "default": "",
                "description": "Persistent state file",
                "help": "Path for processed article IDs and detected pairs.",
            },
        }

    def filter_pairlist(self, pairlist: list[str], tickers: Tickers) -> list[str]:
        if not self._enabled:
            return pairlist
        if self._config.get("runmode") in (RunMode.BACKTEST, RunMode.EDGE, RunMode.HYPEROPT):
            return pairlist

        self._refresh_delistings()
        filtered = [pair for pair in pairlist if pair not in self._delisted_pairs]
        removed = [pair for pair in pairlist if pair not in filtered]
        if removed:
            self.log_once(
                f"DelistingFilter removed pairs from whitelist: {removed}", logger.warning
            )
        return filtered

    def _refresh_delistings(self) -> None:
        now = time.monotonic()
        if now < self._next_refresh:
            return
        self._next_refresh = now + max(0, self.refresh_period)

        try:
            articles = self._get_article_ids()
        except requests.RequestException as exc:
            logger.warning("Unable to fetch Binance delisting announcements: %s", exc)
            return

        if self._article_ids:
            candidates = [article for article in articles if article[0] not in self._article_ids]
        else:
            candidates = articles if self._initial_scan else []

        processed_ids: set[str] = set()
        for article_id, article_url in candidates:
            try:
                text = self._get_page_text(article_url)
            except requests.RequestException as exc:
                logger.warning("Unable to fetch Binance delisting article %s: %s", article_url, exc)
                continue

            pairs = self._extract_pairs(text)
            processed_ids.add(article_id)
            if pairs:
                new_pairs = set(pairs) - self._delisted_pairs
                self._delisted_pairs.update(pairs)
                if new_pairs:
                    logger.warning("Detected delisted pairs: %s", sorted(new_pairs))

        if not self._initial_scan:
            processed_ids.update(article_id for article_id, _ in articles)

        self._article_ids.update(processed_ids)
        self._save_state()

    def _get_article_ids(self) -> list[tuple[str, str]]:
        payload = self._get_json(self._url)
        catalogs = payload.get("data", {}).get("catalogs", [])
        result: list[tuple[str, str]] = []
        seen_ids: set[str] = set()
        for catalog in catalogs:
            for article in catalog.get("articles", []):
                article_id = str(article.get("id") or article.get("code", ""))
                article_code = article.get("code")
                if not article_id or not article_code:
                    continue
                article_url = self._article_detail_url.format(code=article_code)
                if article_id in seen_ids:
                    continue
                seen_ids.add(article_id)
                result.append((article_id, article_url))
        return result

    def _get_page_text(self, url: str) -> str:
        payload = self._get_json(url)
        return self._json_text(payload.get("data", {}))

    def _get_json(self, url: str) -> dict:
        response = requests.get(
            url,
            headers={"User-Agent": "Freqtrade DelistingFilter"},
            timeout=self._read_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            # Raised as RequestException so _refresh_delistings' handler catches it.
            raise requests.RequestException(
                f"Binance API returned a non-object payload of type {type(payload).__name__}."
            )
        if payload.get("code") != "000000" or not payload.get("success", False):
            raise requests.RequestException(f"Binance API returned an error: {payload}")
        return payload

    def _json_text(self, value: object) -> str:
        if isinstance(value, str):
            try:
                return self._json_text(json.loads(value))
            except json.JSONDecodeError:
                return value
        if isinstance(value, list):
            return " ".join(self._json_text(item) for item in value)
        if isinstance(value, dict):
            parts: list[str] = []
            if isinstance(value.get("text"), str):
                parts.append(value["text"])
            for key in ("title", "body", "content", "child"):
                if key in value:
                    parts.append(self._json_text(value[key]))
            return " ".join(parts)
        return ""

    def _extract_pairs(self, text: str) -> list[str]:
        """Match only symbols supported by this bot's configured exchange."""
        upper_text = text.upper()
        pairs: list[str] = []
        for pair in self._exchange.get_markets():
            symbols = {pair.upper()}
            if ":" in pair:
                # Binance spot announcements can refer to the underlying symbol
                # while the bot is using a futures contract symbol.
                symbols.add(pair.upper().split(":", 1)[0])
            if any(
                re.search(rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])", upper_text)
                for symbol in symbols
            ):
                pairs.append(pair)
        return pairs

    def _load_state(self) -> None:
        if not self._state_file.exists():
            return

        try:
            state = json.loads(self._state_file.read_text(encoding="utf-8"))
            self._article_ids = {
                item for item in state.get("article_ids", []) if isinstance(item, str)
            }
            self._delisted_pairs = {
                item for item in state.get("delisted_pairs", []) if isinstance(item, str)
            }
        except (OSError, json.JSONDecodeError, AttributeError, TypeError) as exc:
            logger.warning("Unable to load delisting state from %s: %s", self._state_file, exc)

    def _save_state(self) -> None:
        state = {
            "article_ids": sorted(self._article_ids),
            "delisted_pairs": sorted(self._delisted_pairs),
        }
        temporary_file = self._state_file.with_name(self._state_file.name + ".tmp")
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            temporary_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            temporary_file.replace(self._state_file)
        except OSError as exc:
            logger.warning("Unable to save delisting state to %s: %s", self._state_file, exc)

from pathlib import Path
from unittest.mock import MagicMock

import requests

from freqtrade.plugins.pairlist.DelistingFilter import DelistingFilter


def _response(content: object) -> MagicMock:
    response = MagicMock()
    response.json.return_value = content
    return response


def _handler(tmp_path: Path, initial_scan: bool = True) -> DelistingFilter:
    exchange = MagicMock()
    exchange.get_markets.return_value = {
        "BTC/USDT": {},
        "ETH/USDT": {},
        "BTC/USDT:USDT": {},
    }
    return DelistingFilter(
        exchange=exchange,
        pairlistmanager=MagicMock(),
        config={"user_data_dir": tmp_path},
        pairlistconfig={
            "refresh_period": 1800,
            "state_file": str(tmp_path / "state.json"),
            "initial_scan": initial_scan,
        },
        pairlist_pos=1,
    )


def test_filter_processes_announcements_and_persists_state(tmp_path, mocker):
    handler = _handler(tmp_path)
    page = {
        "code": "000000",
        "success": True,
        "data": {"catalogs": [{"articles": [{"id": "article-1", "code": "article-1"}]}]},
    }
    article = {"code": "000000", "success": True, "data": {"body": "BTC/USDT"}}
    mocker.patch(
        "freqtrade.plugins.pairlist.DelistingFilter.requests.get",
        side_effect=[_response(page), _response(article)],
    )

    assert handler.filter_pairlist(["BTC/USDT", "ETH/USDT"], {}) == ["ETH/USDT"]
    state = (tmp_path / "state.json").read_text(encoding="utf-8")
    assert "article-1" in state
    assert "BTC/USDT" in state


def test_filter_processes_only_new_articles(tmp_path, mocker):
    handler = _handler(tmp_path)
    page = {
        "code": "000000",
        "success": True,
        "data": {"catalogs": [{"articles": [{"id": 1, "code": "article-1"}]}]},
    }
    updated_page = {
        "code": "000000",
        "success": True,
        "data": {
            "catalogs": [
                {
                    "articles": [
                        {"id": 2, "code": "article-2"},
                        {"id": 1, "code": "article-1"},
                    ]
                }
            ]
        },
    }
    mocker.patch(
        "freqtrade.plugins.pairlist.DelistingFilter.requests.get",
        side_effect=[
            _response(page),
            _response({"code": "000000", "success": True, "data": {"body": "BTC/USDT"}}),
            _response(updated_page),
            _response({"code": "000000", "success": True, "data": {"body": "ETH/USDT"}}),
        ],
    )

    assert handler.filter_pairlist(["BTC/USDT", "ETH/USDT"], {}) == ["ETH/USDT"]
    handler._next_refresh = 0
    assert handler.filter_pairlist(["BTC/USDT", "ETH/USDT"], {}) == []


def test_filter_can_skip_existing_announcements(tmp_path, mocker):
    handler = _handler(tmp_path, initial_scan=False)
    page = {
        "code": "000000",
        "success": True,
        "data": {"catalogs": [{"articles": [{"id": 1, "code": "article-1"}]}]},
    }
    get = mocker.patch(
        "freqtrade.plugins.pairlist.DelistingFilter.requests.get",
        return_value=_response(page),
    )

    assert handler.filter_pairlist(["BTC/USDT", "ETH/USDT"], {}) == [
        "BTC/USDT",
        "ETH/USDT",
    ]
    get.assert_called_once()


def test_filter_keeps_cached_pairs_when_source_fails(tmp_path, mocker):
    handler = _handler(tmp_path)
    handler._delisted_pairs.add("BTC/USDT")
    handler._save_state()

    mocker.patch(
        "freqtrade.plugins.pairlist.DelistingFilter.requests.get",
        side_effect=requests.Timeout("source unavailable"),
    )

    assert handler.filter_pairlist(["BTC/USDT", "ETH/USDT"], {}) == ["ETH/USDT"]


def test_extract_pairs_matches_spot_symbol_in_futures_market(tmp_path):
    handler = _handler(tmp_path)

    assert handler._extract_pairs("The affected market is BTC/USDT") == [
        "BTC/USDT",
        "BTC/USDT:USDT",
    ]

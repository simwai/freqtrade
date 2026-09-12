# freqtrade-local

Local overlay package for custom freqtrade extensions.

## Installation

```bash
pip install -e freqtrade-local
```

## Commands

| Command | Description |
|---|---|
| `freqtrade-edge` | Run edge backtesting |
| `freqtrade-binance-migrate` | Migrate Binance futures pair names |
| `freqtrade-walkforward` | Run walk-forward optimization |
| `freqtrade-lab` | Start SSE log stream server |

## Plugin Discovery

### Pairlists

Place custom pairlists in `freqtrade_local/plugins/pairlist/` and reference them via config:

```json
{
  "pairlist": ["CorrelationPairList", "VolumePairList"],
  "pairlist_path": "/path/to/freqtrade-local/src/freqtrade_local/plugins/pairlist"
}
```

### Hyperopt Losses

Place custom hyperopt losses in `freqtrade_local/plugins/hyperopt_loss/` and reference them via config:

```json
{
  "hyperopt_loss": "DrawdownConstrainedHyperOptLoss",
  "hyperopt_path": "/path/to/freqtrade-local/src/freqtrade_local/plugins/hyperopt_loss"
}
```

## Runtime Patches

Some features require runtime patches to upstream freqtrade:

- **Backtest heartbeat**: Set `backtest_heartbeat_interval` in config (seconds). The overlay patches `Backtesting` to emit heartbeat logs during long backtests.

## Upgrading freqtrade

When a new upstream version is released:

```bash
cd /path/to/freqtrade
git pull upstream develop
pip install -e .
```

The overlay package remains compatible because it imports from freqtrade's public APIs. If internal APIs change, the overlay's test suite will catch breakage.

# Walk-forward Optimization

Walk-forward optimization repeatedly tunes a strategy using older data, then tests the selected
parameters on the next unseen period. This helps measure whether weekly parameter changes would
have worked in the past without using future candles during optimization.

## Historical testing

Use a finite timerange containing enough data for both training and testing:

```bash
freqtrade walk-forward \
    --strategy SampleStrategy \
    --timerange 20220101-20240101 \
    --train-days 90 \
    --test-days 7 \
    --step-days 7 \
    --epochs 100
```

For every window, Freqtrade hyperopts the previous training period and backtests the following
test period. The simulated account is continuous across windows. Parameters found at a weekly
boundary remain pending until existing simulated trades are closed.

Results are saved below:

```text
user_data/walk_forward/<strategy>/<run_id>/walk_forward.json
```

The result contains each training and test range, selected parameters, out-of-sample metrics, and
an aggregate report.

## Live weekly optimization

Run the optimizer separately from the trading bot:

```bash
freqtrade walk-forward --live --run-now --strategy SampleStrategy --config config.json
```

Without `--run-now`, the worker waits for the configured weekly UTC schedule. It publishes a
candidate parameter file after a successful run. The trading bot applies it automatically only
when no trades are open.

Enable the bot-side handoff in the trading configuration:

```json
"walk_forward": {
    "enabled": true,
    "train_days": 90,
    "test_days": 7,
    "step_days": 7,
    "schedule": "sun 00:05",
    "min_trades": 20,
    "max_drawdown": 0.30
}
```

If a result fails the safety limits, the current parameters remain active. Freqtrade never starts
a second optimization while another hyperopt is running.

## Limitations

The first implementation supports regular strategies. FreqAI support is planned separately because
FreqAI has its own rolling model-training and historic-prediction lifecycle.

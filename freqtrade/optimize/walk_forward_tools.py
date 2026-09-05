"""Shared helpers for walk-forward optimization and parameter deployment."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import rapidjson

from freqtrade.configuration import TimeRange
from freqtrade.constants import Config
from freqtrade.misc import deep_merge_dicts
from freqtrade.optimize.hyperopt_tools import hyperopt_serializer


UTC = timezone.utc
DEFAULT_TRAIN_DAYS = 90
DEFAULT_TEST_DAYS = 7
DEFAULT_STEP_DAYS = 7
DEFAULT_SCHEDULE = "sun 00:05"


@dataclass(frozen=True)
class WalkForwardWindow:
    """One in-sample and immediately following out-of-sample period."""

    index: int
    train: TimeRange
    test: TimeRange

    @property
    def train_timerange(self) -> str:
        return self.train.timerange_str

    @property
    def test_timerange(self) -> str:
        return self.test.timerange_str


def walk_forward_settings(config: Config) -> dict[str, Any]:
    settings = config.get("walk_forward", {})
    return {
        "train_days": int(settings.get("train_days", DEFAULT_TRAIN_DAYS)),
        "test_days": int(settings.get("test_days", DEFAULT_TEST_DAYS)),
        "step_days": int(settings.get("step_days", DEFAULT_STEP_DAYS)),
        "schedule": str(settings.get("schedule", DEFAULT_SCHEDULE)),
        "min_trades": int(settings.get("min_trades", 0)),
        "max_drawdown": settings.get("max_drawdown"),
        "pending_file": settings.get("pending_file"),
    }


def _midnight(value: datetime | date) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return datetime.combine(value, time.min, tzinfo=UTC)


def _timerange(start: datetime, end: datetime) -> TimeRange:
    return TimeRange("date", "date", int(start.timestamp()), int(end.timestamp()))


def generate_walk_forward_windows(
    timerange: TimeRange,
    train_days: int = DEFAULT_TRAIN_DAYS,
    test_days: int = DEFAULT_TEST_DAYS,
    step_days: int = DEFAULT_STEP_DAYS,
) -> list[WalkForwardWindow]:
    """Generate non-overlapping, UTC-aligned rolling walk-forward windows."""
    if not timerange.startdt or not timerange.stopdt:
        raise ValueError("Walk-forward testing requires a finite --timerange.")
    if train_days < 1 or test_days < 1 or step_days < 1:
        raise ValueError("Walk-forward periods must be positive numbers of days.")
    if step_days < test_days:
        raise ValueError("Walk-forward step_days must be at least test_days.")

    overall_start = _midnight(timerange.startdt)
    overall_end = _midnight(timerange.stopdt)
    test_start = overall_start + timedelta(days=train_days)
    windows: list[WalkForwardWindow] = []
    index = 1

    while test_start <= overall_end:
        train_start = test_start - timedelta(days=train_days)
        train_end = test_start - timedelta(days=1)
        test_end = min(test_start + timedelta(days=test_days - 1), overall_end)
        if train_start < overall_start or test_end < test_start:
            break

        windows.append(
            WalkForwardWindow(
                index=index,
                train=_timerange(train_start, train_end),
                test=_timerange(test_start, test_end),
            )
        )
        index += 1
        test_start += timedelta(days=step_days)

    if not windows:
        raise ValueError("The timerange is too short for the configured training and test periods.")
    return windows


def live_training_timerange(now: datetime, train_days: int) -> TimeRange:
    """Return a training range ending on the last completed UTC day."""
    last_complete_day = _midnight(now) - timedelta(days=1)
    start = last_complete_day - timedelta(days=train_days - 1)
    return _timerange(start, last_complete_day)


def parse_schedule(value: str) -> tuple[int, time]:
    """Parse a simple ``day HH:MM`` UTC schedule."""
    match = re.fullmatch(r"\s*([A-Za-z]+)\s+(\d{1,2}):(\d{1,2})\s*", value)
    if not match:
        raise ValueError("Walk-forward schedule must look like `sun 00:05`.")

    day_name, hour, minute = match.groups()
    # Normalize single-digit minutes like '0:5' -> '0:05'
    minute = minute.zfill(2)
    day_names = {
        "mon": 0,
        "monday": 0,
        "tue": 1,
        "tuesday": 1,
        "wed": 2,
        "wednesday": 2,
        "thu": 3,
        "thursday": 3,
        "fri": 4,
        "friday": 4,
        "sat": 5,
        "saturday": 5,
        "sun": 6,
        "sunday": 6,
    }
    try:
        day = day_names[day_name.lower()]
        schedule_time = time(int(hour), int(minute))
    except (KeyError, ValueError) as exc:
        raise ValueError("Walk-forward schedule must contain a valid UTC day and time.") from exc
    return day, schedule_time


def next_schedule(now: datetime, schedule: str) -> datetime:
    """Return the next occurrence of a weekly UTC schedule."""
    weekday, schedule_time = parse_schedule(schedule)
    current = now.astimezone(UTC)
    candidate = current.replace(
        hour=schedule_time.hour,
        minute=schedule_time.minute,
        second=0,
        microsecond=0,
    )
    days_ahead = (weekday - current.weekday()) % 7
    candidate += timedelta(days=days_ahead)
    if candidate <= current:
        candidate += timedelta(days=7)
    return candidate


def parameter_file_from_result(
    result: dict[str, Any], strategy_name: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build the normal strategy parameter-file format from a hyperopt result."""
    params = deepcopy(result.get("params_not_optimized", {}))
    deep_merge_dicts(result.get("params_details", {}), params)
    return {
        "strategy_name": strategy_name,
        "params": params,
        "ft_stratparam_v": 1,
        "export_time": datetime.now(UTC),
        "walk_forward": metadata or {},
    }


def write_json_atomic(filename: Path, data: Any) -> None:
    """Write JSON using a replace so readers never observe a partial file."""
    filename.parent.mkdir(parents=True, exist_ok=True)
    temporary = filename.with_name(f".{filename.name}.tmp")
    with temporary.open("w", encoding="utf-8") as fp:
        rapidjson.dump(
            data,
            fp,
            default=hyperopt_serializer,
            number_mode=rapidjson.NM_NATIVE | rapidjson.NM_NAN,
        )
    temporary.replace(filename)


def read_json(filename: Path) -> dict[str, Any]:
    with filename.open("r", encoding="utf-8") as fp:
        return rapidjson.load(fp, number_mode=rapidjson.NM_NATIVE | rapidjson.NM_NAN)


def pending_parameter_file(config: Config, strategy_name: str) -> Path:
    settings = walk_forward_settings(config)
    configured = settings.get("pending_file")
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = Path(config["user_data_dir"]) / path
        return path
    return Path(config["user_data_dir"]) / "walk_forward" / strategy_name / "pending.json"

"""Shared helpers for walk-forward optimization and parameter deployment."""

from __future__ import annotations

import re
import time as time_module
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


def capture_resource_snapshot() -> dict[str, Any]:  # noqa: C901
    """Capture current process and system resource usage for walk-forward cost estimation."""
    snapshot: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "perf_counter": time_module.perf_counter(),
    }
    try:
        import psutil

        proc = psutil.Process()
        try:
            mem = proc.memory_info()
            cpu = proc.cpu_times()
            rss = int(mem.rss)
            vms = int(mem.vms)
            cpu_total = float(cpu.user + cpu.system)
            # Include child processes (joblib workers) for a realistic total.
            children: list[Any] = []
            try:
                children = proc.children(recursive=True)
            except Exception:  # noqa: BLE001
                children = []
            for child in children:
                try:
                    cm = child.memory_info()
                    cc = child.cpu_times()
                    rss += int(cm.rss)
                    vms += int(cm.vms)
                    cpu_total += float(cc.user + cc.system)
                except Exception:  # noqa: BLE001, S112
                    continue
            vm = psutil.virtual_memory()
            cpu_logical = int(psutil.cpu_count(logical=True) or 1)
            cpu_physical = int(psutil.cpu_count(logical=False) or 1)
            # CPU frequency for GHz quoting (total across cores).
            cpu_freq_current_mhz: float | None = None
            cpu_total_ghz: float | None = None
            try:
                freq = psutil.cpu_freq()
                if freq and freq.current:
                    cpu_freq_current_mhz = float(freq.current)
                    cpu_total_ghz = round(cpu_freq_current_mhz * cpu_logical / 1000, 2)
                # Prefer per-cpu sum when available and complete.
                freqs = psutil.cpu_freq(percpu=True)
                if freqs and len(freqs) == cpu_logical:
                    total = sum(float(f.current) for f in freqs if f.current)
                    if total > 0:
                        # Sanity: per-cpu total should be ~ logical * current, else ignore.
                        per_cpu_total = round(total / 1000, 2)
                        if (
                            abs(per_cpu_total - (cpu_total_ghz or 0)) < 1
                            or per_cpu_total > (cpu_total_ghz or 0) * 0.5
                        ):
                            cpu_total_ghz = per_cpu_total
                        if not cpu_freq_current_mhz:
                            cpu_freq_current_mhz = round(total / len(freqs), 2)
            except Exception:  # noqa: BLE001, S110
                pass
            snapshot.update(
                {
                    "rss_mb": round(rss / (1024 * 1024), 2),
                    "vms_mb": round(vms / (1024 * 1024), 2),
                    "cpu_total_s": round(cpu_total, 2),
                    "proc_cpu_user_s": round(float(cpu.user), 2),
                    "proc_cpu_system_s": round(float(cpu.system), 2),
                    "memory_percent": round(float(proc.memory_percent()), 2),
                    "system_ram_percent": round(float(vm.percent), 2),
                    "system_ram_total_mb": round(float(vm.total / (1024 * 1024)), 2),
                    "system_ram_available_mb": round(float(vm.available / (1024 * 1024)), 2),
                    "cpu_count_logical": cpu_logical,
                    "cpu_count_physical": cpu_physical,
                    "cpu_freq_current_mhz": cpu_freq_current_mhz,
                    "cpu_total_ghz": cpu_total_ghz,
                    "children_count": len(children),
                }
            )
        except ImportError:
            snapshot.update(
                {
                    "rss_mb": None,
                    "cpu_total_s": None,
                }
            )
        except Exception:  # noqa: BLE001, S110
            pass
    except Exception:  # noqa: BLE001, S110
        pass
    return snapshot


def compute_resource_delta(
    start: dict[str, Any], end: dict[str, Any], extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compute wall and CPU deltas between two snapshots."""
    wall_s = round(float(end.get("perf_counter", 0) - start.get("perf_counter", 0)), 2)
    cpu_s: float | None = None
    if start.get("cpu_total_s") is not None and end.get("cpu_total_s") is not None:
        cpu_s = round(float(end["cpu_total_s"] - start["cpu_total_s"]), 2)
    rss_before = start.get("rss_mb")
    rss_after = end.get("rss_mb")
    peak_rss = None
    if isinstance(rss_before, int | float) and isinstance(rss_after, int | float):
        peak_rss = round(max(float(rss_before), float(rss_after)), 2)
    elif isinstance(rss_after, int | float):
        peak_rss = round(float(rss_after), 2)
    elif isinstance(rss_before, int | float):
        peak_rss = round(float(rss_before), 2)

    cpu_count = end.get("cpu_count_logical") or start.get("cpu_count_logical") or 1
    avg_cpu_pct: float | None = None
    if cpu_s is not None and wall_s > 0:
        avg_cpu_pct = round((cpu_s / wall_s / float(cpu_count)) * 100, 1)

    result: dict[str, Any] = {
        "wall_s": wall_s,
        "cpu_total_s": cpu_s,
        "avg_cpu_pct": avg_cpu_pct,
        "rss_before_mb": rss_before,
        "rss_after_mb": rss_after,
        "peak_rss_mb": peak_rss,
        "system_ram_percent": end.get("system_ram_percent"),
        "cpu_count_logical": end.get("cpu_count_logical") or start.get("cpu_count_logical"),
        "cpu_count_physical": end.get("cpu_count_physical") or start.get("cpu_count_physical"),
        "cpu_freq_current_mhz": end.get("cpu_freq_current_mhz")
        or start.get("cpu_freq_current_mhz"),
        "cpu_total_ghz": end.get("cpu_total_ghz") or start.get("cpu_total_ghz"),
        "wall_human": _human_seconds(wall_s),
    }
    if cpu_s is not None:
        result["cpu_human"] = _human_seconds(cpu_s)
        result["cpu_hours"] = round(cpu_s / 3600, 4)
        # GB-hours = (peak GB) * (wall hours)
        if isinstance(peak_rss, int | float):
            result["gb_hours"] = round(float(peak_rss) / 1024 * wall_s / 3600, 4)
    if extra:
        result.update(extra)
    return result


def _human_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m ({seconds:.0f}s)"
    return f"{seconds / 3600:.2f}h ({seconds:.0f}s)"


def estimate_daily_weekly(
    avg_wall_s: float | None,
    avg_cpu_s: float | None,
    avg_rss_mb: float | None,
    step_days: int,
    wall_total_s: float | None = None,
) -> dict[str, Any]:
    """Estimate per-day and per-week cost from an average window cost."""
    if avg_wall_s is None or avg_wall_s <= 0:
        return {}
    windows_per_week = 7 / max(step_days, 1)
    windows_per_day = windows_per_week / 7
    est: dict[str, Any] = {}
    for label, factor in (("per_day", windows_per_day), ("per_week", windows_per_week)):
        wall = round(avg_wall_s * factor, 1)
        cpu = round(avg_cpu_s * factor, 1) if isinstance(avg_cpu_s, int | float) else None
        entry: dict[str, Any] = {
            "wall_s": wall,
            "wall_human": _human_seconds(float(wall)),
            "windows": round(factor, 3),
        }
        if cpu is not None:
            entry["cpu_s"] = cpu
            entry["cpu_hours"] = round(cpu / 3600, 4)
            entry["cpu_human"] = _human_seconds(float(cpu))
        if isinstance(avg_rss_mb, int | float):
            entry["peak_rss_mb"] = round(float(avg_rss_mb), 1)
            entry["gb_hours"] = round(float(avg_rss_mb) / 1024 * wall / 3600, 4)
        est[label] = entry
    if isinstance(wall_total_s, int | float):
        est["total_measured_wall_s"] = round(float(wall_total_s), 1)
        est["total_measured_wall_human"] = _human_seconds(float(wall_total_s))
    return est


def format_resource_line(
    label: str, resource: dict[str, Any], estimate: dict[str, Any] | None = None
) -> str:
    """One-line human summary for log output - quotable for infra sizing."""
    wall = resource.get("wall_human") or f"{resource.get('wall_s')}s"
    peak = resource.get("peak_rss_mb")
    if isinstance(peak, int | float):
        peak_s = f"{peak / 1024:.2f} GB" if peak >= 1024 else f"{peak:.0f} MB"
    else:
        peak_s = "n/a"
    cores = resource.get("cpu_count_logical")
    total_ghz = resource.get("cpu_total_ghz")
    freq_mhz = resource.get("cpu_freq_current_mhz")
    if isinstance(cores, int) and isinstance(total_ghz, int | float):
        if isinstance(freq_mhz, int | float):
            per_core_ghz = float(freq_mhz) / 1000
            cores_s = f", {cores} cores @ {per_core_ghz:.2f} GHz ({float(total_ghz):.2f} GHz total)"
        else:
            cores_s = f", {cores} cores ({float(total_ghz):.2f} GHz total)"
    elif isinstance(cores, int):
        cores_s = f", {cores} cores"
    else:
        cores_s = ""
    # Optional hyperopt/backtest split (for window detail).
    split_s = ""
    hw = resource.get("hyperopt_wall_s")
    bw = resource.get("backtest_wall_s")
    if isinstance(hw, int | float) and isinstance(bw, int | float):
        split_s = f" (hyperopt {_human_seconds(float(hw))} + backtest {_human_seconds(float(bw))})"

    base = f"{label}: wall {wall}{split_s}, peak RAM {peak_s}{cores_s}"

    if estimate and "per_day" in estimate and "per_week" in estimate:
        pd = estimate["per_day"]
        pw = estimate["per_week"]
        # Only show daily/weekly if meaningful (>1s)
        if isinstance(pd.get("wall_s"), int | float) and pd["wall_s"] >= 1:
            base += f" | ~{pd.get('wall_human')}/day, ~{pw.get('wall_human')}/week"
        elif isinstance(pw.get("wall_s"), int | float) and pw["wall_s"] >= 1:
            base += f" | ~{pw.get('wall_human')}/week (~{pd.get('wall_human')}/day)"
    return base

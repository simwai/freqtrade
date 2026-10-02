"""Schedule command - sets up automated weekly walk-forward retraining via system cron/Windows Task Scheduler."""

import argparse
import logging
import platform
import subprocess
import sys

logger = logging.getLogger(__name__)


def start_schedule(args: list[str] | None = None) -> int:
    """
    Schedule weekly walk-forward retraining.

    Creates a cron job (Linux/macOS) or Windows Task Scheduler entry
    that runs walk-forward optimization on a weekly schedule.
    """
    parser = argparse.ArgumentParser(
        description="Freqtrade Schedule - sets up automated weekly walk-forward retraining"
    )
    parser.add_argument("--strategy", required=True, help="Strategy class name")
    parser.add_argument("--cron", default="0 0 * * 0", help="Cron expression (default: Sundays 00:00 UTC)")
    parser.add_argument("--config", default=None, help="Config file path override")
    parser.add_argument("--timerange", default=None, help="Timerange (default: auto)")
    parser.add_argument("--train-days", type=int, default=90, help="Training window days")
    parser.add_argument("--test-days", type=int, default=7, help="Test window days")
    parser.add_argument("--step-days", type=int, default=7, help="Step days")
    parser.add_argument("--epochs", type=int, default=50, help="Hyperopt epochs per window")
    parser.add_argument("--remove", action="store_true", help="Remove existing schedule")
    parser.add_argument("--list", action="store_true", help="List scheduled tasks")
    parser.add_argument("--user", action="store_true", help="Install as user cron (not system)")

    # Handle being called via freqtrade CLI
    if args is not None and not isinstance(args, list):
        ns = args
        args = [
            f"--strategy={getattr(ns, 'strategy', '')}",
            f"--cron={getattr(ns, 'cron', '0 0 * * 0')}",
        ]
        if getattr(ns, "config", None):
            args.append(f"--config={ns.config}")
        if getattr(ns, "timerange", None):
            args.append(f"--timerange={ns.timerange}")
        if getattr(ns, "train_days", None):
            args.append(f"--train-days={ns.train_days}")
        if getattr(ns, "test_days", None):
            args.append(f"--test-days={ns.test_days}")
        if getattr(ns, "step_days", None):
            args.append(f"--step-days={ns.step_days}")
        if getattr(ns, "epochs", None):
            args.append(f"--epochs={ns.epochs}")
        if getattr(ns, "remove", None):
            args.append("--remove")
        if getattr(ns, "list", None):
            args.append("--list")
        if getattr(ns, "user", None):
            args.append("--user")

    cli_args = parser.parse_args(args)

    system = platform.system()
    is_windows = system == "Windows"
    task_name = f"freqtrade_wf_{cli_args.strategy.lower()}"

    try:
        if cli_args.list:
            return list_scheduled_tasks(task_name, is_windows)

        if cli_args.remove:
            return remove_scheduled_task(task_name, is_windows)

        # Build the command to run
        base_cmd = ["freqtrade", "walkforward"]
        if cli_args.config:
            base_cmd += ["-c", cli_args.config]
        base_cmd += [
            "--strategy", cli_args.strategy,
            "--train-days", str(cli_args.train_days),
            "--test-days", str(cli_args.test_days),
            "--step-days", str(cli_args.step_days),
            "--epochs", str(cli_args.epochs),
        ]
        if cli_args.timerange:
            base_cmd += ["--timerange", cli_args.timerange]

        command_str = " ".join(base_cmd)
        logger.info(f"Scheduling walk-forward for {cli_args.strategy}")
        logger.info(f"Command: {command_str}")
        logger.info(f"Schedule: {cli_args.cron}")

        if is_windows:
            return schedule_windows_task(task_name, command_str, cli_args.cron)
        else:
            return schedule_cron_job(task_name, command_str, cli_args.cron, cli_args.user)

    except Exception as e:
        logger.error(f"Scheduling failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def schedule_cron_job(task_name: str, command: str, cron_expr: str, user: bool = True) -> int:
    """Install a cron job on Linux/macOS."""
    # Build the cron entry
    cron_entry = f"{cron_expr} {command} >> /var/log/freqtrade_{task_name}.log 2>&1"

    if user:
        # User crontab
        logger.info("Installing user cron job...")
        try:
            # Get current crontab
            result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            current_cron = result.stdout if result.returncode == 0 else ""

            # Remove existing entry for this task
            lines = [line for line in current_cron.splitlines() if task_name not in line]

            # Add new entry
            lines.append(cron_entry)
            new_cron = "\n".join(lines) + "\n"

            # Write back
            proc = subprocess.run(["crontab", "-"], input=new_cron, text=True, capture_output=True)
            if proc.returncode != 0:
                logger.error(f"Failed to install cron: {proc.stderr}")
                return 1

            logger.info(f"✅ User cron job installed: {task_name}")
            logger.info(f"   Schedule: {cron_expr}")
            logger.info(f"   Command: {command}")
            return 0

        except Exception as e:
            logger.error(f"Cron installation failed: {e}")
            return 1
    else:
        # System crontab (requires sudo)
        cron_file = f"/etc/cron.d/freqtrade_{task_name}"
        cron_content = f"{cron_entry}\n"

        logger.info(f"Installing system cron job to {cron_file} (requires sudo)...")
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".cron", delete=False) as f:
                f.write(cron_content)
                temp_file = f.name

            result = subprocess.run(["sudo", "cp", temp_file, cron_file], capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to install system cron: {result.stderr}")
                logger.info("Try with --user flag for user-level cron")
                return 1

            subprocess.run(["sudo", "chmod", "644", cron_file], check=True)
            logger.info(f"✅ System cron job installed: {cron_file}")
            return 0
        except Exception as e:
            logger.error(f"System cron installation failed: {e}")
            return 1


def schedule_windows_task(task_name: str, command: str, cron_expr: str) -> int:
    """Create a Windows Task Scheduler task from cron expression."""
    parts = cron_expr.split()
    if len(parts) != 5:
        logger.error(f"Invalid cron expression: {cron_expr}")
        return 1

    minute, hour, day_of_month, month, day_of_week = parts

    if day_of_week != "*" and day_of_month == "*" and month == "*":
        days_map = {"0": "SUN", "1": "MON", "2": "TUE", "3": "WED", "4": "THU", "5": "FRI", "6": "SAT"}
        day_name = days_map.get(day_of_week, "SUN")
        schedule_type = "WEEKLY"
        day_arg = f"/D {day_name}"
    elif day_of_month != "*" and month != "*":
        schedule_type = "MONTHLY"
        day_arg = f"/D {day_of_month}"
    else:
        schedule_type = "DAILY"
        day_arg = ""

    time_str = f"{hour.zfill(2)}:{minute.zfill(2)}"
    escaped_command = command.replace('"', '\\"')

    schtasks_cmd = [
        "schtasks", "/Create",
        "/TN", task_name,
        "/TR", f'cmd /c "{escaped_command}"',
        "/SC", schedule_type,
        "/ST", time_str,
        "/F",
    ]

    if day_arg:
        schtasks_cmd.extend(day_arg.split())

    logger.info(f"Creating Windows task: {task_name}")
    logger.info(f"Schedule: {schedule_type} at {time_str}")
    logger.info(f"Command: {command}")

    try:
        result = subprocess.run(schtasks_cmd, capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            logger.error(f"Failed to create task: {result.stderr}")
            logger.info("Try running as Administrator")
            return 1

        logger.info(f"✅ Windows Task Scheduler task created: {task_name}")
        return 0
    except Exception as e:
        logger.error(f"Task creation failed: {e}")
        return 1


def list_scheduled_tasks(task_name: str, is_windows: bool) -> int:
    """List scheduled tasks for this strategy."""
    if is_windows:
        cmd = ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST", "/V"]
    else:
        cmd = ["crontab", "-l"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(result.stdout)
        else:
            logger.info(f"No scheduled tasks found for {task_name}")
        return 0
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        return 1


def remove_scheduled_task(task_name: str, is_windows: bool) -> int:
    """Remove scheduled task."""
    if is_windows:
        cmd = ["schtasks", "/Delete", "/TN", task_name, "/F"]
    else:
        try:
            result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            if result.returncode == 0:
                lines = [line for line in result.stdout.splitlines() if task_name not in line]
                new_cron = "\n".join(lines) + "\n"
                proc = subprocess.run(["crontab", "-"], input=new_cron, text=True, capture_output=True)
                if proc.returncode == 0:
                    logger.info(f"✅ Removed cron job: {task_name}")
                    return 0
        except Exception as e:
            logger.error(f"Failed to remove cron: {e}")
            return 1
        return 0

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if result.returncode == 0:
            logger.info(f"✅ Removed scheduled task: {task_name}")
            return 0
        else:
            logger.error(f"Failed to remove task: {result.stderr}")
            return 1
    except Exception as e:
        logger.error(f"Task removal failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(start_schedule())
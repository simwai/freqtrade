"""
This module contain functions to load the configuration file
"""

import logging
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import rapidjson

from freqtrade.constants import MINIMAL_CONFIG, Config
from freqtrade.exceptions import ConfigurationError, OperationalException
from freqtrade.misc import deep_merge_dicts


logger = logging.getLogger(__name__)


CONFIG_PARSE_MODE = rapidjson.PM_COMMENTS | rapidjson.PM_TRAILING_COMMAS


def log_config_error_range(path: str, errmsg: str) -> str:
    """
    Parses configuration file and prints range around error
    """
    if path != "-":
        offsetlist = re.findall(r"(?<=Parse\serror\sat\soffset\s)\d+", errmsg)
        if offsetlist:
            offset = int(offsetlist[0])
            text = Path(path).read_text()
            # Fetch an offset of 80 characters around the error line
            subtext = text[offset - min(80, offset) : offset + 80]
            segments = subtext.split("\n")
            if len(segments) > 3:
                # Remove first and last lines, to avoid odd truncations
                return "\n".join(segments[1:-1])
            else:
                return subtext
    return ""


def load_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("r") as file:
            config = rapidjson.load(file, parse_mode=CONFIG_PARSE_MODE)
    except FileNotFoundError:
        raise OperationalException(f'File "{path}" not found!') from None
    return config


def _resolve_config_path(filename: str, user_data_dir: Path | None) -> Path:
    """
    Resolve a config file path. Tries the filename as-given first, then
    falls back to user_data_dir when the filename is a bare relative name.
    """
    candidate = Path(filename)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    if user_data_dir is not None and not filename.startswith(("/", "\\")):
        fallback = user_data_dir / filename
        if fallback.exists():
            logger.info("Config file resolved via user_data_dir: %s", fallback)
            return fallback
    return candidate


def load_config_file(path: str) -> dict[str, Any]:
    """
    Loads a config file from the given path
    :param path: path as str
    :return: configuration as dictionary
    """
    try:
        # Read config from stdin if requested in the options
        with Path(path).open() if path != "-" else sys.stdin as file:
            config = rapidjson.load(file, parse_mode=CONFIG_PARSE_MODE)
    except FileNotFoundError:
        raise OperationalException(
            f'Config file "{path}" not found!'
            " Please create a config file or check whether it exists."
        ) from None
    except rapidjson.JSONDecodeError as e:
        err_range = log_config_error_range(path, str(e))
        raise ConfigurationError(
            f"{e}\nPlease verify the following segment of your configuration:\n{err_range}"
            if err_range
            else "Please verify your configuration file for syntax errors."
        )

    return config


def load_from_files(
    files: list[str],
    base_path: Path | None = None,
    level: int = 0,
    user_data_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Recursively load configuration files if specified.
    Sub-files are assumed to be relative to the initial config.
    """
    config: Config = {}
    if level > 5:
        raise ConfigurationError("Config loop detected.")

    if not files:
        return deepcopy(MINIMAL_CONFIG)
    files_loaded = []
    # We expect here a list of config filenames
    for filename in files:
        logger.info(f"Using config: {filename} ...")
        if filename == "-":
            # Immediately load stdin and return
            return load_config_file(filename)
        file = Path(filename)
        if base_path:
            # Prepend basepath to allow for relative assignments
            file = base_path / file
        else:
            # why: bare relative config paths also resolve under user_data_dir
            # so users can run from the repo root without typing the full path.
            # cwd-relative resolution is preserved; this is purely additive.
            file = _resolve_config_path(filename, user_data_dir)

        config_tmp = load_config_file(str(file))
        if "add_config_files" in config_tmp:
            config_sub = load_from_files(
                config_tmp["add_config_files"],
                file.resolve().parent,
                level + 1,
            )
            files_loaded.extend(config_sub.get("config_files", []))
            config_tmp = deep_merge_dicts(config_tmp, config_sub)

        files_loaded.insert(0, str(file))

        # Merge config options, overwriting prior values
        config = deep_merge_dicts(config_tmp, config)

    config["config_files"] = files_loaded

    return config

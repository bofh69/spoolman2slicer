#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Common utility functions for spoolman2slicer.
"""

import os
import tempfile
import appdirs
from .constants import APP_NAME, APP_AUTHOR, Slicers


def get_user_config_dir():
    """Returns the standardized roaming configuration directory."""
    return appdirs.user_config_dir(appname=APP_NAME, appauthor=APP_AUTHOR, roaming=True)


def is_json_slicer(slicer_name):
    """Returns True if the slicer uses JSON-based configuration (Orca/Creality)."""
    try:
        return Slicers(slicer_name).is_json
    except ValueError:
        return False


def _sanitize_env_val(val):
    """Strip quotes and whitespace from environment variable values."""
    if val is None:
        return None
    val = val.strip()
    if len(val) >= 2 and (
        (val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")
    ):
        val = val[1:-1]
    return val.strip()


def get_env_bool(name, legacy_name=None, default=False):
    """Helper to parse boolean environment variables with explicit validation."""
    val = _sanitize_env_val(os.environ.get(name))
    if val is None and legacy_name:
        val = _sanitize_env_val(os.environ.get(legacy_name))

    if not val:
        return default
    val_lower = val.lower()
    if val_lower in ("true", "1", "yes", "on"):
        return True
    if val_lower in ("false", "0", "no", "off"):
        return False

    # Construct descriptive error message
    err_msg = f"Invalid boolean environment variable {name}"
    if legacy_name:
        err_msg += f" or {legacy_name}"
    err_msg += f": {val!r}. Use: true/false, 1/0, yes/no, or on/off."

    raise ValueError(err_msg)


def get_arg_default(parser, name, legacy_name=None, default_val=False):
    """Safely fetch boolean defaults from environment for argparse."""
    try:
        return get_env_bool(name, legacy_name=legacy_name, default=default_val)
    except ValueError as err:
        parser.error(str(err))
        return None  # Satisfies pylint R1710; parser.error calls sys.exit


def get_env_str(name, legacy_name=None, default=None):
    """Fetch string value from env with sanitization and legacy fallback."""
    val = _sanitize_env_val(os.environ.get(name))
    if val is None and legacy_name:
        val = _sanitize_env_val(os.environ.get(legacy_name))
    return val if val is not None else default


def get_env_choice(parser, name, choices, legacy_name=None, default=None):
    """Fetch value from env and validate against choices during parser initialization."""
    val = get_env_str(name, legacy_name=legacy_name)

    if not val:
        return default

    val_lower = val.lower()
    if val_lower in choices:
        return val_lower

    env_name_str = f"environment variable {name}"
    if legacy_name:
        env_name_str += f" (or legacy {legacy_name})"

    parser.error(f"Invalid {env_name_str}: {val!r}. Choose from: {choices}")
    return None


def atomic_write(filename, content, encoding="utf-8"):
    """
    Write content to a file atomically.

    Writes to a temporary file in the same directory first, then atomically
    renames it to the target filename. This prevents partial writes if the
    process is interrupted.

    Args:
        filename: Path to the target file
        content: Content to write to the file
        encoding: Text encoding (default: utf-8)
    """
    # Create temporary file in the same directory to ensure atomic rename works
    # (os.replace is atomic only on the same filesystem)
    directory = os.path.dirname(filename) or "."
    basename = os.path.basename(filename)

    # Create a temporary file with delete=False so we can rename it
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding=encoding,
        dir=directory,
        prefix=f".tmp_{basename}_",
        suffix=".tmp",
        delete=False,
    ) as tmp_file:
        tmp_filename = tmp_file.name
        tmp_file.write(content)
        # Ensure data is written to disk
        tmp_file.flush()
        try:
            os.fsync(tmp_file.fileno())
        except (AttributeError, OSError):
            # Fallback if fsync is not supported (e.g. some virtual filesystems)
            pass

    try:
        # Atomically replace the target file
        # os.replace is atomic on both POSIX and Windows
        os.replace(tmp_filename, filename)
    except Exception:
        # Clean up temporary file if rename fails
        try:
            os.unlink(tmp_filename)
        except OSError:
            pass  # Ignore cleanup errors
        raise

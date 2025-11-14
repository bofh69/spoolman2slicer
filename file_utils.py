#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Common file utilities for spoolman2slicer.
"""

import os
import tempfile


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
        os.fsync(tmp_file.fileno())

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

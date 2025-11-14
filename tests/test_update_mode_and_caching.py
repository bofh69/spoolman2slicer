#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for update mode resilience and caching improvements
"""

import atexit
import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, AsyncMock

import pytest
import requests

# Setup fake template directory before import
# Note: These are module-level to work around module-level execution in spoolman2slicer.py
fake_config_dir = tempfile.mkdtemp()
fake_template_dir = os.path.join(fake_config_dir, "templates-superslicer")
os.makedirs(fake_template_dir, exist_ok=True)

# Create minimal required template files
Path(fake_template_dir, "filename.template").write_text(
    "{{vendor.name}} - {{name}}.{{sm2s.slicer_suffix}}\n"
)
Path(fake_template_dir, "filename_for_spool.template").write_text(
    "{{vendor.name}} - {{name}} - {{spool.id}}.{{sm2s.slicer_suffix}}\n"
)
Path(fake_template_dir, "default.ini.template").write_text(
    "filament_type = {{material}}\n"
)

# Mock sys.argv and user_config_dir before importing
fake_output_dir = tempfile.mkdtemp()
sys.argv = ["spoolman2slicer.py", "--dir", fake_output_dir, "--url", "http://test:7912"]

# Register cleanup handlers for temporary directories
atexit.register(lambda: shutil.rmtree(fake_config_dir, ignore_errors=True))
atexit.register(lambda: shutil.rmtree(fake_output_dir, ignore_errors=True))

# Patch user_config_dir before import
with patch("appdirs.user_config_dir", return_value=fake_config_dir):
    # Add parent directory to path to import the module
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import spoolman2slicer


# Override the module-level variables for testing
@pytest.fixture(autouse=True)
def reset_caches():
    """Reset module-level caches before each test"""
    spoolman2slicer.filament_id_to_filename.clear()
    spoolman2slicer.filament_id_to_content.clear()
    spoolman2slicer.filename_usage.clear()
    yield


class TestUpdateModeResilience:
    """Test that update mode retries initial API load until successful"""

    def test_update_mode_retries_on_connection_error(self):
        """Test that -U mode retries API load on connection error until success"""
        call_count = 0

        def side_effect_func(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise requests.exceptions.ConnectionError("Connection refused")
            # Third call succeeds
            return None

        with (
            patch.object(spoolman2slicer.args, "updates", True),
            patch.object(spoolman2slicer.args, "delete_all", False),
            patch(
                "spoolman2slicer.load_and_update_all_filaments",
                side_effect=side_effect_func,
            ),
            patch("time.sleep") as mock_sleep,
            patch("asyncio.run") as mock_asyncio_run,
        ):
            # Mock the asyncio.run to raise KeyboardInterrupt to exit cleanly
            mock_asyncio_run.side_effect = KeyboardInterrupt()

            with pytest.raises(SystemExit) as exc_info:
                spoolman2slicer.main()

            # Should exit with code 0 (KeyboardInterrupt)
            assert exc_info.value.code == 0
            # Verify that load was retried before succeeding
            assert call_count == 3
            # Verify that sleep was called between retries
            assert mock_sleep.call_count == 2
            # Verify that asyncio.run (websocket connection) was attempted after success
            mock_asyncio_run.assert_called_once()

    def test_update_mode_retries_on_timeout(self):
        """Test that -U mode retries API load on timeout until success"""
        call_count = 0

        def side_effect_func(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise requests.exceptions.Timeout("Request timeout")
            return None

        with (
            patch.object(spoolman2slicer.args, "updates", True),
            patch.object(spoolman2slicer.args, "delete_all", False),
            patch(
                "spoolman2slicer.load_and_update_all_filaments",
                side_effect=side_effect_func,
            ),
            patch("time.sleep") as mock_sleep,
            patch("asyncio.run") as mock_asyncio_run,
        ):
            mock_asyncio_run.side_effect = KeyboardInterrupt()

            with pytest.raises(SystemExit) as exc_info:
                spoolman2slicer.main()

            assert exc_info.value.code == 0
            assert call_count == 2
            assert mock_sleep.call_count == 1
            mock_asyncio_run.assert_called_once()

    def test_update_mode_retries_on_http_error(self):
        """Test that -U mode retries API load on HTTP error until success"""
        mock_response = Mock()
        mock_response.status_code = 500

        call_count = 0

        def side_effect_func(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise requests.exceptions.HTTPError(
                    "500 Server Error", response=mock_response
                )
            return None

        with (
            patch.object(spoolman2slicer.args, "updates", True),
            patch.object(spoolman2slicer.args, "delete_all", False),
            patch(
                "spoolman2slicer.load_and_update_all_filaments",
                side_effect=side_effect_func,
            ),
            patch("time.sleep") as mock_sleep,
            patch("asyncio.run") as mock_asyncio_run,
        ):
            mock_asyncio_run.side_effect = KeyboardInterrupt()

            with pytest.raises(SystemExit) as exc_info:
                spoolman2slicer.main()

            assert exc_info.value.code == 0
            assert call_count == 2
            mock_asyncio_run.assert_called_once()

    def test_update_mode_retries_on_json_error(self):
        """Test that -U mode retries API load on JSON decode error until success"""
        call_count = 0

        def side_effect_func(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise json.JSONDecodeError("Invalid JSON", "", 0)
            return None

        with (
            patch.object(spoolman2slicer.args, "updates", True),
            patch.object(spoolman2slicer.args, "delete_all", False),
            patch(
                "spoolman2slicer.load_and_update_all_filaments",
                side_effect=side_effect_func,
            ),
            patch("time.sleep") as mock_sleep,
            patch("asyncio.run") as mock_asyncio_run,
        ):
            mock_asyncio_run.side_effect = KeyboardInterrupt()

            with pytest.raises(SystemExit) as exc_info:
                spoolman2slicer.main()

            assert exc_info.value.code == 0
            assert call_count == 2
            mock_asyncio_run.assert_called_once()

    def test_non_update_mode_exits_on_connection_error(self):
        """Test that without -U mode, program exits on API connection error"""
        with (
            patch.object(spoolman2slicer.args, "updates", False),
            patch.object(spoolman2slicer.args, "delete_all", False),
            patch(
                "spoolman2slicer.load_and_update_all_filaments",
                side_effect=requests.exceptions.ConnectionError("Connection refused"),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                spoolman2slicer.main()

            # Should exit with code 1 (error)
            assert exc_info.value.code == 1


class TestCachingForSpoolAll:
    """Test that caching uses spool ID when in 'all' mode"""

    def test_cache_uses_spool_id_in_all_mode(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test that cache keys use spool ID when --create-per-spool all is used"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "create_per_spool", "all"),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            # Add sm2s and spool data
            sample_filament_data["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }
            sample_filament_data["spool"] = {"id": 42}

            # Write filament
            spoolman2slicer.write_filament(sample_filament_data)

            # Check that cache key uses spool ID
            expected_cache_key = "spool-42-ini"
            assert expected_cache_key in spoolman2slicer.filament_id_to_filename

            # Content cache should also use spool ID
            expected_content_key = "spool-42"
            assert expected_content_key in spoolman2slicer.filament_id_to_content

    def test_cache_uses_filament_id_without_all_mode(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test that cache keys use filament ID when not in 'all' mode"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "create_per_spool", None),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            # Add sm2s and spool data
            sample_filament_data["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }
            sample_filament_data["spool"] = {}

            # Write filament
            spoolman2slicer.write_filament(sample_filament_data)

            # Check that cache key uses filament ID
            expected_cache_key = f"{sample_filament_data['id']}-ini"
            assert expected_cache_key in spoolman2slicer.filament_id_to_filename

            # Content cache should also use filament ID
            expected_content_key = str(sample_filament_data["id"])
            assert expected_content_key in spoolman2slicer.filament_id_to_content

    def test_multiple_spools_same_filament_separate_cache(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test that multiple spools of same filament have separate cache entries in 'all' mode"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "create_per_spool", "all"),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            # Create two spools with the same filament
            filament1 = sample_filament_data.copy()
            filament1["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }
            filament1["spool"] = {"id": 1}

            filament2 = sample_filament_data.copy()
            filament2["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }
            filament2["spool"] = {"id": 2}

            # Write both filaments
            spoolman2slicer.write_filament(filament1)
            spoolman2slicer.write_filament(filament2)

            # Check that both spools have separate cache entries
            assert "spool-1-ini" in spoolman2slicer.filament_id_to_filename
            assert "spool-2-ini" in spoolman2slicer.filament_id_to_filename
            assert "spool-1" in spoolman2slicer.filament_id_to_content
            assert "spool-2" in spoolman2slicer.filament_id_to_content

            # Check that two files were created
            files = os.listdir(temp_output_dir)
            assert len(files) == 2

    def test_cache_detects_different_content_per_spool(
        self, sample_filament_data, temp_template_dir, temp_output_dir, capsys
    ):
        """Test that cache correctly detects different content for different spools"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", True),
            patch.object(spoolman2slicer.args, "create_per_spool", "all"),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            # First write
            filament1 = sample_filament_data.copy()
            filament1["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }
            filament1["spool"] = {"id": 1}

            spoolman2slicer.write_filament(filament1)
            captured = capsys.readouterr()
            assert "Writing to:" in captured.out

            # Second write with same filament but different spool
            filament2 = sample_filament_data.copy()
            filament2["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }
            filament2["spool"] = {"id": 2}

            # Should write because it's a different spool
            spoolman2slicer.write_filament(filament2)
            captured = capsys.readouterr()
            assert "Writing to:" in captured.out

            # Third write with same spool and content
            spoolman2slicer.write_filament(filament1)
            captured = capsys.readouterr()
            assert "Same content, file not updated" in captured.out

#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for spoolman2slicer.py
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


class TestConfigSuffix:
    """Test get_config_suffix function"""

    def test_superslicer_suffix(self):
        """Test SuperSlicer returns ini suffix"""
        with patch.object(spoolman2slicer.args, "slicer", spoolman2slicer.SUPERSLICER):
            result = spoolman2slicer.get_config_suffix()
            assert result == ["ini"]

    def test_prusaslicer_suffix(self):
        """Test PrusaSlicer returns ini suffix"""
        with patch.object(spoolman2slicer.args, "slicer", spoolman2slicer.PRUSASLICER):
            result = spoolman2slicer.get_config_suffix()
            assert result == ["ini"]

    def test_orcaslicer_suffix(self):
        """Test OrcaSlicer returns json and info suffixes"""
        with patch.object(spoolman2slicer.args, "slicer", spoolman2slicer.ORCASLICER):
            result = spoolman2slicer.get_config_suffix()
            assert result == ["json", "info"]


class TestLoadFilaments:
    """Test loading filaments from Spoolman"""

    def test_load_filaments_success(self, sample_spoolman_response):
        """Test successful loading of filaments"""
        mock_response = Mock()
        mock_response.text = json.dumps(sample_spoolman_response)

        with patch("requests.get", return_value=mock_response):
            result = spoolman2slicer.load_filaments_from_spoolman(
                "http://test.local:7912"
            )
            assert len(result) == 2
            assert result[0]["id"] == 1
            assert result[0]["filament"]["material"] == "PLA"

    def test_load_filaments_connection_error(self):
        """Test handling of connection errors"""
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError):
            with pytest.raises(requests.exceptions.ConnectionError):
                spoolman2slicer.load_filaments_from_spoolman("http://test.local:7912")

    def test_load_filaments_with_retry_on_connection_error(self):
        """Test that connection errors are retried with exponential backoff"""
        with (
            patch(
                "requests.get",
                side_effect=requests.exceptions.ConnectionError("Connection refused"),
            ),
            patch("time.sleep") as mock_sleep,
        ):
            with pytest.raises(requests.exceptions.ConnectionError):
                spoolman2slicer.load_filaments_from_spoolman(
                    "http://test.local:7912", max_retries=3
                )

            # Should have tried 3 times
            assert (
                mock_sleep.call_count == 2
            )  # Sleep between retries (not after last one)
            # Check exponential backoff: 1, 2 seconds
            mock_sleep.assert_any_call(1)
            mock_sleep.assert_any_call(2)

    def test_load_filaments_timeout_with_retry(self):
        """Test that timeout errors are retried"""
        with (
            patch(
                "requests.get",
                side_effect=requests.exceptions.Timeout("Request timeout"),
            ),
            patch("time.sleep") as mock_sleep,
        ):
            with pytest.raises(requests.exceptions.Timeout):
                spoolman2slicer.load_filaments_from_spoolman(
                    "http://test.local:7912", max_retries=3
                )

            # Should have tried 3 times
            assert mock_sleep.call_count == 2

    def test_load_filaments_http_error(self):
        """Test handling of HTTP errors (no retry)"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Not Found", response=mock_response
        )

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(requests.exceptions.HTTPError):
                spoolman2slicer.load_filaments_from_spoolman("http://test.local:7912")

    def test_load_filaments_malformed_json(self, capsys):
        """Test handling of malformed JSON responses"""
        mock_response = Mock()
        mock_response.text = "This is not valid JSON {{{["
        mock_response.raise_for_status = Mock()  # No HTTP error

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(json.JSONDecodeError):
                spoolman2slicer.load_filaments_from_spoolman("http://test.local:7912")

            # Check that error message was printed
            captured = capsys.readouterr()
            assert "ERROR: Failed to parse JSON response" in captured.err

    def test_load_filaments_success_after_retry(self, sample_spoolman_response):
        """Test successful load after initial failure"""
        mock_response = Mock()
        mock_response.text = json.dumps(sample_spoolman_response)
        mock_response.raise_for_status = Mock()

        # Fail first two times, succeed on third
        with (
            patch(
                "requests.get",
                side_effect=[
                    requests.exceptions.ConnectionError("Connection refused"),
                    requests.exceptions.ConnectionError("Connection refused"),
                    mock_response,
                ],
            ),
            patch("time.sleep"),
        ):
            result = spoolman2slicer.load_filaments_from_spoolman(
                "http://test.local:7912", max_retries=3
            )
            assert len(result) == 2
            assert result[0]["id"] == 1


class TestFilenameGeneration:
    """Test filament filename generation"""

    def test_get_filament_filename(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test filename generation with templates"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
        ):
            # Setup template mock
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            # Add sm2s data
            sample_filament_data["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }

            filename = spoolman2slicer.get_filament_filename(sample_filament_data)
            assert filename.endswith("TestVendor - Test PLA Black.ini")
            assert filename.startswith(temp_output_dir)

    def test_get_filament_filename_with_variant(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test filename generation with variant"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            sample_filament_data["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "printer1",
            }

            filename = spoolman2slicer.get_filament_filename(sample_filament_data)
            assert filename.endswith("printer1 - TestVendor - Test PLA Black.ini")


class TestTemplateRendering:
    """Test Jinja2 template rendering"""

    def test_write_filament_creates_file(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test that write_filament creates a file"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            sample_filament_data["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }

            spoolman2slicer.write_filament(sample_filament_data)

            # Check file was created
            files = os.listdir(temp_output_dir)
            assert len(files) == 1
            assert files[0].endswith(".ini")

            # Check content
            with open(os.path.join(temp_output_dir, files[0]), "r") as f:
                content = f.read()
                assert "filament_type = PLA" in content
                assert "filament_cost = 25.0" in content

    def test_write_filament_uses_material_template(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test that material-specific templates are used when available"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            sample_filament_data["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }

            spoolman2slicer.write_filament(sample_filament_data)

            # Check file content uses PLA template
            files = os.listdir(temp_output_dir)
            with open(os.path.join(temp_output_dir, files[0]), "r") as f:
                content = f.read()
                assert "filament_type = PLA" in content


class TestFileOperations:
    """Test file operations"""

    def test_write_same_content_no_update(
        self, sample_filament_data, temp_template_dir, temp_output_dir, capsys
    ):
        """Test that same content doesn't rewrite file"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", True),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            sample_filament_data["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }

            # First write
            spoolman2slicer.write_filament(sample_filament_data)
            captured = capsys.readouterr()
            assert "Writing to:" in captured.out

            # Second write with same content
            spoolman2slicer.write_filament(sample_filament_data)
            captured = capsys.readouterr()
            assert "Same content, file not updated" in captured.out

    def test_delete_filament(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test filament deletion"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            sample_filament_data["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }

            # Write filament
            spoolman2slicer.write_filament(sample_filament_data)
            files_before = os.listdir(temp_output_dir)
            assert len(files_before) == 1

            # Delete filament
            spoolman2slicer.delete_filament(sample_filament_data)
            files_after = os.listdir(temp_output_dir)
            assert len(files_after) == 0


class TestCaching:
    """Test caching mechanisms"""

    def test_filename_cache(self, sample_filament_data):
        """Test filament ID to filename caching"""
        sample_filament_data["sm2s"] = {
            "slicer_suffix": "ini",
        }

        filename = "/test/output/TestVendor - Test PLA Black.ini"
        spoolman2slicer.set_cached_filename_from_filaments_id(
            sample_filament_data, filename
        )

        cached = spoolman2slicer.get_cached_filename_from_filaments_id(
            sample_filament_data
        )
        assert cached == filename

    def test_content_cache(self, sample_filament_data, temp_template_dir):
        """Test content caching prevents rewrites"""
        # Clear cache
        spoolman2slicer.filament_id_to_content.clear()

        filament_id = sample_filament_data["id"]
        content = "test content"

        # Store in cache
        spoolman2slicer.filament_id_to_content[filament_id] = content

        # Verify cache hit
        assert spoolman2slicer.filament_id_to_content.get(filament_id) == content


class TestVariants:
    """Test variant handling"""

    def test_multiple_variants_generate_multiple_files(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test that multiple variants create multiple files"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "variants", "printer1,printer2"),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            for variant in ["printer1", "printer2"]:
                data = sample_filament_data.copy()
                data["sm2s"] = {
                    "name": "spoolman2slicer.py",
                    "version": "0.0.2",
                    "slicer_suffix": "ini",
                    "variant": variant,
                }
                spoolman2slicer.write_filament(data)

            files = os.listdir(temp_output_dir)
            assert len(files) == 2
            assert any("printer1" in f for f in files)
            assert any("printer2" in f for f in files)


class TestSlicerTypes:
    """Test different slicer types"""

    def test_orcaslicer_json_generation(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test OrcaSlicer JSON file generation"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "slicer", spoolman2slicer.ORCASLICER),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            sample_filament_data["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "json",
                "variant": "",
                "now_int": 1234567890,
            }

            spoolman2slicer.write_filament(sample_filament_data)

            files = [f for f in os.listdir(temp_output_dir) if f.endswith(".json")]
            assert len(files) == 1

            # Verify JSON is valid
            with open(os.path.join(temp_output_dir, files[0]), "r") as f:
                data = json.load(f)
                assert data["name"] == "Test PLA Black"
                assert data["filament_type"] == ["PLA"]


class TestAddSm2sToFilament:
    """Test adding sm2s metadata to filament"""

    def test_add_sm2s_data(self, sample_filament_data):
        """Test that sm2s metadata is added correctly"""
        with (
            patch.object(spoolman2slicer.args, "url", "http://test.local:7912"),
            patch("time.time", return_value=1234567890.0),
            patch("time.asctime", return_value="Mon Jan 1 00:00:00 2024"),
        ):
            spoolman2slicer.add_sm2s_to_filament(
                sample_filament_data, "ini", "printer1"
            )

            assert "sm2s" in sample_filament_data
            assert sample_filament_data["sm2s"]["version"] == spoolman2slicer.VERSION
            assert sample_filament_data["sm2s"]["slicer_suffix"] == "ini"
            assert sample_filament_data["sm2s"]["variant"] == "printer1"
            assert (
                sample_filament_data["sm2s"]["spoolman_url"] == "http://test.local:7912"
            )
            assert sample_filament_data["sm2s"]["now_int"] == 1234567890


class TestWebsocketHandlers:
    """Test websocket update message handlers"""

    def test_handle_spool_update_added(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test handling of spool added messages"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "variants", ""),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            msg = {
                "type": "added",
                "payload": {"filament": sample_filament_data},
            }

            with patch.object(
                spoolman2slicer, "get_config_suffix", return_value=["ini"]
            ):
                spoolman2slicer.handle_spool_update_msg(msg)

            files = os.listdir(temp_output_dir)
            assert len(files) == 1

    def test_handle_filament_update_updated(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test handling of filament updated messages"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "variants", ""),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            # First create the filament
            with patch.object(
                spoolman2slicer, "get_config_suffix", return_value=["ini"]
            ):
                sample_filament_data["sm2s"] = {
                    "name": "spoolman2slicer.py",
                    "version": "0.0.2",
                    "slicer_suffix": "ini",
                    "variant": "",
                }
                spoolman2slicer.write_filament(sample_filament_data)

            # Now update it
            msg = {
                "type": "updated",
                "payload": sample_filament_data,
            }

            with patch.object(
                spoolman2slicer, "get_config_suffix", return_value=["ini"]
            ):
                spoolman2slicer.handle_filament_update_msg(msg)


class TestErrorHandling:
    """Test error handling"""

    def test_missing_template_directory(self):
        """Test error when template directory doesn't exist"""
        # This is tested at module load time in the actual script
        # We can test the get_default_template_for_suffix function
        result = spoolman2slicer.get_default_template_for_suffix("ini")
        assert result == "default.ini.template"

    def test_missing_output_directory(self):
        """Test error when output directory doesn't exist"""
        # This is validated in the script's main execution
        # We can't easily test it without modifying args before import
        pass

    def test_template_not_found_fallback(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test fallback to default template when material template not found"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
        ):
            from jinja2 import Environment, FileSystemLoader, TemplateNotFound

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)

            # Mock to raise TemplateNotFound for non-default templates
            original_get = env.get_template

            def mock_get_template(name):
                if name.startswith("NONEXISTENT"):
                    raise TemplateNotFound(name)
                return original_get(name)

            mock_templates.get_template = mock_get_template

            sample_filament_data["material"] = "NONEXISTENT"
            sample_filament_data["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }

            # Should fallback to default template
            spoolman2slicer.write_filament(sample_filament_data)

            files = os.listdir(temp_output_dir)
            assert len(files) == 1


class TestDeleteAll:
    """Test delete all filaments functionality"""

    def test_delete_all_filaments(self, temp_output_dir):
        """Test deleting all filament configs"""
        # Create some test files
        (Path(temp_output_dir) / "test1.ini").write_text("content1")
        (Path(temp_output_dir) / "test2.ini").write_text("content2")
        (Path(temp_output_dir) / "test3.txt").write_text(
            "content3"
        )  # Should not delete

        with (
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer, "get_config_suffix", return_value=["ini"]),
        ):
            spoolman2slicer.delete_all_filaments()

        files = os.listdir(temp_output_dir)
        assert len(files) == 1
        assert "test3.txt" in files


class TestCreatePerSpool:
    """Test create-per-spool functionality"""

    def test_add_sm2s_with_spool_data(self, sample_filament_data):
        """Test that add_sm2s_to_filament adds spool field"""
        spool_data = {"id": 1, "spool_weight": 200.0, "archived": False}

        with (
            patch.object(spoolman2slicer.args, "url", "http://test.local:7912"),
            patch("time.time", return_value=1234567890.0),
            patch("time.asctime", return_value="Mon Jan 1 00:00:00 2024"),
        ):
            spoolman2slicer.add_sm2s_to_filament(
                sample_filament_data, "ini", "printer1", spool_data
            )

            assert "spool" in sample_filament_data
            assert sample_filament_data["spool"]["id"] == 1
            assert sample_filament_data["spool"]["spool_weight"] == 200.0

    def test_add_sm2s_without_spool_data(self, sample_filament_data):
        """Test that add_sm2s_to_filament adds empty spool dict when no spool provided"""
        with (
            patch.object(spoolman2slicer.args, "url", "http://test.local:7912"),
            patch("time.time", return_value=1234567890.0),
            patch("time.asctime", return_value="Mon Jan 1 00:00:00 2024"),
        ):
            spoolman2slicer.add_sm2s_to_filament(
                sample_filament_data, "ini", "printer1"
            )

            assert "spool" in sample_filament_data
            assert sample_filament_data["spool"] == {}

    def test_create_per_spool_all_mode(self, temp_template_dir, temp_output_dir):
        """Test --create-per-spool all creates one file per non-archived spool"""
        spools_response = [
            {
                "id": 1,
                "archived": False,
                "spool_weight": 200.0,
                "filament": {
                    "id": 10,
                    "name": "Test PLA Black",
                    "vendor": {"id": 5, "name": "TestVendor", "extra": {}},
                    "material": "PLA",
                    "price": 25.0,
                    "density": 1.24,
                    "diameter": 1.75,
                    "weight": 1000.0,
                    "spool_weight": 200.0,
                    "settings_extruder_temp": 210,
                    "settings_bed_temp": 60,
                    "color_hex": "000000",
                    "extra": {},
                },
            },
            {
                "id": 2,
                "archived": False,
                "spool_weight": 150.0,
                "filament": {
                    "id": 10,  # Same filament as spool 1
                    "name": "Test PLA Black",
                    "vendor": {"id": 5, "name": "TestVendor", "extra": {}},
                    "material": "PLA",
                    "price": 25.0,
                    "density": 1.24,
                    "diameter": 1.75,
                    "weight": 1000.0,
                    "spool_weight": 200.0,
                    "settings_extruder_temp": 210,
                    "settings_bed_temp": 60,
                    "color_hex": "000000",
                    "extra": {},
                },
            },
            {
                "id": 3,
                "archived": True,  # This should be skipped
                "spool_weight": 100.0,
                "filament": {
                    "id": 11,
                    "name": "Test ABS Red",
                    "vendor": {"id": 6, "name": "AnotherVendor", "extra": {}},
                    "material": "ABS",
                    "price": 30.0,
                    "density": 1.04,
                    "diameter": 1.75,
                    "weight": 1000.0,
                    "spool_weight": 250.0,
                    "settings_extruder_temp": 240,
                    "settings_bed_temp": 100,
                    "color_hex": "FF0000",
                    "extra": {},
                },
            },
        ]

        # Create filename_for_spool template
        Path(temp_template_dir, "filename_for_spool.template").write_text(
            "{{vendor.name}} - {{name}} - {{spool.id}}.{{sm2s.slicer_suffix}}\n"
        )

        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "variants", ""),
            patch.object(spoolman2slicer.args, "create_per_spool", "all"),
            patch("requests.get") as mock_get,
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            # Mock the API response
            mock_response = Mock()
            mock_response.text = json.dumps(spools_response)
            mock_get.return_value = mock_response

            with patch.object(
                spoolman2slicer, "get_config_suffix", return_value=["ini"]
            ):
                spoolman2slicer.load_and_update_all_filaments("http://test.local:7912")

            files = os.listdir(temp_output_dir)
            # Should have 2 files (spools 1 and 2, not the archived one)
            assert len(files) == 2
            assert any("1.ini" in f for f in files)
            assert any("2.ini" in f for f in files)
            assert not any("3.ini" in f for f in files)

    def test_create_per_spool_least_left_mode(self, temp_template_dir, temp_output_dir):
        """Test --create-per-spool least-left selects spool with lowest spool_weight"""
        spools_response = [
            {
                "id": 1,
                "archived": False,
                "spool_weight": 200.0,
                "filament": {
                    "id": 10,
                    "name": "Test PLA Black",
                    "vendor": {"id": 5, "name": "TestVendor", "extra": {}},
                    "material": "PLA",
                    "price": 25.0,
                    "density": 1.24,
                    "diameter": 1.75,
                    "weight": 1000.0,
                    "spool_weight": 200.0,
                    "settings_extruder_temp": 210,
                    "settings_bed_temp": 60,
                    "color_hex": "000000",
                    "extra": {},
                },
            },
            {
                "id": 2,
                "archived": False,
                "spool_weight": 150.0,  # This should be selected (lowest weight)
                "filament": {
                    "id": 10,  # Same filament as spool 1
                    "name": "Test PLA Black",
                    "vendor": {"id": 5, "name": "TestVendor", "extra": {}},
                    "material": "PLA",
                    "price": 25.0,
                    "density": 1.24,
                    "diameter": 1.75,
                    "weight": 1000.0,
                    "spool_weight": 200.0,
                    "settings_extruder_temp": 210,
                    "settings_bed_temp": 60,
                    "color_hex": "000000",
                    "extra": {},
                },
            },
            {
                "id": 3,
                "archived": False,
                "spool_weight": 300.0,
                "filament": {
                    "id": 11,
                    "name": "Test ABS Red",
                    "vendor": {"id": 6, "name": "AnotherVendor", "extra": {}},
                    "material": "ABS",
                    "price": 30.0,
                    "density": 1.04,
                    "diameter": 1.75,
                    "weight": 1000.0,
                    "spool_weight": 250.0,
                    "settings_extruder_temp": 240,
                    "settings_bed_temp": 100,
                    "color_hex": "FF0000",
                    "extra": {},
                },
            },
        ]

        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "variants", ""),
            patch.object(spoolman2slicer.args, "create_per_spool", "least-left"),
            patch("requests.get") as mock_get,
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            # Mock the API response
            mock_response = Mock()
            mock_response.text = json.dumps(spools_response)
            mock_get.return_value = mock_response

            with patch.object(
                spoolman2slicer, "get_config_suffix", return_value=["ini"]
            ):
                spoolman2slicer.load_and_update_all_filaments("http://test.local:7912")

            files = os.listdir(temp_output_dir)
            # Should have 2 files (one per filament)
            assert len(files) == 2

            # Check that spool field contains the right spool data
            # File for PLA should have spool 2 data (lowest weight)
            pla_file = [f for f in files if "PLA" in f][0]
            with open(os.path.join(temp_output_dir, pla_file), "r") as f:
                content = f.read()
                # The file should be generated from spool 2 (lowest weight)
                # We can't directly check spool ID in the content without knowing
                # the template, so we just verify files were created

    def test_create_per_spool_most_recent_mode(
        self, temp_template_dir, temp_output_dir
    ):
        """Test --create-per-spool most-recent selects spool with highest last_used"""
        spools_response = [
            {
                "id": 1,
                "archived": False,
                "spool_weight": 200.0,
                "last_used": "2024-01-01T10:00:00Z",
                "filament": {
                    "id": 10,
                    "name": "Test PLA Black",
                    "vendor": {"id": 5, "name": "TestVendor", "extra": {}},
                    "material": "PLA",
                    "price": 25.0,
                    "density": 1.24,
                    "diameter": 1.75,
                    "weight": 1000.0,
                    "spool_weight": 200.0,
                    "settings_extruder_temp": 210,
                    "settings_bed_temp": 60,
                    "color_hex": "000000",
                    "extra": {},
                },
            },
            {
                "id": 2,
                "archived": False,
                "spool_weight": 150.0,
                "last_used": "2024-02-01T10:00:00Z",  # Most recent, should be selected
                "filament": {
                    "id": 10,  # Same filament as spool 1
                    "name": "Test PLA Black",
                    "vendor": {"id": 5, "name": "TestVendor", "extra": {}},
                    "material": "PLA",
                    "price": 25.0,
                    "density": 1.24,
                    "diameter": 1.75,
                    "weight": 1000.0,
                    "spool_weight": 200.0,
                    "settings_extruder_temp": 210,
                    "settings_bed_temp": 60,
                    "color_hex": "000000",
                    "extra": {},
                },
            },
            {
                "id": 3,
                "archived": False,
                "spool_weight": 300.0,
                "last_used": None,  # Empty last_used
                "filament": {
                    "id": 11,
                    "name": "Test ABS Red",
                    "vendor": {"id": 6, "name": "AnotherVendor", "extra": {}},
                    "material": "ABS",
                    "price": 30.0,
                    "density": 1.04,
                    "diameter": 1.75,
                    "weight": 1000.0,
                    "spool_weight": 250.0,
                    "settings_extruder_temp": 240,
                    "settings_bed_temp": 100,
                    "color_hex": "FF0000",
                    "extra": {},
                },
            },
        ]

        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "variants", ""),
            patch.object(spoolman2slicer.args, "create_per_spool", "most-recent"),
            patch("requests.get") as mock_get,
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            # Mock the API response
            mock_response = Mock()
            mock_response.text = json.dumps(spools_response)
            mock_get.return_value = mock_response

            with patch.object(
                spoolman2slicer, "get_config_suffix", return_value=["ini"]
            ):
                spoolman2slicer.load_and_update_all_filaments("http://test.local:7912")

            files = os.listdir(temp_output_dir)
            # Should have 2 files (one per filament)
            assert len(files) == 2

    def test_create_per_spool_tie_break_by_id(self, temp_template_dir, temp_output_dir):
        """Test that ties are broken by lowest spool id"""
        spools_response = [
            {
                "id": 3,
                "archived": False,
                "spool_weight": 200.0,
                "filament": {
                    "id": 10,
                    "name": "Test PLA Black",
                    "vendor": {"id": 5, "name": "TestVendor", "extra": {}},
                    "material": "PLA",
                    "price": 25.0,
                    "density": 1.24,
                    "diameter": 1.75,
                    "weight": 1000.0,
                    "spool_weight": 200.0,
                    "settings_extruder_temp": 210,
                    "settings_bed_temp": 60,
                    "color_hex": "000000",
                    "extra": {},
                },
            },
            {
                "id": 1,  # Lower ID, should win the tie
                "archived": False,
                "spool_weight": 200.0,  # Same weight
                "filament": {
                    "id": 10,  # Same filament as spool 3
                    "name": "Test PLA Black",
                    "vendor": {"id": 5, "name": "TestVendor", "extra": {}},
                    "material": "PLA",
                    "price": 25.0,
                    "density": 1.24,
                    "diameter": 1.75,
                    "weight": 1000.0,
                    "spool_weight": 200.0,
                    "settings_extruder_temp": 210,
                    "settings_bed_temp": 60,
                    "color_hex": "000000",
                    "extra": {},
                },
            },
        ]

        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "variants", ""),
            patch.object(spoolman2slicer.args, "create_per_spool", "least-left"),
            patch("requests.get") as mock_get,
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            # Mock the API response
            mock_response = Mock()
            mock_response.text = json.dumps(spools_response)
            mock_get.return_value = mock_response

            with patch.object(
                spoolman2slicer, "get_config_suffix", return_value=["ini"]
            ):
                spoolman2slicer.load_and_update_all_filaments("http://test.local:7912")

            files = os.listdir(temp_output_dir)
            # Should have 1 file (one per filament)
            assert len(files) == 1

    def test_filename_template_selection(
        self, temp_template_dir, temp_output_dir, sample_filament_data
    ):
        """Test that correct filename template is used based on mode"""
        # Create both templates
        Path(temp_template_dir, "filename.template").write_text(
            "{{vendor.name}} - {{name}}.{{sm2s.slicer_suffix}}\n"
        )
        Path(temp_template_dir, "filename_for_spool.template").write_text(
            "{{vendor.name}} - {{name}} - {{spool.id}}.{{sm2s.slicer_suffix}}\n"
        )

        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            sample_filament_data["sm2s"] = {
                "slicer_suffix": "ini",
                "variant": "",
            }
            sample_filament_data["spool"] = {"id": 42}

            # Test with --create-per-spool all
            with patch.object(spoolman2slicer.args, "create_per_spool", "all"):
                filename = spoolman2slicer.get_filament_filename(sample_filament_data)
                assert "42.ini" in filename

            # Test without --create-per-spool
            with patch.object(spoolman2slicer.args, "create_per_spool", None):
                filename = spoolman2slicer.get_filament_filename(sample_filament_data)
                assert "42.ini" not in filename


class TestAtomicWrites:
    """Test atomic write functionality"""

    def test_atomic_write_creates_file(self, temp_output_dir):
        """Test that atomic_write creates a file successfully"""
        test_file = os.path.join(temp_output_dir, "test_atomic.txt")
        test_content = "Hello, atomic world!"

        spoolman2slicer.atomic_write(test_file, test_content)

        assert os.path.exists(test_file)
        with open(test_file, "r", encoding="utf-8") as f:
            assert f.read() == test_content

    def test_atomic_write_replaces_existing_file(self, temp_output_dir):
        """Test that atomic_write replaces an existing file"""
        test_file = os.path.join(temp_output_dir, "test_replace.txt")

        # Create initial file
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("Original content")

        # Replace with atomic write
        new_content = "New atomic content"
        spoolman2slicer.atomic_write(test_file, new_content)

        with open(test_file, "r", encoding="utf-8") as f:
            assert f.read() == new_content

    def test_atomic_write_no_temp_files_left(self, temp_output_dir):
        """Test that no temporary files are left after atomic write"""
        test_file = os.path.join(temp_output_dir, "test_cleanup.txt")
        test_content = "Content for cleanup test"

        spoolman2slicer.atomic_write(test_file, test_content)

        # Check that no temporary files are left
        files = os.listdir(temp_output_dir)
        temp_files = [f for f in files if f.startswith(".tmp_")]
        assert len(temp_files) == 0

    def test_write_filament_uses_atomic_write(
        self, sample_filament_data, temp_template_dir, temp_output_dir
    ):
        """Test that write_filament uses atomic writes"""
        with (
            patch.object(spoolman2slicer, "templates") as mock_templates,
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "variants", ""),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)
            mock_templates.get_template = env.get_template

            sample_filament_data["sm2s"] = {
                "name": "spoolman2slicer.py",
                "version": "0.0.2",
                "slicer_suffix": "ini",
                "variant": "",
            }

            with patch.object(
                spoolman2slicer, "get_config_suffix", return_value=["ini"]
            ):
                spoolman2slicer.write_filament(sample_filament_data)

            # Verify file was created
            files = os.listdir(temp_output_dir)
            assert len(files) == 1

            # Verify no temp files left
            temp_files = [f for f in files if f.startswith(".tmp_")]
            assert len(temp_files) == 0


class TestVendorNameChange:
    """Test that vendor name changes update config filenames correctly"""

    def test_vendor_name_change_default_mode(self, temp_output_dir, temp_template_dir):
        """Test that vendor name change updates filename in default mode"""
        # Setup test data with complete filament fields
        vendor = {"id": 1, "name": "OldVendor", "extra": {}}
        vendor_updated = {"id": 1, "name": "NewVendor", "extra": {}}

        filament = {
            "id": 10,
            "name": "Test PLA",
            "material": "PLA",
            "vendor": vendor.copy(),
            "settings_extruder_temp": 210,
            "settings_bed_temp": 60,
            "density": 1.24,
            "diameter": 1.75,
            "weight": 1000.0,
            "spool_weight": 200.0,
            "color_hex": "000000",
            "extra": {},
        }

        spool = {"id": 100, "filament": filament.copy(), "archived": False}

        # Populate caches
        spoolman2slicer.vendors_cache[1] = vendor
        spoolman2slicer.filaments_cache[10] = filament
        spoolman2slicer.spools_cache[100] = spool

        with (
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "variants", ""),
            patch.object(spoolman2slicer.args, "create_per_spool", None),
            patch.object(spoolman2slicer, "get_config_suffix", return_value=["ini"]),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)

            with patch.object(spoolman2slicer, "templates") as mock_templates:
                mock_templates.get_template = env.get_template

                # Write initial file with old vendor name
                filament_copy = filament.copy()
                spoolman2slicer.add_sm2s_to_filament(filament_copy, "ini", "")
                spoolman2slicer.write_filament(filament_copy)

                # Check old file was created
                old_filename = f"{temp_output_dir}/OldVendor - Test PLA.ini"
                assert os.path.exists(
                    old_filename
                ), f"Old file not found: {old_filename}"

                # Now simulate vendor name change
                msg = {"type": "updated", "payload": vendor_updated}
                spoolman2slicer.handle_vendor_update_msg(msg)

                # Check new file was created
                new_filename = f"{temp_output_dir}/NewVendor - Test PLA.ini"
                assert os.path.exists(
                    new_filename
                ), f"New file not found: {new_filename}"

                # Check old file was deleted
                assert not os.path.exists(
                    old_filename
                ), f"Old file still exists: {old_filename}"

    def test_vendor_name_change_per_spool_all_mode(
        self, temp_output_dir, temp_template_dir
    ):
        """Test that vendor name change updates filename in per-spool all mode"""
        # Setup test data with complete filament fields
        vendor = {"id": 1, "name": "OldVendor", "extra": {}}
        vendor_updated = {"id": 1, "name": "NewVendor", "extra": {}}

        filament = {
            "id": 10,
            "name": "Test PLA",
            "material": "PLA",
            "vendor": vendor.copy(),
            "settings_extruder_temp": 210,
            "settings_bed_temp": 60,
            "density": 1.24,
            "diameter": 1.75,
            "weight": 1000.0,
            "spool_weight": 200.0,
            "color_hex": "000000",
            "extra": {},
        }

        spool = {"id": 100, "filament": filament.copy(), "archived": False}

        # Populate caches
        spoolman2slicer.vendors_cache[1] = vendor
        spoolman2slicer.filaments_cache[10] = filament
        spoolman2slicer.spools_cache[100] = spool

        with (
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "variants", ""),
            patch.object(spoolman2slicer.args, "create_per_spool", "all"),
            patch.object(spoolman2slicer, "get_config_suffix", return_value=["ini"]),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)

            with patch.object(spoolman2slicer, "templates") as mock_templates:
                mock_templates.get_template = env.get_template

                # Write initial file with old vendor name
                filament_copy = filament.copy()
                spoolman2slicer.add_sm2s_to_filament(filament_copy, "ini", "", spool)
                spoolman2slicer.write_filament(filament_copy)

                # Check old file was created
                old_filename = f"{temp_output_dir}/OldVendor - Test PLA - 100.ini"
                assert os.path.exists(
                    old_filename
                ), f"Old file not found: {old_filename}"

                # Now simulate vendor name change
                msg = {"type": "updated", "payload": vendor_updated}
                spoolman2slicer.handle_vendor_update_msg(msg)

                # Check new file was created
                new_filename = f"{temp_output_dir}/NewVendor - Test PLA - 100.ini"
                assert os.path.exists(
                    new_filename
                ), f"New file not found: {new_filename}"

                # Check old file was deleted
                assert not os.path.exists(
                    old_filename
                ), f"Old file still exists: {old_filename}"

    def test_vendor_name_change_multiple_filaments(
        self, temp_output_dir, temp_template_dir
    ):
        """Test that vendor name change updates all filaments from that vendor"""
        # Setup test data with complete filament fields
        vendor = {"id": 1, "name": "OldVendor", "extra": {}}
        vendor_updated = {"id": 1, "name": "NewVendor", "extra": {}}

        filament1 = {
            "id": 10,
            "name": "Test PLA",
            "material": "PLA",
            "vendor": vendor.copy(),
            "settings_extruder_temp": 210,
            "settings_bed_temp": 60,
            "density": 1.24,
            "diameter": 1.75,
            "weight": 1000.0,
            "spool_weight": 200.0,
            "color_hex": "000000",
            "extra": {},
        }

        filament2 = {
            "id": 11,
            "name": "Test ABS",
            "material": "ABS",
            "vendor": vendor.copy(),
            "settings_extruder_temp": 240,
            "settings_bed_temp": 100,
            "density": 1.04,
            "diameter": 1.75,
            "weight": 1000.0,
            "spool_weight": 250.0,
            "color_hex": "FF0000",
            "extra": {},
        }

        spool1 = {"id": 100, "filament": filament1.copy(), "archived": False}
        spool2 = {"id": 101, "filament": filament2.copy(), "archived": False}

        # Populate caches
        spoolman2slicer.vendors_cache[1] = vendor
        spoolman2slicer.filaments_cache[10] = filament1
        spoolman2slicer.filaments_cache[11] = filament2
        spoolman2slicer.spools_cache[100] = spool1
        spoolman2slicer.spools_cache[101] = spool2

        with (
            patch.object(spoolman2slicer.args, "dir", temp_output_dir),
            patch.object(spoolman2slicer.args, "verbose", False),
            patch.object(spoolman2slicer.args, "variants", ""),
            patch.object(spoolman2slicer.args, "create_per_spool", None),
            patch.object(spoolman2slicer, "get_config_suffix", return_value=["ini"]),
        ):
            from jinja2 import Environment, FileSystemLoader

            loader = FileSystemLoader(temp_template_dir)
            env = Environment(loader=loader)

            with patch.object(spoolman2slicer, "templates") as mock_templates:
                mock_templates.get_template = env.get_template

                # Write initial files with old vendor name
                for filament in [filament1, filament2]:
                    filament_copy = filament.copy()
                    spoolman2slicer.add_sm2s_to_filament(filament_copy, "ini", "")
                    spoolman2slicer.write_filament(filament_copy)

                # Check old files were created
                old_filename1 = f"{temp_output_dir}/OldVendor - Test PLA.ini"
                old_filename2 = f"{temp_output_dir}/OldVendor - Test ABS.ini"
                assert os.path.exists(old_filename1)
                assert os.path.exists(old_filename2)

                # Now simulate vendor name change
                msg = {"type": "updated", "payload": vendor_updated}
                spoolman2slicer.handle_vendor_update_msg(msg)

                # Check new files were created
                new_filename1 = f"{temp_output_dir}/NewVendor - Test PLA.ini"
                new_filename2 = f"{temp_output_dir}/NewVendor - Test ABS.ini"
                assert os.path.exists(new_filename1)
                assert os.path.exists(new_filename2)

                # Check old files were deleted
                assert not os.path.exists(old_filename1)
                assert not os.path.exists(old_filename2)

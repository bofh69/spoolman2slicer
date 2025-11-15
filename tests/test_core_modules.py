#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for the new core modules to ensure they work correctly.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from spoolman_core import SpoolmanConfig, SpoolmanProcessor
from template_core import TemplateConfig, TemplateProcessor


class TestSpoolmanCore:
    """Tests for spoolman_core module"""

    def test_config_creation(self):
        """Test that SpoolmanConfig can be created with required fields"""
        config = SpoolmanConfig(
            output_dir="/tmp/test",
            slicer="superslicer",
            spoolman_url="http://localhost:7912",
            template_path="/tmp/templates",
        )
        assert config.output_dir == "/tmp/test"
        assert config.slicer == "superslicer"
        assert config.verbose is False
        assert config.updates is False

    def test_config_validation(self):
        """Test that invalid slicer raises error"""
        with pytest.raises(ValueError, match="Unsupported slicer"):
            SpoolmanConfig(
                output_dir="/tmp/test",
                slicer="invalid_slicer",
                spoolman_url="http://localhost:7912",
                template_path="/tmp/templates",
            )

    def test_processor_creation(self):
        """Test that processor can be created"""
        config = SpoolmanConfig(
            output_dir="/tmp/test",
            slicer="superslicer",
            spoolman_url="http://localhost:7912",
            template_path="/tmp/templates",
        )
        processor = SpoolmanProcessor(config)
        assert processor.config == config
        assert processor.templates is not None

    def test_custom_logger(self):
        """Test that custom logger is used"""
        logged_messages = []

        def custom_logger(message: str, level: str = "INFO"):
            logged_messages.append((level, message))

        config = SpoolmanConfig(
            output_dir="/tmp/test",
            slicer="superslicer",
            spoolman_url="http://localhost:7912",
            template_path="/tmp/templates",
        )
        processor = SpoolmanProcessor(config, logger=custom_logger)
        processor._log_info("Test message")
        
        assert len(logged_messages) == 1
        assert logged_messages[0][0] == "INFO"
        assert "Test message" in logged_messages[0][1]

    def test_get_config_suffix_superslicer(self):
        """Test config suffix for SuperSlicer"""
        config = SpoolmanConfig(
            output_dir="/tmp/test",
            slicer="superslicer",
            spoolman_url="http://localhost:7912",
            template_path="/tmp/templates",
        )
        processor = SpoolmanProcessor(config)
        assert processor.get_config_suffix() == ["ini"]

    def test_get_config_suffix_orcaslicer(self):
        """Test config suffix for OrcaSlicer"""
        config = SpoolmanConfig(
            output_dir="/tmp/test",
            slicer="orcaslicer",
            spoolman_url="http://localhost:7912",
            template_path="/tmp/templates",
        )
        processor = SpoolmanProcessor(config)
        assert processor.get_config_suffix() == ["json", "info"]

    def test_load_filaments_success(self):
        """Test successful loading of filaments"""
        config = SpoolmanConfig(
            output_dir="/tmp/test",
            slicer="superslicer",
            spoolman_url="http://localhost:7912",
            template_path="/tmp/templates",
        )
        processor = SpoolmanProcessor(config)

        mock_response = Mock()
        mock_response.text = json.dumps([{"id": 1, "name": "Test"}])
        mock_response.raise_for_status = Mock()

        with patch("requests.get", return_value=mock_response):
            result = processor.load_filaments_from_spoolman("http://test:7912")
            assert len(result) == 1
            assert result[0]["id"] == 1


class TestTemplateCore:
    """Tests for template_core module"""

    def test_template_config_creation(self):
        """Test that TemplateConfig can be created"""
        config = TemplateConfig(
            slicer="superslicer",
            filament_path="/tmp/filaments",
            template_path="/tmp/templates",
        )
        assert config.slicer == "superslicer"
        assert config.verbose is False

    def test_template_config_validation(self):
        """Test that invalid slicer raises error"""
        with pytest.raises(ValueError, match="Unsupported slicer"):
            TemplateConfig(
                slicer="invalid",
                filament_path="/tmp/filaments",
                template_path="/tmp/templates",
            )

    def test_template_processor_creation(self):
        """Test that template processor can be created"""
        config = TemplateConfig(
            slicer="superslicer",
            filament_path="/tmp/filaments",
            template_path="/tmp/templates",
        )
        processor = TemplateProcessor(config)
        assert processor.config == config

    def test_get_material_superslicer(self):
        """Test material extraction for SuperSlicer"""
        config = TemplateConfig(
            slicer="superslicer",
            filament_path="/tmp/filaments",
            template_path="/tmp/templates",
        )
        processor = TemplateProcessor(config)
        test_config = {"filament_type": "PLA"}
        assert processor.get_material(test_config, "superslicer") == "PLA"

    def test_get_material_orcaslicer(self):
        """Test material extraction for OrcaSlicer"""
        config = TemplateConfig(
            slicer="orcaslicer",
            filament_path="/tmp/filaments",
            template_path="/tmp/templates",
        )
        processor = TemplateProcessor(config)
        test_config = {"filament_type": ["PLA"]}
        assert processor.get_material(test_config, "orcaslicer") == "PLA"

    def test_read_ini_file(self):
        """Test reading INI files"""
        config = TemplateConfig(
            slicer="superslicer",
            filament_path="/tmp/filaments",
            template_path="/tmp/templates",
        )
        processor = TemplateProcessor(config)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write("# Comment line\n")
            f.write("key1 = value1\n")
            f.write("key2 = value2\n")
            temp_file = f.name

        try:
            result = processor.read_ini_file(temp_file)
            assert result["key1"] == "value1"
            assert result["key2"] == "value2"
            assert "#" not in result
        finally:
            os.unlink(temp_file)


class TestIntegration:
    """Integration tests to ensure the core modules work together"""

    def test_processor_with_templates(self, tmp_path):
        """Test that processor can work with template directory"""
        # Create template directory
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        
        # Create minimal templates
        (template_dir / "filename.template").write_text("{{vendor.name}} - {{name}}.ini\n")
        (template_dir / "default.ini.template").write_text("filament_type = {{material}}\n")
        
        # Create output directory
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create config
        config = SpoolmanConfig(
            output_dir=str(output_dir),
            slicer="superslicer",
            spoolman_url="http://localhost:7912",
            template_path=str(template_dir),
        )

        # Create processor - should not raise error
        processor = SpoolmanProcessor(config)
        assert processor.templates is not None
        assert processor.get_config_suffix() == ["ini"]

    def test_template_processor_creates_directory(self, tmp_path):
        """Test that template processor creates output directory"""
        template_dir = tmp_path / "templates"
        filament_dir = tmp_path / "filaments"
        filament_dir.mkdir()

        config = TemplateConfig(
            slicer="superslicer",
            filament_path=str(filament_dir),
            template_path=str(template_dir),
        )

        processor = TemplateProcessor(config)
        processor.create_template_path()

        assert template_dir.exists()
        assert template_dir.is_dir()

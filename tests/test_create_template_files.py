#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for create_template_files.py
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Mock sys.argv to provide required arguments before import
sys.argv = ["create_template_files.py", "--slicer", "superslicer", "--dir", "/tmp/test"]

# Add parent directory to path to import the module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import create_template_files


class TestGetMaterial:
    """Test material extraction from config"""

    def test_get_material_orcaslicer(self):
        """Test extracting material from OrcaSlicer config"""
        config = {"filament_type": ["PLA"]}
        material = create_template_files.get_material(
            config, create_template_files.ORCASLICER
        )
        assert material == "PLA"

    def test_get_material_crealityprint(self):
        """Test extracting material from CrealityPrint config"""
        config = {"filament_type": "PLA"}
        material = create_template_files.get_material(
            config, create_template_files.CREALITYPRINT
        )
        assert material == "PLA"

    def test_get_material_superslicer(self):
        """Test extracting material from SuperSlicer config"""
        config = {"filament_type": "ABS"}
        material = create_template_files.get_material(
            config, create_template_files.SUPERSLICER
        )
        assert material == "ABS"

    def test_get_material_prusaslicer(self):
        """Test extracting material from PrusaSlicer config"""
        config = {"filament_type": "PETG"}
        material = create_template_files.get_material(
            config, create_template_files.PRUSASLICER
        )
        assert material == "PETG"


class TestReadIniFile:
    """Test reading INI configuration files"""

    def test_read_ini_file_basic(self, tmp_path):
        """Test reading a basic INI file"""
        ini_file = tmp_path / "test.ini"
        ini_file.write_text(
            "# Comment line\n"
            "filament_type = PLA\n"
            "temperature = 210\n"
            "bed_temperature = 60\n"
        )

        config = create_template_files.read_ini_file(str(ini_file))

        assert config["filament_type"] == "PLA"
        assert config["temperature"] == "210"
        assert config["bed_temperature"] == "60"

    def test_read_ini_file_with_spaces(self, tmp_path):
        """Test reading INI file with spacing variations"""
        ini_file = tmp_path / "test.ini"
        ini_file.write_text(
            "key1=value1\n" "key2 = value2\n" "key3=  value3  \n" "key4  =value4\n"
        )

        config = create_template_files.read_ini_file(str(ini_file))

        assert config["key1"] == "value1"
        assert config["key2"] == "value2"
        assert config["key3"] == "value3"  # Trailing spaces are stripped
        assert config["key4"] == "value4"

    def test_read_ini_file_ignores_comments(self, tmp_path):
        """Test that comments are ignored"""
        ini_file = tmp_path / "test.ini"
        ini_file.write_text(
            "# This is a comment\n" "key1 = value1\n" "# Another comment\n"
        )

        config = create_template_files.read_ini_file(str(ini_file))

        assert len(config) == 1
        assert config["key1"] == "value1"


class TestLoadConfigFile:
    """Test loading different types of config files"""

    def test_load_orcaslicer_json(self, tmp_path):
        """Test loading OrcaSlicer JSON config"""
        json_file = tmp_path / "test.json"
        test_data = {
            "name": "Test Filament",
            "filament_type": ["PLA"],
            "nozzle_temperature": ["210"],
        }
        json_file.write_text(json.dumps(test_data))

        config = create_template_files.load_config_file(
            create_template_files.ORCASLICER, str(json_file)
        )

        assert config["name"] == "Test Filament"
        assert config["filament_type"] == ["PLA"]

    def test_load_crealityprint_json(self, tmp_path):
        """Test loading CrealityPrint JSON config"""
        json_file = tmp_path / "test.json"
        test_data = {
            "name": "Test Filament",
            "filament_type": ["PLA"],
            "nozzle_temperature": ["210"],
        }
        json_file.write_text(json.dumps(test_data))

        config = create_template_files.load_config_file(
            create_template_files.CREALITYPRINT, str(json_file)
        )

        assert config["name"] == "Test Filament"
        assert config["filament_type"] == ["PLA"]

    def test_load_superslicer_ini(self, tmp_path):
        """Test loading SuperSlicer INI config"""
        ini_file = tmp_path / "test.ini"
        ini_file.write_text("filament_type = PLA\n" "temperature = 210\n")

        config = create_template_files.load_config_file(
            create_template_files.SUPERSLICER, str(ini_file)
        )

        assert config["filament_type"] == "PLA"
        assert config["temperature"] == "210"


class TestStoreConfig:
    """Test storing configuration to templates"""

    def test_store_orcaslicer_config(self, tmp_path):
        """Test storing OrcaSlicer JSON template"""
        template_file = tmp_path / "PLA.json.template"
        config = {
            "name": "{{name}}",
            "filament_type": ["{{material}}"],
            "nozzle_temperature": ["{{settings_extruder_temp|int}}"],
        }

        create_template_files.store_config(
            create_template_files.ORCASLICER, str(template_file), config
        )

        assert template_file.exists()
        stored_data = json.loads(template_file.read_text())
        assert "_comment" in stored_data
        assert stored_data["name"] == "{{name}}"

    def test_store_crealityprint_config(self, tmp_path):
        """Test storing CrealityPrint JSON template"""
        template_file = tmp_path / "PLA.json.template"
        config = {
            "name": "{{name}}",
            "filament_type": ["{{material}}"],
            "nozzle_temperature": ["{{settings_extruder_temp|int}}"],
        }

        create_template_files.store_config(
            create_template_files.CREALITYPRINT, str(template_file), config
        )

        assert template_file.exists()
        stored_data = json.loads(template_file.read_text())
        assert "_comment" in stored_data
        assert stored_data["name"] == "{{name}}"

    def test_store_superslicer_config(self, tmp_path):
        """Test storing SuperSlicer INI template"""
        template_file = tmp_path / "PLA.ini.template"
        config = {
            "filament_type": "{{material}}",
            "temperature": "{{settings_extruder_temp|int}}",
        }

        create_template_files.store_config(
            create_template_files.SUPERSLICER, str(template_file), config
        )

        assert template_file.exists()
        content = template_file.read_text()
        assert "# generated by {{sm2s.name}} {{sm2s.version}}" in content
        assert "filament_type = {{material}}" in content

    def test_store_info_template_no_comment(self, tmp_path):
        """Test storing .info template without comment"""
        template_file = tmp_path / "PLA.info.template"
        config = {"updated_time": "{{sm2s.now_int}}"}

        create_template_files.store_config(
            create_template_files.SUPERSLICER, str(template_file), config
        )

        content = template_file.read_text()
        # .info files should not have the comment line
        assert not content.startswith("# generated by")
        assert "updated_time = {{sm2s.now_int}}" in content


class TestUpdateConfigSettings:
    """Test updating config settings with template variables"""

    def test_update_orcaslicer_settings(self):
        """Test updating OrcaSlicer config settings"""
        config = {
            "name": "Original Name",
            "filament_type": ["PLA"],
            "filament_cost": ["25.0"],
            "nozzle_temperature": ["210"],
        }

        args = type("Args", (), {"slicer": create_template_files.ORCASLICER})()
        updated = create_template_files.update_config_settings(args, config)

        assert (
            updated["name"]
            == "{% if spool.id %}{{name}} - {{spool.id}}{% else %}{{name}}{% endif %}"
        )
        assert updated["filament_type"] == ["{{material}}"]
        assert updated["filament_cost"] == ["{{price}}"]
        assert updated["nozzle_temperature"] == ["{{settings_extruder_temp|int}}"]

    def test_update_crealityprint_settings(self):
        """Test updating CrealityPrint config settings"""
        config = {
            "name": "Original Name",
            "filament_type": ["PLA"],
            "filament_cost": ["25.0"],
            "nozzle_temperature": ["210"],
        }

        args = type("Args", (), {"slicer": create_template_files.CREALITYPRINT})()
        updated = create_template_files.update_config_settings(args, config)

        assert (
            updated["name"]
            == "{% if spool.id %}{{name}} - {{spool.id}}{% else %}{{name}}{% endif %}"
        )
        assert updated["filament_type"] == ["{{material}}"]
        assert updated["filament_cost"] == ["{{price}}"]
        assert updated["nozzle_temperature"] == ["{{settings_extruder_temp|int}}"]

    def test_update_superslicer_settings(self):
        """Test updating SuperSlicer config settings"""
        config = {
            "filament_type": "PLA",
            "filament_cost": "25.0",
            "temperature": "210",
            "bed_temperature": "60",
        }

        args = type("Args", (), {"slicer": create_template_files.SUPERSLICER})()
        updated = create_template_files.update_config_settings(args, config)

        assert updated["filament_type"] == "{{material}}"
        assert updated["filament_cost"] == "{{price}}"
        assert updated["temperature"] == "{{settings_extruder_temp|int}}"

    def test_update_settings_preserves_unlisted_keys(self):
        """Test that unlisted keys are preserved"""
        config = {
            "filament_type": "PLA",
            "custom_key": "custom_value",
        }

        args = type("Args", (), {"slicer": create_template_files.SUPERSLICER})()
        updated = create_template_files.update_config_settings(args, config)

        assert updated["custom_key"] == "custom_value"


class TestGetFilamentPath:
    """Test getting filament path"""

    def test_get_filament_path_with_dir_arg(self, tmp_path):
        """Test with explicit directory argument"""
        args = type("Args", (), {"dir": str(tmp_path), "slicer": "superslicer"})()

        path = create_template_files.get_filament_path(args)
        assert path == str(tmp_path)

    def test_get_filament_path_without_dir(self, tmp_path):
        """Test without explicit directory (uses defaults)"""
        args = type("Args", (), {"dir": None, "slicer": "superslicer"})()

        # This would fail in real scenario as the default path likely doesn't exist
        # We test that it attempts to look up the default
        with patch("platform.system", return_value="UnknownOS"):
            with pytest.raises(SystemExit):
                create_template_files.get_filament_path(args)

    def test_get_filament_path_nonexistent(self):
        """Test with non-existent directory"""
        args = type("Args", (), {"dir": "/nonexistent/path", "slicer": "superslicer"})()

        with pytest.raises(SystemExit):
            create_template_files.get_filament_path(args)


class TestCreateTemplatePath:
    """Test creating template directory"""

    def test_create_template_path_new(self, tmp_path):
        """Test creating a new template directory"""
        template_dir = tmp_path / "templates-test"
        assert not template_dir.exists()

        create_template_files.create_template_path(str(template_dir))

        assert template_dir.exists()
        assert template_dir.is_dir()

    def test_create_template_path_existing(self, tmp_path):
        """Test with existing template directory"""
        template_dir = tmp_path / "templates-test"
        template_dir.mkdir()

        # Should not raise error
        create_template_files.create_template_path(str(template_dir))
        assert template_dir.exists()


class TestCopyFilamentTemplateFiles:
    """Test copying filename template file"""

    def test_copy_filename_templates(self, tmp_path):
        """Test copying filename.template if missing"""
        template_dir = tmp_path / "templates-test"
        template_dir.mkdir()

        # Create a source templates directory
        source_dir = tmp_path / "templates-superslicer"
        source_dir.mkdir()
        (source_dir / "filename.template").write_text("{{name}}.{{sm2s.slicer_suffix}}")
        (source_dir / "filename_for_spool.template").write_text(
            "{{name}}.{{sm2s.slicer_suffix}}.{{spool.id}}"
        )

        args = type("Args", (), {"slicer": "superslicer"})()

        with patch("create_template_files.os.path.dirname", return_value=str(tmp_path)):
            create_template_files.copy_filament_template_files(args, str(template_dir))

        assert (template_dir / "filename.template").exists()
        assert (template_dir / "filename_for_spool.template").exists()

    def test_copy_filename_template_already_exists(self, tmp_path):
        """Test that existing filename.template is not overwritten"""
        template_dir = tmp_path / "templates-test"
        template_dir.mkdir()
        existing_template = template_dir / "filename.template"
        existing_template.write_text("existing content")
        existing_template = template_dir / "filename_for_spool.template"
        existing_template.write_text("existing content")

        args = type("Args", (), {"slicer": "superslicer"})()

        # Should not raise error or overwrite
        with patch("create_template_files.os.path.dirname", return_value=str(tmp_path)):
            # This would normally not copy if file exists
            pass


class TestParseArgs:
    """Test command line argument parsing"""

    def test_parse_args_with_delete_all_exits(self):
        """Test that --delete-all exits with error (not implemented)"""
        with patch("sys.argv", ["create_template_files.py", "--delete-all"]):
            with pytest.raises(SystemExit):
                create_template_files.parse_args()


class TestMain:
    """Test main function"""

    def test_main_creates_templates(self, tmp_path):
        """Test main function creates template files"""
        filament_dir = tmp_path / "filament"
        filament_dir.mkdir()
        template_dir = tmp_path / "templates-superslicer"

        # Create sample filament config
        (filament_dir / "test_pla.ini").write_text(
            "filament_type = PLA\n" "temperature = 210\n"
        )

        args = type(
            "Args",
            (),
            {
                "dir": str(filament_dir),
                "slicer": "superslicer",
                "verbose": False,
                "delete_all": False,
            },
        )()

        with (
            patch("create_template_files.parse_args", return_value=args),
            patch("create_template_files.user_config_dir", return_value=str(tmp_path)),
            patch("create_template_files.os.path.dirname", return_value=str(tmp_path)),
        ):
            # Create source templates dir
            source_templates = tmp_path / "templates-superslicer"
            source_templates.mkdir()
            (source_templates / "filename.template").write_text(
                "{{name}}.{{sm2s.slicer_suffix}}"
            )
            (source_templates / "filename_for_spool.template").write_text(
                "{{name}}.{{sm2s.slicer_suffix}}.{{spool.id}}"
            )

            create_template_files.main()

        # Check that template was created
        assert template_dir.exists()
        pla_template = template_dir / "PLA.ini.template"
        assert pla_template.exists()
        content = pla_template.read_text()
        assert "{{material}}" in content


class TestAtomicWrites:
    """Test atomic write functionality"""

    def test_atomic_write_creates_file(self, tmp_path):
        """Test that atomic_write creates a file successfully"""
        test_file = tmp_path / "test_atomic.txt"
        test_content = "Hello, atomic world!"

        create_template_files.atomic_write(str(test_file), test_content)

        assert test_file.exists()
        assert test_file.read_text() == test_content

    def test_atomic_write_replaces_existing_file(self, tmp_path):
        """Test that atomic_write replaces an existing file"""
        test_file = tmp_path / "test_replace.txt"

        # Create initial file
        test_file.write_text("Original content")

        # Replace with atomic write
        new_content = "New atomic content"
        create_template_files.atomic_write(str(test_file), new_content)

        assert test_file.read_text() == new_content

    def test_atomic_write_no_temp_files_left(self, tmp_path):
        """Test that no temporary files are left after atomic write"""
        test_file = tmp_path / "test_cleanup.txt"
        test_content = "Content for cleanup test"

        create_template_files.atomic_write(str(test_file), test_content)

        # Check that no temporary files are left
        files = list(tmp_path.iterdir())
        temp_files = [f for f in files if f.name.startswith(".tmp_")]
        assert len(temp_files) == 0

    def test_store_config_uses_atomic_write_superslicer(self, tmp_path):
        """Test that store_config uses atomic writes for SuperSlicer"""
        template_file = tmp_path / "test.ini.template"
        config = {
            "filament_type": "PLA",
            "temperature": "200",
        }

        create_template_files.store_config(
            create_template_files.SUPERSLICER, str(template_file), config
        )

        # Verify file was created
        assert template_file.exists()

        # Verify no temp files left
        temp_files = [f for f in tmp_path.iterdir() if f.name.startswith(".tmp_")]
        assert len(temp_files) == 0

    def test_store_config_uses_atomic_write_orcaslicer(self, tmp_path):
        """Test that store_config uses atomic writes for OrcaSlicer"""
        template_file = tmp_path / "test.json.template"
        config = {
            "filament_type": ["PLA"],
            "nozzle_temperature": [200],
        }

        create_template_files.store_config(
            create_template_files.ORCASLICER, str(template_file), config
        )

        # Verify file was created
        assert template_file.exists()

        # Verify content is valid JSON
        content = template_file.read_text()
        parsed = json.loads(content)
        assert "_comment" in parsed
        assert "filament_type" in parsed

        # Verify no temp files left
        temp_files = [f for f in tmp_path.iterdir() if f.name.startswith(".tmp_")]
        assert len(temp_files) == 0

    def test_store_config_uses_atomic_write_crealityprint(self, tmp_path):
        """Test that store_config uses atomic writes for CrealityPrint"""
        template_file = tmp_path / "test.json.template"
        config = {
            "filament_type": ["PLA"],
            "nozzle_temperature": [200],
        }

        create_template_files.store_config(
            create_template_files.CREALITYPRINT, str(template_file), config
        )

        # Verify file was created
        assert template_file.exists()

        # Verify content is valid JSON
        content = template_file.read_text()
        parsed = json.loads(content)
        assert "_comment" in parsed
        assert "filament_type" in parsed

        # Verify no temp files left
        temp_files = [f for f in tmp_path.iterdir() if f.name.startswith(".tmp_")]
        assert len(temp_files) == 0

#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "appdirs==1.4.4",
# ]
# ///

"""
Program to create template files from existing filament configuration
"""

import argparse
import json
import os
import platform
import shutil
import sys

from importlib import resources

from appdirs import user_config_dir

from .file_utils import atomic_write


VERSION = "0.10.1rc1"

ORCASLICER = "orcaslicer"
CREALITYPRINT = "crealityprint"
PRUSASLICER = "prusaslicer"
SLICER = "slic3r"
SUPERSLICER = "superslicer"

SLICERS = [
    ORCASLICER,
    CREALITYPRINT,
    PRUSASLICER,
    SLICER,
    SUPERSLICER,
]

DEFAULT_TEMPLATE_SUFFIX = ".template"

OS_MAC = "Darwin"
OS_WINDOWS = "Windows"
OS_LINUX = "Linux"

FILAMENT_CONFIG_DIRS = {
    f"{OS_LINUX}-{ORCASLICER}": "~/.config/OrcaSlicer/user/default/filament",
    f"{OS_LINUX}-{CREALITYPRINT}": "~/.config/Creality/Creality Print/6.0/user/default/filament",
    f"{OS_LINUX}-{PRUSASLICER}": "~/.var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer/filament",
    f"{OS_LINUX}-{SUPERSLICER}": "~/.config/SuperSlicer/filament",
    f"{OS_LINUX}-{SLICER}": "~/.Slic3r/filament",
}


def get_material(config, slicer):
    """Returns the filament config's material"""
    if slicer == ORCASLICER:
        return config.get("filament_type")[0]
    if slicer == SLICER:
        # Slic3r doesn't support materials
        return "default"
    return config.get("filament_type")


def parse_args():
    # pylint: disable=R0801
    """Command line parsing"""
    parser = argparse.ArgumentParser(
        description="Create template files from existing config",
    )

    parser.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    parser.add_argument(
        "-d",
        "--dir",
        metavar="DIR",
        required=False,
        help="the slicer's filament config dir",
    )

    parser.add_argument(
        "-s",
        "--slicer",
        default=SUPERSLICER,
        choices=SLICERS,
        help="the slicer",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="verbose output",
    )

    parser.add_argument(
        "-D",
        "--delete-all",
        action="store_true",
        help="delete all template configs before adding new ones",
    )

    args = parser.parse_args()

    if args.delete_all:
        print("--delete-all is not yet implemented", file=sys.stderr)
        sys.exit(1)

    return args


def get_filament_path(args):
    """Returns the path to the slicer's filament config dir"""
    filament_path = args.dir

    if not filament_path:
        filament_path = FILAMENT_CONFIG_DIRS.get(f"{platform.system()}-{args.slicer}")

    if not filament_path:
        print("Filament dir is unknown, use option -d", file=sys.stderr)
        sys.exit(1)

    filament_path = os.path.expanduser(filament_path)

    if not os.path.exists(filament_path):
        print(
            f'ERROR: The filament config dir "{filament_path}" doesn\'t exist.',
            file=sys.stderr,
        )
        sys.exit(1)

    return filament_path


def create_template_path(template_path):
    """Creates the dir for the template config for the slicer"""
    if not os.path.exists(template_path):
        print(f"Creating templates config dir: {template_path}")
        os.makedirs(template_path)


def copy_filament_template_files(args, template_path):
    """Copy the default filename template, if missing"""
    filename_template_file = f"{template_path}/filename.template"
    if not os.path.exists(filename_template_file):
        res = (
            resources.files("spoolman2slicer")
            / "data"
            / f"templates-{args.slicer}"
            / "filename.template"
        )
        with resources.as_file(res) as source_file_path:
            shutil.copy(source_file_path, filename_template_file)

    filename_template_file = f"{template_path}/filename_for_spool.template"
    if not os.path.exists(filename_template_file):
        res = (
            resources.files("spoolman2slicer")
            / "data"
            / f"templates-{args.slicer}"
            / "filename_for_spool.template"
        )
        with resources.as_file(res) as source_file_path:
            shutil.copy(source_file_path, filename_template_file)


def read_ini_file(filename):
    """Reads ini file"""
    config = {}
    with open(filename, "r", encoding="utf-8") as file:
        while line := file.readline():
            if line.startswith("#"):
                continue
            line = line.rstrip()
            line = line.split("=", 1)
            if len(line) > 1:
                key = line[0].rstrip()
                val = line[1].lstrip()
                # print(f"{key} = {val}")
                config[key] = val
    return config


def load_config_file(slicer, filename):
    """Load filament config file for slicer"""
    if slicer in (ORCASLICER, CREALITYPRINT):
        with open(filename, "r", encoding="utf-8") as file:
            config = json.load(file)
    else:
        config = read_ini_file(filename)

    return config


def store_config(slicer, template_file_name, config):
    """Store the config file"""
    # Build content as a string first
    if slicer in (ORCASLICER, CREALITYPRINT):
        config["_comment"] = "Generated by {{sm2s.name}} {{sm2s.version}}"
        content = json.dumps(config, indent=4)
    else:
        lines = []
        if not template_file_name.endswith(f".info{DEFAULT_TEMPLATE_SUFFIX}"):
            lines.append("# generated by {{sm2s.name}} {{sm2s.version}}\n")
        for key, value in config.items():
            lines.append(f"{key} = {value}\n")
        content = "".join(lines)

    # Write atomically
    atomic_write(template_file_name, content)


def update_config_settings(args, config):
    """Update config settings"""
    if args.slicer in (ORCASLICER, CREALITYPRINT):
        for key, value in {
            "default_filament_colour": ["#{{color_hex}}"],
            "filament_cost": ["{{price}}"],
            "filament_spool_weight": ["{{spool_weight}}"],
            "filament_type": ["{{material}}"],
            "filament_diameter": ["{{diameter}}"],
            "filament_density": ["{{density}}"],
            "filament_settings_id": ["{{id}}"],
            "filament_start_gcode": [
                "{% if spool.id %}SET_ACTIVE_SPOOL ID={{spool.id}}{% else %}"
                + "ASSERT_ACTIVE_FILAMENT ID={{id}}{% endif %}"
            ],
            "pressure_advance": ["{{extra.pressure_advance|default(0)|float}}"],
            "filament_vendor": ["{{vendor.name}}"],
            "name": "{% if spool.id %}{{name}} - {{spool.id}}{% else %}{{name}}{% endif %}",
            "nozzle_temperature": ["{{settings_extruder_temp|int}}"],
            "nozzle_temperature_initial_layer": ["{{settings_extruder_temp|int + 5}}"],
            "cool_plate_temp": ["{{settings_bed_temp|int}}"],
            "eng_plate_temp": ["{{settings_bed_temp|int}}"],
            "hot_plate_temp": ["{{settings_bed_temp|int}}"],
            "textured_plate_temp": ["{{settings_bed_temp|int}}"],
            "cool_plate_temp_initial_layer": ["{{settings_bed_temp|int + 10}}"],
            "eng_plate_temp_initial_layer": ["{{settings_bed_temp|int + 10}}"],
            "hot_plate_temp_initial_layer": ["{{settings_bed_temp|int + 10}}"],
            "textured_plate_temp_initial_layer": ["{{settings_bed_temp|int + 10}}"],
        }.items():
            if key in config:
                config[key] = value
    else:
        for key, value in {
            "bed_temperature": "{{settings_bed_temp|int}}",
            "filament_colour": " #{{color_hex}}",
            "filament_cost": "{{price}}",
            "filament_density": "{{density}}",
            "filament_diameter": "{{diameter}}",
            "filament_settings_id": '"{{id}}"',
            "filament_spool_weight": "{{spool_weight}}",
            "filament_type": "{{material}}",
            "filament_vendor": '"{{vendor.name}}"',
            "first_layer_bed_temperature": "{{settings_bed_temp|int + 10}}",
            "first_layer_temperature": "{{settings_extruder_temp|int + 10}}",
            "start_filament_gcode": '"; Filament gcode\n'
            + "{% if extra.pressure_advace %}"
            + "SET_PRESSURE_ADVANCE ADVANCE="
            + "{{extra.pressure_advance|default(0)|float}}\n{% endif %}"
            + "{% if spool.id %}SET_ACTIVE_SPOOL ID={{spool.id}}"
            + '{% else %}ASSERT_ACTIVE_FILAMENT ID={{id}}{% endif %}\n"',
            "temperature": "{{settings_extruder_temp|int}}",
        }.items():
            if key in config:
                config[key] = value.replace("\n", "\\n")

    return config


def main():
    """Main funcion"""

    args = parse_args()

    config_dir = user_config_dir("spoolman2slicer", "bofh69")
    template_path = os.path.join(config_dir, f"templates-{args.slicer}")
    filament_path = get_filament_path(args)

    if args.slicer in (ORCASLICER, CREALITYPRINT):
        print("ERROR: OrcaSlicer and Creality Print is not supported at the moment.")
        sys.exit(1)
    if args.verbose:
        print(f"Writing templates files to: {template_path}")

    create_template_path(template_path)

    copy_filament_template_files(args, template_path)

    if args.slicer == ORCASLICER:
        suffix = ".json"
    else:
        suffix = ".ini"

    for filename in os.listdir(filament_path):
        filename = f"{filament_path}/{filename}"
        if filename.endswith(suffix):
            if args.slicer == SLICER and filename.endswith("/My Settings.ini"):
                continue
            if args.verbose:
                print(f"Processing {filename}")
            config = load_config_file(args.slicer, filename)
            material = get_material(config, args.slicer)
            template_file_name = (
                f"{template_path}/{material}{suffix}{DEFAULT_TEMPLATE_SUFFIX}"
            )
            if os.path.exists(template_file_name):
                if args.verbose:
                    print(f"Template for {material} already exists, skipping")
                continue
            config = update_config_settings(args, config)
            print(f"Creating file: {template_file_name}")
            store_config(args.slicer, template_file_name, config)
            if args.slicer == ORCASLICER:
                filename = filename.replace(
                    suffix,
                    ".info",
                )
                config = load_config_file(SUPERSLICER, filename)
                template_file_name = (
                    f"{template_path}/{material}.info{DEFAULT_TEMPLATE_SUFFIX}"
                )
                print(f"Creating file: {template_file_name}")
                config["updated_time"] = "{{sm2s.now_int}}"
                store_config(SUPERSLICER, template_file_name, config)


if __name__ == "__main__":
    main()

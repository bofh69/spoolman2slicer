#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "appdirs==1.4.4",
# ]
# ///

"""
Program to create template files from existing filament configuration
"""

import argparse
import os
import platform
import sys

from appdirs import user_config_dir

from file_utils import atomic_write  # noqa: F401 # pylint: disable=unused-import
from template_core import (
    TemplateConfig,
    TemplateProcessor,
    VERSION,
    ORCASLICER,
    PRUSASLICER,
    SLICER,
    SUPERSLICER,
)

SLICERS = [
    ORCASLICER,
    PRUSASLICER,
    SLICER,
    SUPERSLICER,
]

OS_LINUX = "Linux"

FILAMENT_CONFIG_DIRS = {
    f"{OS_LINUX}-{ORCASLICER}": "~/.config/OrcaSlicer/user/default/filament",
    f"{OS_LINUX}-{PRUSASLICER}": "~/.var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer/filament",
    f"{OS_LINUX}-{SUPERSLICER}": "~/.config/SuperSlicer/filament",
    f"{OS_LINUX}-{SLICER}": "~/.Slic3r/filament",
}


# Re-export functions from template_core for backward compatibility with tests
def get_material(config, slicer):
    """Returns the filament config's material"""
    processor = TemplateProcessor(
        TemplateConfig(
            slicer=slicer,
            filament_path="",
            template_path="",
        )
    )
    return processor.get_material(config, slicer)


def read_ini_file(filename):
    """Reads ini file"""
    processor = TemplateProcessor(
        TemplateConfig(
            slicer=SUPERSLICER,
            filament_path="",
            template_path="",
        )
    )
    return processor.read_ini_file(filename)


def load_config_file(slicer, filename):
    """Load filament config file for slicer"""
    processor = TemplateProcessor(
        TemplateConfig(
            slicer=slicer,
            filament_path="",
            template_path="",
        )
    )
    return processor.load_config_file(slicer, filename)


def store_config(slicer, template_file_name, config):
    """Store the config file"""
    processor = TemplateProcessor(
        TemplateConfig(
            slicer=slicer,
            filament_path="",
            template_path="",
        )
    )
    processor.store_config(slicer, template_file_name, config)


def update_config_settings(slicer_or_args, config):
    """Update config settings with template variables"""
    # Handle both old API (args object) and new API (slicer string)
    if isinstance(slicer_or_args, str):
        slicer = slicer_or_args
    else:
        slicer = slicer_or_args.slicer

    processor = TemplateProcessor(
        TemplateConfig(
            slicer=slicer,
            filament_path="",
            template_path="",
        )
    )
    return processor.update_config_settings(slicer, config)


def create_template_path(template_path):
    """Creates the dir for the template config for the slicer"""
    processor = TemplateProcessor(
        TemplateConfig(
            slicer=SUPERSLICER,
            filament_path="",
            template_path=template_path,
        )
    )
    processor.create_template_path()


def copy_filament_template_files(args, template_path):
    """Copy the default filename template, if missing"""
    processor = TemplateProcessor(
        TemplateConfig(
            slicer=args.slicer,
            filament_path="",
            template_path=template_path,
        )
    )
    script_dir = os.path.dirname(__file__)
    processor.copy_filament_template_files(script_dir)


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


def main():
    """Main function"""
    args = parse_args()

    config_dir = user_config_dir("spoolman2slicer", "bofh69")
    template_path = os.path.join(config_dir, f"templates-{args.slicer}")
    filament_path = get_filament_path(args)

    if args.verbose:
        print(f"Writing templates files to: {template_path}")

    # Create configuration
    config = TemplateConfig(
        slicer=args.slicer,
        filament_path=filament_path,
        template_path=template_path,
        verbose=args.verbose,
        delete_all=args.delete_all,
    )

    # Create processor with simple console logger
    def console_logger(message: str, level: str = "INFO"):
        if level == "DEBUG" and not config.verbose:
            return
        print(message)

    processor = TemplateProcessor(config, logger=console_logger)

    # Run template creation
    script_dir = os.path.dirname(__file__)
    processor.run(script_dir)


if __name__ == "__main__":
    main()

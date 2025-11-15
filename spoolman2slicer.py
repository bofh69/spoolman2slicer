#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "appdirs==1.4.4",
#   "Jinja2==3.1.6",
#   "requests==2.32.4",
#   "websockets==12.0",
# ]
# ///


"""
Program to load filaments from Spoolman and create slicer filament configuration.
"""

import argparse
import os
import platform
import sys

from appdirs import user_config_dir

from spoolman_core import (
    SpoolmanConfig,
    SpoolmanProcessor,
    VERSION,
    ORCASLICER,
    PRUSASLICER,
    SLICER,
    SUPERSLICER,
)

parser = argparse.ArgumentParser(
    description="Fetches data from Spoolman and creates slicer filament config files.",
)

parser.add_argument("--version", action="version", version="%(prog)s " + VERSION)
parser.add_argument(
    "-d",
    "--dir",
    metavar="DIR",
    required=True,
    help="the slicer's filament config dir",
)

parser.add_argument(
    "-s",
    "--slicer",
    default=SUPERSLICER,
    choices=[ORCASLICER, PRUSASLICER, SLICER, SUPERSLICER],
    help="the slicer",
)

parser.add_argument(
    "-u",
    "--url",
    metavar="URL",
    default="http://localhost:7912",
    help="URL for the Spoolman installation",
)

parser.add_argument(
    "-U",
    "--updates",
    action="store_true",
    help="keep running and update filament configs if they're updated in Spoolman",
)

parser.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    help="verbose output",
)

parser.add_argument(
    "-V",
    "--variants",
    metavar="VALUE1,VALUE2..",
    default="",
    help="write one template per value, separated by comma",
)

parser.add_argument(
    "-D",
    "--delete-all",
    action="store_true",
    help="delete all filament configs before adding existing ones",
)

parser.add_argument(
    "--create-per-spool",
    choices=["all", "least-left", "most-recent"],
    help="create one output file per spool instead of per filament. "
    "'all': one file per spool. "
    "'least-left': one file per filament for the spool having the least filament left. "
    "'most-recent': one file per filament for the spool being most recently used.",
)

args = parser.parse_args()

config_dir = user_config_dir(appname="spoolman2slicer", appauthor=False, roaming=True)
template_path = os.path.join(config_dir, f"templates-{args.slicer}")

if args.verbose:
    print(f"Reading templates files from: {template_path}")

if not os.path.exists(template_path):
    script_dir = os.path.dirname(__file__)
    if platform.system() == "Windows":
        print(
            (
                f'ERROR: No templates found in "{template_path}".\n'
                "\n"
                "Install them with:\n"
                "\n"
                f'mkdir "{config_dir} /p"\n'
                f'copy "{script_dir}"\\templates-* "{config_dir}\\"\n'
            ),
            file=sys.stderr,
        )
    else:
        print(
            (
                f'ERROR: No templates found in "{template_path}".\n'
                "\n"
                "Install them with:\n"
                "\n"
                f"mkdir -p '{config_dir}'\n"
                f"cp -r '{script_dir}'/templates-* '{config_dir}/'\n"
            ),
            file=sys.stderr,
        )
    sys.exit(1)

if not os.path.exists(args.dir):
    print(f'ERROR: The output dir "{args.dir}" doesn\'t exist.', file=sys.stderr)
    sys.exit(1)


# Create module-level processor for backward compatibility with tests
_processor = None
_processor_args_hash = None


def _get_processor():
    """Get or create module-level processor instance"""
    global _processor, _processor_args_hash  # pylint: disable=global-statement

    # Create a hash of current args to detect changes
    current_hash = (
        args.dir,
        args.slicer,
        args.url,
        args.verbose,
        args.updates,
        args.variants,
        args.delete_all,
        args.create_per_spool,
    )

    # Recreate processor if args changed (important for tests that patch args)
    if _processor is None or _processor_args_hash != current_hash:
        config = SpoolmanConfig(
            output_dir=args.dir,
            slicer=args.slicer,
            spoolman_url=args.url,
            template_path=template_path,
            verbose=args.verbose,
            updates=args.updates,
            variants=args.variants,
            delete_all=args.delete_all,
            create_per_spool=args.create_per_spool,
        )

        def console_logger(message: str, level: str = "INFO"):
            if level == "DEBUG" and not args.verbose:
                return
            if level == "ERROR":
                print(message, file=sys.stderr)
            else:
                print(message)

        _processor = SpoolmanProcessor(config, logger=console_logger)
        _processor_args_hash = current_hash

    return _processor


# Initialize processor early to have module-level dicts available
_init_processor = _get_processor()

# Re-export module-level variables for backward compatibility with tests
# These are actual dict references that get updated when processor changes
filament_id_to_filename = _init_processor.filament_id_to_filename
filament_id_to_content = _init_processor.filament_id_to_content
filename_usage = _init_processor.filename_usage
vendors_cache = _init_processor.vendors_cache
filaments_cache = _init_processor.filaments_cache
spools_cache = _init_processor.spools_cache
templates = _init_processor.templates


# Re-export functions from spoolman_core for backward compatibility with tests
def get_config_suffix():
    """Returns the slicer's config file suffix(es)"""
    return _get_processor().get_config_suffix()


def add_sm2s_to_filament(filament, suffix, variant, spool=None):
    """Adds the sm2s object and spool field to filament"""
    _get_processor().add_sm2s_to_filament(filament, suffix, variant, spool)


def load_filaments_from_spoolman(url: str, max_retries: int = 3):
    """Load filaments json data from Spoolman with retry logic"""
    return _get_processor().load_filaments_from_spoolman(url, max_retries)


def get_filament_filename(filament):
    """Returns the filament's config filename"""
    return _get_processor().get_filament_filename(filament)


def get_filename_cache_key(filament):
    """Generate cache key for filament filename"""
    return _get_processor().get_filename_cache_key(filament)


def get_content_cache_key(filament):
    """Generate cache key for filament content"""
    return _get_processor().get_content_cache_key(filament)


def get_cached_filename_from_filaments_id(filament):
    """Returns the cached (old) filename for the filament"""
    return _get_processor().get_cached_filename_from_filaments_id(filament)


def set_cached_filename_from_filaments_id(filament, filename):
    """Stores the filename for the filament in a cache"""
    _get_processor().set_cached_filename_from_filaments_id(filament, filename)


def get_default_template_for_suffix(suffix):
    """Get the template filename for the given suffix"""
    return _get_processor().get_default_template_for_suffix(suffix)


def delete_filament(filament, is_update=False):
    """Delete the filament's file if no longer in use"""
    _get_processor().delete_filament(filament, is_update)


def delete_all_filaments():
    """Delete all config files in the filament dir"""
    _get_processor().delete_all_filaments()


def write_filament(filament):
    """Output the filament to the right file"""
    _get_processor().write_filament(filament)


def process_filaments_default(spools):
    """Process filaments in default mode: one file per filament"""
    _get_processor().process_filaments_default(spools)


def process_filaments_per_spool_all(spools):
    """Process filaments in 'all' mode: one file per non-archived spool"""
    _get_processor().process_filaments_per_spool_all(spools)


def select_spool_by_least_left(spool_list):
    """Select spool with lowest spool_weight, tie-break by lowest id"""
    return _get_processor().select_spool_by_least_left(spool_list)


def select_spool_by_most_recent(spool_list):
    """Select spool with highest last_used, tie-break by lowest id"""
    return _get_processor().select_spool_by_most_recent(spool_list)


def process_filaments_per_spool_selected(spools, selector_func):
    """Process filaments by selecting one spool per filament"""
    _get_processor().process_filaments_per_spool_selected(spools, selector_func)


def load_and_cache_data(url: str):
    """Load vendors, filaments, and spools from Spoolman and cache them"""
    _get_processor().load_and_cache_data(url)


def load_and_update_all_filaments(url: str):  # pylint: disable=unused-argument
    """Load the filaments from Spoolman and store them in the files"""
    _get_processor().load_and_update_all_filaments()


def handle_spool_update(spool):
    """Update files for a spool based on current mode"""
    _get_processor().handle_spool_update(spool)


def handle_vendor_update_msg(msg):
    """Handles vendor update msgs received via WS"""
    _get_processor().handle_vendor_update_msg(msg)


def handle_filament_update_msg(msg):
    """Handles filament update msgs received via WS"""
    _get_processor().handle_filament_update_msg(msg)


def handle_spool_update_msg(msg):
    """Handles spool update msgs received via WS"""
    _get_processor().handle_spool_update_msg(msg)


async def connect_updates():
    """Connect to Spoolman and receive updates for vendors, filaments, and spools"""
    await _get_processor().connect_updates()


def main():
    """Main function to run the spoolman2slicer tool"""
    processor = _get_processor()

    try:
        if args.updates:
            processor.run_with_updates()
        else:
            processor.run_once()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        sys.exit(0)
    except Exception:  # pylint: disable=broad-exception-caught
        sys.exit(1)


if __name__ == "__main__":
    main()

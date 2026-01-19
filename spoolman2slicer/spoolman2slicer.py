#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "appdirs==1.4.4",
#   "Jinja2==3.1.6",
#   "requests==2.32.5",
#   "urllib3>=2.6.0",
#   "websockets==12.0",
# ]
# ///


"""
Program to load filaments from Spoolman and create slicer filament configuration.
"""

import argparse
import asyncio
import json
import os
import platform
import sys
import time
import traceback

from appdirs import user_config_dir
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
import requests
from websockets.client import connect

from .file_utils import atomic_write


VERSION = "0.10.1rc1"

DEFAULT_TEMPLATE_PREFIX = "default."
DEFAULT_TEMPLATE_SUFFIX = ".template"
FILENAME_TEMPLATE = "filename.template"
FILENAME_FOR_SPOOL_TEMPLATE = "filename_for_spool.template"

REQUEST_TIMEOUT_SECONDS = 10

# pylint: disable=duplicate-code
ORCASLICER = "orcaslicer"
CREALITYPRINT = "crealityprint"
PRUSASLICER = "prusaslicer"
SLICER = "slic3r"
SUPERSLICER = "superslicer"

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
    choices=[ORCASLICER, CREALITYPRINT, PRUSASLICER, SLICER, SUPERSLICER],
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

if not os.path.exists(template_path):
    print(f'ERROR: No templates found in "{template_path}".', file=sys.stderr)
    sys.exit(1)

if not os.path.exists(args.dir):
    print(f'ERROR: The output dir "{args.dir}" doesn\'t exist.', file=sys.stderr)
    sys.exit(1)

loader = FileSystemLoader(template_path)
templates = Environment(loader=loader)  # nosec B701

filament_id_to_filename = {}
filament_id_to_content = {}

filename_usage = {}

vendors_cache = {}  # id -> vendor dict
filaments_cache = {}  # id -> filament dict
spools_cache = {}  # id -> spool dict
material_code_year_prefix = ""  # pylint: disable=invalid-name


def add_sm2s_to_filament(filament, suffix, variant, spool=None):
    """Adds the sm2s object and spool field to filament"""
    sm2s = {
        "name": parser.prog,
        "version": VERSION,
        "now": time.asctime(),
        "now_int": int(time.time()),
        "slicer_suffix": suffix,
        "variant": variant.strip(),
        "spoolman_url": args.url,
    }
    filament["sm2s"] = sm2s
    # Add spool field (empty dict if not provided)
    filament["spool"] = spool if spool is not None else {}


def get_config_suffix():
    """Returns the slicer's config file prefix"""
    if args.slicer in (SLICER, SUPERSLICER, PRUSASLICER):
        return ["ini"]
    if args.slicer in (ORCASLICER, CREALITYPRINT):
        return ["json", "info"]

    raise ValueError("That slicer is not yet supported")


def _log_error(message: str, details: str = None):
    """
    Log an error message to stderr.

    Args:
        message: Main error message
        details: Optional additional details
    """
    print(f"ERROR: {message}", file=sys.stderr)
    if details and args.verbose:
        print(f"  Details: {details}", file=sys.stderr)


def _log_info(message: str):
    """
    Log an informational message if verbose mode is enabled.

    Args:
        message: Message to log
    """
    print(f"INFO: {message}")


def _log_debug(message: str):
    """
    Log a debug message if verbose mode is enabled.

    Args:
        message: Message to log
    """
    if args.verbose:
        print(f"DEBUG: {message}")


# pylint: disable=too-many-branches  # Complex error handling requires multiple branches
def load_filaments_from_spoolman(url: str, max_retries: int = 3):
    """
    Load filaments json data from Spoolman with retry logic.

    Args:
        url: The URL to fetch data from
        max_retries: Maximum number of retry attempts (default: 3)

    Returns:
        List of spool data from Spoolman

    Raises:
        requests.exceptions.ConnectionError: If connection fails after all retries
        requests.exceptions.Timeout: If request times out after all retries
        json.JSONDecodeError: If response is not valid JSON
        requests.exceptions.HTTPError: If HTTP error occurs
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                _log_info(f"Retry attempt {attempt + 1} of {max_retries}")

            _log_debug(f"Fetching data from {url}")
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()  # Raise exception for HTTP errors

            try:
                data = json.loads(response.text)
                _log_info(f"Successfully loaded {len(data)} spools from Spoolman")
                return data
            except json.JSONDecodeError as ex:
                _log_error(
                    f"Failed to parse JSON response from Spoolman at {url}",
                    f"Response (first 500 chars): {response.text[:500]}",
                )
                raise json.JSONDecodeError(
                    f"Invalid JSON response from Spoolman: {ex.msg}",
                    ex.doc,
                    ex.pos,
                ) from ex

        except requests.exceptions.ConnectionError as ex:
            last_exception = ex
            error_msg = f"Could not connect to Spoolman at {url}"
            if attempt == max_retries - 1:
                _log_error(error_msg, str(ex))
                print("\nPlease check:", file=sys.stderr)
                print("  1. Is Spoolman running?", file=sys.stderr)
                print("  2. Is the URL correct?", file=sys.stderr)
                print(f"  3. Can you access {url} in a web browser?", file=sys.stderr)
            else:
                _log_info(f"{error_msg} (attempt {attempt + 1}/{max_retries})")
                wait_time = 2**attempt  # Exponential backoff: 1, 2, 4 seconds
                _log_info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            continue

        except requests.exceptions.Timeout as ex:
            last_exception = ex
            error_msg = (
                f"Request to Spoolman at {url} timed out after "
                f"{REQUEST_TIMEOUT_SECONDS} seconds"
            )
            if attempt == max_retries - 1:
                _log_error(error_msg)
                print("\nThe server is taking too long to respond.", file=sys.stderr)
                print(
                    "Please check if Spoolman is running and responsive.",
                    file=sys.stderr,
                )
            else:
                _log_debug(f"{error_msg} (attempt {attempt + 1}/{max_retries})")
                wait_time = 2**attempt
                _log_info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            continue

        except requests.exceptions.HTTPError as ex:
            _log_error(
                f"HTTP error {ex.response.status_code} from Spoolman at {url}", str(ex)
            )
            raise

    # If we get here, all retries failed
    if last_exception:
        raise last_exception

    # Should never reach here, but just in case
    raise RuntimeError(f"Failed to load data from {url} after {max_retries} attempts")


def get_filament_filename(filament):
    """Returns the filament's config filename"""
    # Use filename_for_spool template when in "all" mode
    template_name = (
        FILENAME_FOR_SPOOL_TEMPLATE
        if args.create_per_spool == "all"
        else FILENAME_TEMPLATE
    )
    template = templates.get_template(template_name)
    return args.dir.removesuffix("/") + "/" + template.render(filament).strip()


def get_filename_cache_key(filament):
    """
    Generate cache key for filament filename.

    Uses spool ID when in "all" mode, otherwise uses filament ID.
    Includes variant in the key to support per-variant filenames.
    """
    variant = filament.get("sm2s", {}).get("variant", "")
    if args.create_per_spool == "all" and filament.get("spool", {}).get("id"):
        return f"spool-{filament['spool']['id']}-{filament['sm2s']['slicer_suffix']}-{variant}"
    return f"{filament['id']}-{filament['sm2s']['slicer_suffix']}-{variant}"


def get_content_cache_key(filament):
    """
    Generate cache key for filament content.

    Uses spool ID when in "all" mode, otherwise uses filament ID.
    Includes variant in the key to support per-variant content.
    """
    variant = filament.get("sm2s", {}).get("variant", "")
    if args.create_per_spool == "all" and filament.get("spool", {}).get("id"):
        return f"spool-{filament['spool']['id']}-{variant}"
    return f"{filament['id']}-{variant}"


def get_cached_filename_from_filaments_id(filament):
    """Returns the cached (old) filename for the filament"""
    cache_key = get_filename_cache_key(filament)
    return filament_id_to_filename.get(cache_key)


def set_cached_filename_from_filaments_id(filament, filename):
    """Stores the filename for the filament in a cache"""
    cache_key = get_filename_cache_key(filament)
    filament_id_to_filename[cache_key] = filename


def get_default_template_for_suffix(suffix):
    """Get the template filename for the given suffix"""
    return f"{DEFAULT_TEMPLATE_PREFIX}{suffix}{DEFAULT_TEMPLATE_SUFFIX}"


def delete_filament(filament, is_update=False):
    """Delete the filament's file if no longer in use"""
    filename = get_cached_filename_from_filaments_id(filament)

    if filename not in filename_usage:
        return
    filename_usage[filename] -= 1
    if filename_usage[filename] > 0:
        return

    new_filename = None
    if is_update:
        new_filename = get_filament_filename(filament)

    if filename != new_filename:
        print(f"Deleting: {filename}")
        os.remove(filename)


def delete_all_filaments():
    """Delete all config files in the filament dir"""
    for filename in os.listdir(args.dir):
        for suffix in get_config_suffix():
            if filename.endswith("." + suffix):
                filename = args.dir + "/" + filename
                print(f"Deleting: {filename}")
                os.remove(filename)


def write_filament(filament):
    """Output the filament to the right file"""

    filename = get_filament_filename(filament)
    if filename in filename_usage:
        filename_usage[filename] += 1
    else:
        filename_usage[filename] = 1

    content_cache_key = get_content_cache_key(filament)

    old_filename = get_cached_filename_from_filaments_id(filament)

    set_cached_filename_from_filaments_id(filament, filename)

    if "material" in filament:
        template_name = (
            f"{filament['material']}.{filament['sm2s']['slicer_suffix']}.template"
        )
    else:
        template_name = get_default_template_for_suffix(
            filament["sm2s"]["slicer_suffix"]
        )

    try:
        template = templates.get_template(template_name)
        _log_debug(f"Using {template_name} as template")
    except TemplateNotFound:
        template_name = get_default_template_for_suffix(
            filament["sm2s"]["slicer_suffix"]
        )
        template = templates.get_template(template_name)
        _log_debug("Using the default template")

    _log_info(f"Rendering for filename: {filename}")
    _log_debug("Fields for the template:")
    _log_debug(filament)

    filament_text = template.render(filament)
    old_filament_text = filament_id_to_content.get(content_cache_key)

    if old_filament_text == filament_text and old_filename == filename:
        _log_debug("Same content, file not updated")
        return

    print(f"Writing to: {filename}")

    atomic_write(filename, filament_text)
    filament_id_to_content[content_cache_key] = filament_text

    if args.verbose:
        print()


def process_filaments_default(spools):
    """Process filaments in default mode: one file per filament (with empty spool dict)"""
    # Find all filaments that have at least one spool referring to them
    filament_ids_with_spools = set()
    for spool in spools:
        if not spool.get("archived", False) and "filament" in spool:
            filament_ids_with_spools.add(spool["filament"]["id"])

    # Process each filament that has spools
    for filament_id in filament_ids_with_spools:
        if filament_id in filaments_cache:
            filament = filaments_cache[filament_id].copy()
            if args.slicer == CREALITYPRINT:
                filament["spool_id"] = filament_id
                filament["material_code"] = material_code_year_prefix + str(
                    filament_id
                ).rjust(3, "0")
            for suffix in get_config_suffix():
                for variant in args.variants.split(","):
                    add_sm2s_to_filament(filament, suffix, variant)
                    write_filament(filament)


def process_filaments_per_spool_all(spools):
    """Process filaments in 'all' mode: one file per non-archived spool"""
    for spool in spools:
        # Skip archived spools
        if spool.get("archived", False):
            continue
        filament = spool["filament"].copy()  # Make a copy to avoid mutation
        if args.slicer == CREALITYPRINT:
            filament["spool_id"] = spool["id"]
            filament["material_code"] = material_code_year_prefix + str(
                spool["id"]
            ).rjust(3, "0")
        for suffix in get_config_suffix():
            for variant in args.variants.split(","):
                add_sm2s_to_filament(filament, suffix, variant, spool)
                write_filament(filament)


def select_spool_by_least_left(spool_list):
    """Select spool with lowest spool_weight, tie-break by lowest id"""
    return min(
        spool_list,
        key=lambda s: (s.get("spool_weight", float("inf")), s["id"]),
    )


def select_spool_by_most_recent(spool_list):
    """Select spool with highest last_used, tie-break by lowest id"""

    def last_used_key(s):
        last_used = s.get("last_used")
        if not last_used:
            # Empty/None goes to the end (lowest priority)
            return ("", s["id"])
        return (last_used, -s["id"])  # Negative for descending order on tie

    return max(spool_list, key=last_used_key)


def process_filaments_per_spool_selected(spools, selector_func):
    """
    Process filaments by selecting one spool per filament.

    Args:
        spools: List of spools from Spoolman
        selector_func: Function to select which spool to use for each filament
    """
    # Group spools by filament ID
    filament_to_spools = {}
    for spool in spools:
        # Skip archived spools
        if spool.get("archived", False):
            continue
        filament_id = spool["filament"]["id"]
        if filament_id not in filament_to_spools:
            filament_to_spools[filament_id] = []
        filament_to_spools[filament_id].append(spool)

    # For each filament, select the appropriate spool
    for spool_list in filament_to_spools.values():
        selected_spool = selector_func(spool_list)
        filament = selected_spool["filament"].copy()
        for suffix in get_config_suffix():
            for variant in args.variants.split(","):
                add_sm2s_to_filament(filament, suffix, variant, selected_spool)
                write_filament(filament)


def load_and_cache_data(url: str):
    """Load vendors, filaments, and spools from Spoolman and cache them"""
    # pylint: disable=global-variable-not-assigned
    global vendors_cache, filaments_cache, spools_cache, material_code_year_prefix

    material_code_year_prefix = str(str(time.strftime("%Y"))[-2:])
    _log_debug("Loading vendors from Spoolman")
    vendors_list = load_filaments_from_spoolman(url + "/api/v1/vendor")
    vendors_cache = {vendor["id"]: vendor for vendor in vendors_list}
    _log_info(f"Loaded {len(vendors_cache)} vendors")

    _log_debug("Loading filaments from Spoolman")
    filaments_list = load_filaments_from_spoolman(url + "/api/v1/filament")
    # Build filament dicts with vendor references
    for filament in filaments_list:
        # If the filament API returns nested vendor object, use it
        # Otherwise, look up vendor by vendor_id
        if "vendor" not in filament:
            vendor_id = filament.get("vendor_id")
            if vendor_id and vendor_id in vendors_cache:
                filament["vendor"] = vendors_cache[vendor_id]
        filaments_cache[filament["id"]] = filament
    _log_info(f"Loaded {len(filaments_cache)} filaments")

    _log_debug("Loading spools from Spoolman")
    spools_list = load_filaments_from_spoolman(url + "/api/v1/spool")
    # Build spool dicts with filament references (which include vendor)
    for spool in spools_list:
        # If the spool API returns nested filament object, use it but ensure vendor is set
        if "filament" in spool:
            filament = spool["filament"]
            if "vendor" not in filament:
                vendor_id = filament.get("vendor_id")
                if vendor_id and vendor_id in vendors_cache:
                    filament["vendor"] = vendors_cache[vendor_id]
            # Update filaments_cache with the nested filament to ensure consistency
            filaments_cache[filament["id"]] = filament
        else:
            # If filament is not nested, look up by filament_id
            filament_id = spool.get("filament_id")
            if filament_id and filament_id in filaments_cache:
                spool["filament"] = filaments_cache[filament_id]
        spools_cache[spool["id"]] = spool
    _log_info(f"Loaded {len(spools_cache)} spools")


def load_and_update_all_filaments(url: str):
    """Load the filaments from Spoolman and store them in the files"""
    load_and_cache_data(url)

    # Convert spools_cache to list for processing
    spools = list(spools_cache.values())

    if args.create_per_spool == "all":
        process_filaments_per_spool_all(spools)
    elif args.create_per_spool == "least-left":
        process_filaments_per_spool_selected(spools, select_spool_by_least_left)
    elif args.create_per_spool == "most-recent":
        process_filaments_per_spool_selected(spools, select_spool_by_most_recent)
    else:
        process_filaments_default(spools)


def _update_files_for_vendor_change(vendor):
    """Helper to update files when a vendor changes"""
    # Update all filaments that refer to this vendor
    for filament in filaments_cache.values():
        if filament.get("vendor", {}).get("id") == vendor["id"]:
            filament["vendor"] = vendor
            # Update all spools that refer to this filament
            for spool in spools_cache.values():
                if spool.get("filament", {}).get("id") == filament["id"]:
                    spool["filament"] = filament
                    # Update files if spool is active
                    if not spool.get("archived", False):
                        handle_spool_update(spool)


def handle_vendor_update_msg(msg):
    """Handles vendor update msgs received via WS"""
    vendor = msg["payload"]

    if msg["type"] == "added":
        # Add to cache
        vendors_cache[vendor["id"]] = vendor
    elif msg["type"] == "updated":
        # Update cache
        vendors_cache[vendor["id"]] = vendor
        _update_files_for_vendor_change(vendor)
    elif msg["type"] == "deleted":
        # No filament can refer it, remove it.
        vendor_id = vendor["id"]
        if vendor_id in vendors_cache:
            del vendors_cache[vendor_id]
    else:
        _log_info(f"Got unknown vendor update msg: {msg}")


def handle_filament_update_msg(msg):
    """Handles filament update msgs received via WS"""
    filament = msg["payload"]

    if msg["type"] == "added":
        # Add to cache with vendor reference
        if "vendor" not in filament:
            vendor_id = filament.get("vendor_id")
            if vendor_id and vendor_id in vendors_cache:
                filament["vendor"] = vendors_cache[vendor_id]
        filaments_cache[filament["id"]] = filament
    elif msg["type"] == "updated":
        # Update cache
        if "vendor" not in filament:
            vendor_id = filament.get("vendor_id")
            if vendor_id and vendor_id in vendors_cache:
                filament["vendor"] = vendors_cache[vendor_id]
        filaments_cache[filament["id"]] = filament
        # Update all spools that refer to this filament
        for spool in spools_cache.values():
            if spool.get("filament", {}).get("id") == filament["id"]:
                spool["filament"] = filament
                # Update files if spool is active
                if not spool.get("archived", False):
                    handle_spool_update(spool)
    elif msg["type"] == "deleted":
        # Can't be deleted if spools are referencing it.
        filament_id = filament["id"]
        if filament_id in filaments_cache:
            del filaments_cache[filament_id]
    else:
        _log_info(f"Got unknown filament update msg: {msg}")


def handle_spool_update(spool):
    """Update files for a spool based on current mode"""
    if "filament" not in spool:
        filament_id = spool.get("filament_id")
        if filament_id and filament_id in filaments_cache:
            spool["filament"] = filaments_cache[filament_id]

    filament = spool.get("filament")
    if not filament:
        return

    if args.create_per_spool == "all":
        # One file per spool
        if not spool.get("archived", False):
            filament_copy = filament.copy()
            for suffix in get_config_suffix():
                for variant in args.variants.split(","):
                    add_sm2s_to_filament(filament_copy, suffix, variant, spool)
                    delete_filament(filament_copy, is_update=True)
                    write_filament(filament_copy)
    elif args.create_per_spool in ["least-left", "most-recent"]:
        # Find all spools for this filament and reprocess
        filament_id = filament["id"]
        filament_spools = [
            s
            for s in spools_cache.values()
            if s.get("filament", {}).get("id") == filament_id
            and not s.get("archived", False)
        ]

        if filament_spools:
            if args.create_per_spool == "least-left":
                selected_spool = select_spool_by_least_left(filament_spools)
            else:  # most-recent
                selected_spool = select_spool_by_most_recent(filament_spools)

            filament_copy = selected_spool["filament"].copy()
            for suffix in get_config_suffix():
                for variant in args.variants.split(","):
                    add_sm2s_to_filament(filament_copy, suffix, variant, selected_spool)
                    delete_filament(filament_copy, is_update=True)
                    write_filament(filament_copy)
        else:
            # No active spools left, delete the file
            filament_copy = filament.copy()
            for suffix in get_config_suffix():
                for variant in args.variants.split(","):
                    add_sm2s_to_filament(filament_copy, suffix, variant)
                    delete_filament(filament_copy)
    else:
        # Default mode: one file per filament
        # Check if filament has any active spools
        # (or if cache is empty, assume this is the active spool)
        filament_id = filament["id"]
        has_active_spools = len(
            spools_cache
        ) == 0 or any(  # Cache not populated (e.g., in tests or initial load)
            s.get("filament", {}).get("id") == filament_id
            and not s.get("archived", False)
            for s in spools_cache.values()
        )

        if has_active_spools:
            filament_copy = filament.copy()
            for suffix in get_config_suffix():
                for variant in args.variants.split(","):
                    add_sm2s_to_filament(filament_copy, suffix, variant)
                    delete_filament(filament_copy, is_update=True)
                    write_filament(filament_copy)
        else:
            # No active spools, delete the file
            filament_copy = filament.copy()
            for suffix in get_config_suffix():
                for variant in args.variants.split(","):
                    add_sm2s_to_filament(filament_copy, suffix, variant)
                    delete_filament(filament_copy)


def handle_spool_update_msg(msg):
    """Handles spool update msgs received via WS"""
    spool = msg["payload"]

    if msg["type"] == "added":
        # Add to cache with filament reference
        if "filament" not in spool:
            filament_id = spool.get("filament_id")
            if filament_id and filament_id in filaments_cache:
                spool["filament"] = filaments_cache[filament_id]
        # Only add to cache if spool has an id
        if "id" in spool:
            spools_cache[spool["id"]] = spool
        # Update files
        handle_spool_update(spool)
    elif msg["type"] == "updated":
        # Check if filament has changed (for default mode cleanup)
        spool_id = spool.get("id")
        old_spool = spools_cache.get(spool_id) if spool_id else None
        old_filament = old_spool.get("filament") if old_spool else None

        # Update cache
        if "filament" not in spool:
            filament_id = spool.get("filament_id")
            if filament_id and filament_id in filaments_cache:
                spool["filament"] = filaments_cache[filament_id]
        # Only update cache if spool has an id
        if "id" in spool:
            spools_cache[spool["id"]] = spool

        # If filament changed and we're in default mode, handle old filament cleanup
        new_filament = spool.get("filament")
        if (
            old_filament
            and new_filament
            and old_filament.get("id") != new_filament.get("id")
            and not args.create_per_spool
        ):
            # Check if old filament has any remaining active spools
            old_filament_id = old_filament["id"]
            has_remaining_spools = any(
                s.get("filament", {}).get("id") == old_filament_id
                and not s.get("archived", False)
                for s in spools_cache.values()
            )
            if not has_remaining_spools:
                # Delete old filament file
                old_filament_copy = old_filament.copy()
                for suffix in get_config_suffix():
                    for variant in args.variants.split(","):
                        add_sm2s_to_filament(old_filament_copy, suffix, variant)
                        delete_filament(old_filament_copy)

        # Update files for new filament
        handle_spool_update(spool)
    elif msg["type"] == "deleted":
        # Remove from cache
        spool_id = spool.get("id")
        if spool_id and spool_id in spools_cache:
            # Get spool before deletion for update handling
            old_spool = spools_cache[spool_id]
            del spools_cache[spool_id]
            # Update files based on remaining spools
            if "filament" in old_spool:
                handle_spool_update(old_spool)
    else:
        _log_debug(f"Got unknown spool update msg: {msg}")


async def connect_updates():
    """Connect to Spoolman and receive updates for vendors, filaments, and spools"""
    ws_url = "ws" + args.url[4::] + "/api/v1/"
    while True:  # Keep trying to connect indefinitely
        try:
            async for connection in connect(ws_url):
                try:
                    async for msg in connection:
                        try:
                            parsed_msg = json.loads(msg)
                            _log_debug(f"WS-msg {msg}")
                            resource = parsed_msg.get("resource")

                            if resource == "vendor":
                                handle_vendor_update_msg(parsed_msg)
                            elif resource == "filament":
                                handle_filament_update_msg(parsed_msg)
                            elif resource == "spool":
                                handle_spool_update_msg(parsed_msg)
                            else:
                                _log_debug(f"Got unknown resource type: {resource}")
                        except json.JSONDecodeError as ex:
                            print(
                                f"WARNING: Failed to parse WebSocket message as JSON: {ex}",
                                file=sys.stderr,
                            )
                            print(
                                f"Message content (first 200 chars): {msg[:200]}",
                                file=sys.stderr,
                            )
                            continue
                # pylint: disable=broad-exception-caught  # Need to catch all to reconnect
                except Exception as ex:
                    print(
                        f"ERROR: WebSocket connection error: {ex}",
                        file=sys.stderr,
                    )
                    print("Will attempt to reconnect...", file=sys.stderr)
                    await asyncio.sleep(5)  # Wait before reconnecting
        # pylint: disable=broad-exception-caught  # Need to catch all for proper error reporting
        except Exception as ex:
            _log_error(f"Failed to connect to Spoolman WebSocket at {ws_url}: {ex}")
            print("Will retry connection in 5 seconds...", file=sys.stderr)
            await asyncio.sleep(5)  # Wait before retrying


def main():
    """Main function to run the spoolman2slicer tool"""
    if args.delete_all:
        delete_all_filaments()

    # In update mode, keep retrying until initial load succeeds
    # This is necessary because websocket payloads don't contain full vendor objects
    if args.updates:
        retry_delay = 5
        _log_debug("Update mode enabled - will retry initial load until successful")
        while True:
            try:
                load_and_update_all_filaments(args.url)
                _log_debug("Initial data load successful")
                break  # Success, proceed to websocket connection
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.HTTPError,
                json.JSONDecodeError,
            ) as ex:
                # Error details already logged by load_filaments_from_spoolman
                print(
                    f"Initial load failed in update mode: {type(ex).__name__}",
                    file=sys.stderr,
                )
                print(
                    f"Retrying in {retry_delay} seconds...",
                    file=sys.stderr,
                )
                time.sleep(retry_delay)
                continue
            # pylint: disable=broad-exception-caught  # Need to catch all unexpected errors
            except Exception as ex:
                _log_error(f"Unexpected error while loading filaments: {ex}")
                if args.verbose:
                    traceback.print_exc()
                print(
                    f"Retrying in {retry_delay} seconds...",
                    file=sys.stderr,
                )
                time.sleep(retry_delay)
                continue
    else:
        # Non-update mode: fail immediately on error
        try:
            load_and_update_all_filaments(args.url)
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
            json.JSONDecodeError,
        ) as ex:
            # Error details already logged by load_filaments_from_spoolman
            _log_error(f"Failed to load filaments: {type(ex).__name__}")
            sys.exit(1)
        # pylint: disable=broad-exception-caught  # Need to catch all unexpected errors
        except Exception as ex:
            _log_error(f"Unexpected error while loading filaments: {ex}")
            if args.verbose:
                traceback.print_exc()
            sys.exit(1)

    if args.updates:
        print("Waiting for updates...")
        try:
            asyncio.run(connect_updates())
        except KeyboardInterrupt:
            print("\nShutting down gracefully...")
            sys.exit(0)
        # pylint: disable=broad-exception-caught  # Need to catch all websocket errors
        except Exception as ex:
            print(
                f"\nERROR: Failed to maintain WebSocket connection: {ex}",
                file=sys.stderr,
            )
            if args.verbose:
                traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024 Sebastian Andersson <sebastian@bittr.nu>
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


VERSION = "0.0.2-3-gdf67a39"

DEFAULT_TEMPLATE_PREFIX = "default."
DEFAULT_TEMPLATE_SUFFIX = ".template"
FILENAME_TEMPLATE = "filename.template"
FILENAME_FOR_SPOOL_TEMPLATE = "filename_for_spool.template"

REQUEST_TIMEOUT_SECONDS = 10

ORCASLICER = "orcaslicer"
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
    if args.slicer in (SUPERSLICER, PRUSASLICER):
        return ["ini"]
    if args.slicer == ORCASLICER:
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
    if args.verbose:
        print(f"INFO: {message}", file=sys.stderr)


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

            _log_info(f"Fetching data from {url}")
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()  # Raise exception for HTTP errors

            try:
                data = json.loads(response.text)
                _log_info(f"Successfully loaded {len(data)} spools from Spoolman")
                return data
            except json.JSONDecodeError as ex:
                _log_error(
                    f"Failed to parse JSON response from Spoolman at {url}",
                    f"Response (first 500 chars): {response.text[:500]}"
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
                print("Please check if Spoolman is running and responsive.", file=sys.stderr)
            else:
                _log_info(f"{error_msg} (attempt {attempt + 1}/{max_retries})")
                wait_time = 2**attempt
                _log_info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            continue

        except requests.exceptions.HTTPError as ex:
            _log_error(
                f"HTTP error {ex.response.status_code} from Spoolman at {url}",
                str(ex)
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
    """
    if args.create_per_spool == "all" and filament.get("spool", {}).get("id"):
        return f"spool-{filament['spool']['id']}-{filament['sm2s']['slicer_suffix']}"
    return f"{filament['id']}-{filament['sm2s']['slicer_suffix']}"


def get_content_cache_key(filament):
    """
    Generate cache key for filament content.
    
    Uses spool ID when in "all" mode, otherwise uses filament ID.
    """
    if args.create_per_spool == "all" and filament.get("spool", {}).get("id"):
        return f"spool-{filament['spool']['id']}"
    return str(filament["id"])


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

    # old_filename = filament_id_to_filename.get(filament_id)
    old_filename = get_cached_filename_from_filaments_id(filament)

    # filament_id_to_filename[filament_id] = filename
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
        if args.verbose:
            print(f"Using {template_name} as template")
    except TemplateNotFound:
        template_name = get_default_template_for_suffix(
            filament["sm2s"]["slicer_suffix"]
        )
        template = templates.get_template(template_name)
        if args.verbose:
            print("Using the default template")

    if args.verbose:
        print(f"Rendering for filename: {filename}")
        print("Fields for the template:")
        print(filament)

    filament_text = template.render(filament)
    old_filament_text = filament_id_to_content.get(content_cache_key)

    if old_filament_text == filament_text and old_filename == filename:
        if args.verbose:
            print("Same content, file not updated")
        return

    print(f"Writing to: {filename}")

    with open(filename, "w", encoding="utf-8") as cfg_file:
        print(filament_text, file=cfg_file)
    filament_id_to_content[content_cache_key] = filament_text

    if args.verbose:
        print()


def process_filaments_default(spools):
    """Process filaments in default mode: one file per filament (with empty spool dict)"""
    for spool in spools:
        filament = spool["filament"]
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


def load_and_update_all_filaments(url: str):
    """Load the filaments from Spoolman and store them in the files"""
    spools = load_filaments_from_spoolman(url + "/api/v1/spool")

    if args.create_per_spool == "all":
        process_filaments_per_spool_all(spools)
    elif args.create_per_spool == "least-left":
        process_filaments_per_spool_selected(spools, select_spool_by_least_left)
    elif args.create_per_spool == "most-recent":
        process_filaments_per_spool_selected(spools, select_spool_by_most_recent)
    else:
        process_filaments_default(spools)


def handle_filament_update(filament):
    """Handles update of a filament"""
    for variant in args.variants.split(","):
        for suffix in get_config_suffix():
            add_sm2s_to_filament(filament, suffix, variant)
            delete_filament(filament, is_update=True)
            write_filament(filament)


def handle_spool_update_msg(msg):
    """Handles spool update msgs received via WS"""

    spool = msg["payload"]
    filament = spool["filament"]
    if msg["type"] == "added":
        for variant in args.variants.split(","):
            for suffix in get_config_suffix():
                add_sm2s_to_filament(filament, suffix, variant)
                write_filament(filament)
    elif msg["type"] == "updated":
        handle_filament_update(filament)
    elif msg["type"] == "deleted":
        for variant in args.variants.split(","):
            for suffix in get_config_suffix():
                add_sm2s_to_filament(filament, suffix, variant)
                delete_filament(filament)
    else:
        print(f"Got unknown filament update msg: {msg}")


def handle_filament_update_msg(msg):
    """Handles filamentspool update msgs received via WS"""

    if msg["type"] == "added":
        pass
    elif msg["type"] == "updated":
        filament = msg["payload"]
        handle_filament_update(filament)
    elif msg["type"] == "deleted":
        pass
    else:
        print(f"Got unknown filament update msg: {msg}")


async def connect_filament_updates():
    """Connect to Spoolman and receive updates to the filaments"""
    ws_url = "ws" + args.url[4::] + "/api/v1/filament"
    while True:  # Keep trying to connect indefinitely
        try:
            async for connection in connect(ws_url):
                try:
                    async for msg in connection:
                        try:
                            parsed_msg = json.loads(msg)
                            handle_filament_update_msg(parsed_msg)
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
                        f"ERROR: WebSocket connection error for filament updates: {ex}",
                        file=sys.stderr,
                    )
                    print("Will attempt to reconnect...", file=sys.stderr)
                    await asyncio.sleep(5)  # Wait before reconnecting
        # pylint: disable=broad-exception-caught  # Need to catch all for proper error reporting
        except Exception as ex:
            print(
                f"ERROR: Failed to connect to Spoolman WebSocket at {ws_url}",
                file=sys.stderr,
            )
            print(f"Error: {ex}", file=sys.stderr)
            print("Will retry connection in 5 seconds...", file=sys.stderr)
            await asyncio.sleep(5)  # Wait before retrying


async def connect_spool_updates():
    """Connect to Spoolman and receive updates to the spools"""
    ws_url = "ws" + args.url[4::] + "/api/v1/spool"
    while True:  # Keep trying to connect indefinitely
        try:
            async for connection in connect(ws_url):
                try:
                    async for msg in connection:
                        try:
                            parsed_msg = json.loads(msg)
                            handle_spool_update_msg(parsed_msg)
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
                        f"ERROR: WebSocket connection error for spool updates: {ex}",
                        file=sys.stderr,
                    )
                    print("Will attempt to reconnect...", file=sys.stderr)
                    await asyncio.sleep(5)  # Wait before reconnecting
        # pylint: disable=broad-exception-caught  # Need to catch all for proper error reporting
        except Exception as ex:
            print(
                f"ERROR: Failed to connect to Spoolman WebSocket at {ws_url}",
                file=sys.stderr,
            )
            print(f"Error: {ex}", file=sys.stderr)
            print("Will retry connection in 5 seconds...", file=sys.stderr)
            await asyncio.sleep(5)  # Wait before retrying


async def connect_updates():
    """Connect to spoolman to get updates"""
    await asyncio.gather(connect_filament_updates(), connect_spool_updates())


def main():
    """Main function to run the spoolman2slicer tool"""
    if args.delete_all:
        delete_all_filaments()

    # In update mode, keep retrying until initial load succeeds
    # This is necessary because websocket payloads don't contain full vendor objects
    if args.updates:
        retry_delay = 5
        _log_info("Update mode enabled - will retry initial load until successful")
        while True:
            try:
                load_and_update_all_filaments(args.url)
                _log_info("Initial data load successful")
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

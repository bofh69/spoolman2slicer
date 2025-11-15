#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Core business logic for spoolman2slicer, separated from CLI concerns.
This module can be used by both CLI and GUI applications.
"""

import asyncio
import json
import os
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import requests
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from websockets.client import connect

from file_utils import atomic_write


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


@dataclass
class SpoolmanConfig:
    """Configuration for spoolman2slicer operations"""

    output_dir: str
    slicer: str
    spoolman_url: str
    template_path: str
    verbose: bool = False
    updates: bool = False
    variants: str = ""
    delete_all: bool = False
    create_per_spool: Optional[str] = None  # None, "all", "least-left", or "most-recent"

    def __post_init__(self):
        """Validate configuration"""
        if self.slicer not in [ORCASLICER, PRUSASLICER, SLICER, SUPERSLICER]:
            raise ValueError(f"Unsupported slicer: {self.slicer}")
        if self.create_per_spool and self.create_per_spool not in [
            "all",
            "least-left",
            "most-recent",
        ]:
            raise ValueError(f"Invalid create_per_spool mode: {self.create_per_spool}")


class SpoolmanProcessor:
    """
    Processes Spoolman data and generates slicer configuration files.
    Can be used from CLI or GUI applications.
    """

    def __init__(self, config: SpoolmanConfig, logger: Optional[Callable] = None):
        """
        Initialize the processor.

        Args:
            config: Configuration object
            logger: Optional callable for logging messages (takes message string and level)
        """
        self.config = config
        self.logger = logger or self._default_logger

        # Initialize template environment
        loader = FileSystemLoader(config.template_path)
        self.templates = Environment(loader=loader)  # nosec B701

        # Internal caches
        self.filament_id_to_filename: Dict[str, str] = {}
        self.filament_id_to_content: Dict[str, str] = {}
        self.filename_usage: Dict[str, int] = {}
        self.vendors_cache: Dict[int, Dict] = {}
        self.filaments_cache: Dict[int, Dict] = {}
        self.spools_cache: Dict[int, Dict] = {}

    def _default_logger(self, message: str, level: str = "INFO"):
        """Default logger that prints to console"""
        if level == "DEBUG" and not self.config.verbose:
            return
        print(f"{level}: {message}")

    def _log_error(self, message: str, details: str = None):
        """Log an error message"""
        self.logger(f"ERROR: {message}", "ERROR")
        if details and self.config.verbose:
            self.logger(f"  Details: {details}", "ERROR")

    def _log_info(self, message: str):
        """Log an informational message"""
        self.logger(f"INFO: {message}", "INFO")

    def _log_debug(self, message: str):
        """Log a debug message"""
        if self.config.verbose:
            self.logger(f"DEBUG: {message}", "DEBUG")

    def get_config_suffix(self) -> List[str]:
        """Returns the slicer's config file suffix(es)"""
        if self.config.slicer in (SLICER, SUPERSLICER, PRUSASLICER):
            return ["ini"]
        if self.config.slicer == ORCASLICER:
            return ["json", "info"]
        raise ValueError("That slicer is not yet supported")

    def add_sm2s_to_filament(
        self, filament: Dict, suffix: str, variant: str, spool: Optional[Dict] = None
    ):
        """Adds the sm2s object and spool field to filament"""
        sm2s = {
            "name": "spoolman2slicer",
            "version": VERSION,
            "now": time.asctime(),
            "now_int": int(time.time()),
            "slicer_suffix": suffix,
            "variant": variant.strip(),
            "spoolman_url": self.config.spoolman_url,
        }
        filament["sm2s"] = sm2s
        filament["spool"] = spool if spool is not None else {}

    def load_filaments_from_spoolman(
        self, url: str, max_retries: int = 3
    ) -> List[Dict]:
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
                    self._log_info(f"Retry attempt {attempt + 1} of {max_retries}")

                self._log_debug(f"Fetching data from {url}")
                response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()

                try:
                    data = json.loads(response.text)
                    self._log_info(f"Successfully loaded {len(data)} items from {url}")
                    return data
                except json.JSONDecodeError as ex:
                    self._log_error(
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
                if attempt == max_retries - 1:
                    self._log_error(f"Could not connect to Spoolman at {url}", str(ex))
                else:
                    self._log_info(
                        f"Connection failed (attempt {attempt + 1}/{max_retries})"
                    )
                    wait_time = 2**attempt
                    self._log_info(f"Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                continue

            except requests.exceptions.Timeout as ex:
                last_exception = ex
                if attempt == max_retries - 1:
                    self._log_error(
                        f"Request to {url} timed out after {REQUEST_TIMEOUT_SECONDS}s"
                    )
                else:
                    self._log_debug(
                        f"Timeout (attempt {attempt + 1}/{max_retries})"
                    )
                    wait_time = 2**attempt
                    self._log_info(f"Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                continue

            except requests.exceptions.HTTPError as ex:
                self._log_error(
                    f"HTTP error {ex.response.status_code} from {url}", str(ex)
                )
                raise

        if last_exception:
            raise last_exception

        raise RuntimeError(f"Failed to load data from {url} after {max_retries} attempts")

    def get_filament_filename(self, filament: Dict) -> str:
        """Returns the filament's config filename"""
        template_name = (
            FILENAME_FOR_SPOOL_TEMPLATE
            if self.config.create_per_spool == "all"
            else FILENAME_TEMPLATE
        )
        template = self.templates.get_template(template_name)
        return (
            self.config.output_dir.removesuffix("/")
            + "/"
            + template.render(filament).strip()
        )

    def get_filename_cache_key(self, filament: Dict) -> str:
        """Generate cache key for filament filename"""
        if (
            self.config.create_per_spool == "all"
            and filament.get("spool", {}).get("id")
        ):
            return f"spool-{filament['spool']['id']}-{filament['sm2s']['slicer_suffix']}"
        return f"{filament['id']}-{filament['sm2s']['slicer_suffix']}"

    def get_content_cache_key(self, filament: Dict) -> str:
        """Generate cache key for filament content"""
        if (
            self.config.create_per_spool == "all"
            and filament.get("spool", {}).get("id")
        ):
            return f"spool-{filament['spool']['id']}"
        return str(filament["id"])

    def get_cached_filename_from_filaments_id(self, filament: Dict) -> Optional[str]:
        """Returns the cached (old) filename for the filament"""
        cache_key = self.get_filename_cache_key(filament)
        return self.filament_id_to_filename.get(cache_key)

    def set_cached_filename_from_filaments_id(self, filament: Dict, filename: str):
        """Stores the filename for the filament in a cache"""
        cache_key = self.get_filename_cache_key(filament)
        self.filament_id_to_filename[cache_key] = filename

    def get_default_template_for_suffix(self, suffix: str) -> str:
        """Get the template filename for the given suffix"""
        return f"{DEFAULT_TEMPLATE_PREFIX}{suffix}{DEFAULT_TEMPLATE_SUFFIX}"

    def delete_filament(self, filament: Dict, is_update: bool = False):
        """Delete the filament's file if no longer in use"""
        filename = self.get_cached_filename_from_filaments_id(filament)

        if filename not in self.filename_usage:
            return
        self.filename_usage[filename] -= 1
        if self.filename_usage[filename] > 0:
            return

        new_filename = None
        if is_update:
            new_filename = self.get_filament_filename(filament)

        if filename != new_filename:
            self._log_info(f"Deleting: {filename}")
            os.remove(filename)

    def delete_all_filaments(self):
        """Delete all config files in the filament dir"""
        for filename in os.listdir(self.config.output_dir):
            for suffix in self.get_config_suffix():
                if filename.endswith("." + suffix):
                    filename = self.config.output_dir + "/" + filename
                    self._log_info(f"Deleting: {filename}")
                    os.remove(filename)

    def write_filament(self, filament: Dict):
        """Output the filament to the right file"""
        filename = self.get_filament_filename(filament)
        if filename in self.filename_usage:
            self.filename_usage[filename] += 1
        else:
            self.filename_usage[filename] = 1

        content_cache_key = self.get_content_cache_key(filament)
        old_filename = self.get_cached_filename_from_filaments_id(filament)
        self.set_cached_filename_from_filaments_id(filament, filename)

        if "material" in filament:
            template_name = (
                f"{filament['material']}.{filament['sm2s']['slicer_suffix']}.template"
            )
        else:
            template_name = self.get_default_template_for_suffix(
                filament["sm2s"]["slicer_suffix"]
            )

        try:
            template = self.templates.get_template(template_name)
            self._log_debug(f"Using {template_name} as template")
        except TemplateNotFound:
            template_name = self.get_default_template_for_suffix(
                filament["sm2s"]["slicer_suffix"]
            )
            template = self.templates.get_template(template_name)
            self._log_debug("Using the default template")

        self._log_info(f"Rendering for filename: {filename}")
        self._log_debug("Fields for the template:")
        self._log_debug(str(filament))

        filament_text = template.render(filament)
        old_filament_text = self.filament_id_to_content.get(content_cache_key)

        if old_filament_text == filament_text and old_filename == filename:
            self._log_debug("Same content, file not updated")
            return

        self._log_info(f"Writing to: {filename}")
        atomic_write(filename, filament_text)
        self.filament_id_to_content[content_cache_key] = filament_text

    def process_filaments_default(self, spools: List[Dict]):
        """Process filaments in default mode: one file per filament"""
        filament_ids_with_spools = set()
        for spool in spools:
            if not spool.get("archived", False) and "filament" in spool:
                filament_ids_with_spools.add(spool["filament"]["id"])

        for filament_id in filament_ids_with_spools:
            if filament_id in self.filaments_cache:
                filament = self.filaments_cache[filament_id].copy()
                for suffix in self.get_config_suffix():
                    for variant in self.config.variants.split(","):
                        self.add_sm2s_to_filament(filament, suffix, variant)
                        self.write_filament(filament)

    def process_filaments_per_spool_all(self, spools: List[Dict]):
        """Process filaments in 'all' mode: one file per non-archived spool"""
        for spool in spools:
            if spool.get("archived", False):
                continue
            filament = spool["filament"].copy()
            for suffix in self.get_config_suffix():
                for variant in self.config.variants.split(","):
                    self.add_sm2s_to_filament(filament, suffix, variant, spool)
                    self.write_filament(filament)

    def select_spool_by_least_left(self, spool_list: List[Dict]) -> Dict:
        """Select spool with lowest spool_weight, tie-break by lowest id"""
        return min(
            spool_list,
            key=lambda s: (s.get("spool_weight", float("inf")), s["id"]),
        )

    def select_spool_by_most_recent(self, spool_list: List[Dict]) -> Dict:
        """Select spool with highest last_used, tie-break by lowest id"""

        def last_used_key(s):
            last_used = s.get("last_used")
            if not last_used:
                return ("", s["id"])
            return (last_used, -s["id"])

        return max(spool_list, key=last_used_key)

    def process_filaments_per_spool_selected(
        self, spools: List[Dict], selector_func: Callable
    ):
        """Process filaments by selecting one spool per filament"""
        filament_to_spools = {}
        for spool in spools:
            if spool.get("archived", False):
                continue
            filament_id = spool["filament"]["id"]
            if filament_id not in filament_to_spools:
                filament_to_spools[filament_id] = []
            filament_to_spools[filament_id].append(spool)

        for spool_list in filament_to_spools.values():
            selected_spool = selector_func(spool_list)
            filament = selected_spool["filament"].copy()
            for suffix in self.get_config_suffix():
                for variant in self.config.variants.split(","):
                    self.add_sm2s_to_filament(filament, suffix, variant, selected_spool)
                    self.write_filament(filament)

    def load_and_cache_data(self, url: str):
        """Load vendors, filaments, and spools from Spoolman and cache them"""
        self._log_debug("Loading vendors from Spoolman")
        vendors_list = self.load_filaments_from_spoolman(url + "/api/v1/vendor")
        self.vendors_cache = {vendor["id"]: vendor for vendor in vendors_list}
        self._log_info(f"Loaded {len(self.vendors_cache)} vendors")

        self._log_debug("Loading filaments from Spoolman")
        filaments_list = self.load_filaments_from_spoolman(url + "/api/v1/filament")
        for filament in filaments_list:
            if "vendor" not in filament:
                vendor_id = filament.get("vendor_id")
                if vendor_id and vendor_id in self.vendors_cache:
                    filament["vendor"] = self.vendors_cache[vendor_id]
            self.filaments_cache[filament["id"]] = filament
        self._log_info(f"Loaded {len(self.filaments_cache)} filaments")

        self._log_debug("Loading spools from Spoolman")
        spools_list = self.load_filaments_from_spoolman(url + "/api/v1/spool")
        for spool in spools_list:
            if "filament" in spool:
                filament = spool["filament"]
                if "vendor" not in filament:
                    vendor_id = filament.get("vendor_id")
                    if vendor_id and vendor_id in self.vendors_cache:
                        filament["vendor"] = self.vendors_cache[vendor_id]
                self.filaments_cache[filament["id"]] = filament
            else:
                filament_id = spool.get("filament_id")
                if filament_id and filament_id in self.filaments_cache:
                    spool["filament"] = self.filaments_cache[filament_id]
            self.spools_cache[spool["id"]] = spool
        self._log_info(f"Loaded {len(self.spools_cache)} spools")

    def load_and_update_all_filaments(self):
        """Load the filaments from Spoolman and store them in the files"""
        self.load_and_cache_data(self.config.spoolman_url)
        spools = list(self.spools_cache.values())

        if self.config.create_per_spool == "all":
            self.process_filaments_per_spool_all(spools)
        elif self.config.create_per_spool == "least-left":
            self.process_filaments_per_spool_selected(
                spools, self.select_spool_by_least_left
            )
        elif self.config.create_per_spool == "most-recent":
            self.process_filaments_per_spool_selected(
                spools, self.select_spool_by_most_recent
            )
        else:
            self.process_filaments_default(spools)

    def handle_spool_update(self, spool: Dict):
        """Update files for a spool based on current mode"""
        if "filament" not in spool:
            filament_id = spool.get("filament_id")
            if filament_id and filament_id in self.filaments_cache:
                spool["filament"] = self.filaments_cache[filament_id]

        filament = spool.get("filament")
        if not filament:
            return

        if self.config.create_per_spool == "all":
            if not spool.get("archived", False):
                filament_copy = filament.copy()
                for suffix in self.get_config_suffix():
                    for variant in self.config.variants.split(","):
                        self.add_sm2s_to_filament(filament_copy, suffix, variant, spool)
                        self.delete_filament(filament_copy, is_update=True)
                        self.write_filament(filament_copy)
        elif self.config.create_per_spool in ["least-left", "most-recent"]:
            filament_id = filament["id"]
            filament_spools = [
                s
                for s in self.spools_cache.values()
                if s.get("filament", {}).get("id") == filament_id
                and not s.get("archived", False)
            ]

            if filament_spools:
                if self.config.create_per_spool == "least-left":
                    selected_spool = self.select_spool_by_least_left(filament_spools)
                else:
                    selected_spool = self.select_spool_by_most_recent(filament_spools)

                filament_copy = selected_spool["filament"].copy()
                for suffix in self.get_config_suffix():
                    for variant in self.config.variants.split(","):
                        self.add_sm2s_to_filament(
                            filament_copy, suffix, variant, selected_spool
                        )
                        self.delete_filament(filament_copy, is_update=True)
                        self.write_filament(filament_copy)
            else:
                filament_copy = filament.copy()
                for suffix in self.get_config_suffix():
                    for variant in self.config.variants.split(","):
                        self.add_sm2s_to_filament(filament_copy, suffix, variant)
                        self.delete_filament(filament_copy)
        else:
            filament_id = filament["id"]
            has_active_spools = len(self.spools_cache) == 0 or any(
                s.get("filament", {}).get("id") == filament_id
                and not s.get("archived", False)
                for s in self.spools_cache.values()
            )

            if has_active_spools:
                filament_copy = filament.copy()
                for suffix in self.get_config_suffix():
                    for variant in self.config.variants.split(","):
                        self.add_sm2s_to_filament(filament_copy, suffix, variant)
                        self.delete_filament(filament_copy, is_update=True)
                        self.write_filament(filament_copy)
            else:
                filament_copy = filament.copy()
                for suffix in self.get_config_suffix():
                    for variant in self.config.variants.split(","):
                        self.add_sm2s_to_filament(filament_copy, suffix, variant)
                        self.delete_filament(filament_copy)

    def _update_files_for_vendor_change(self, vendor: Dict):
        """Helper to update files when a vendor changes"""
        for filament in self.filaments_cache.values():
            if filament.get("vendor", {}).get("id") == vendor["id"]:
                filament["vendor"] = vendor
                for spool in self.spools_cache.values():
                    if spool.get("filament", {}).get("id") == filament["id"]:
                        spool["filament"] = filament
                        if not spool.get("archived", False):
                            self.handle_spool_update(spool)

    def handle_vendor_update_msg(self, msg: Dict):
        """Handles vendor update msgs received via WS"""
        vendor = msg["payload"]

        if msg["type"] == "added":
            self.vendors_cache[vendor["id"]] = vendor
        elif msg["type"] == "updated":
            self.vendors_cache[vendor["id"]] = vendor
            self._update_files_for_vendor_change(vendor)
        elif msg["type"] == "deleted":
            vendor_id = vendor["id"]
            if vendor_id in self.vendors_cache:
                del self.vendors_cache[vendor_id]
        else:
            self._log_info(f"Got unknown vendor update msg: {msg}")

    def handle_filament_update_msg(self, msg: Dict):
        """Handles filament update msgs received via WS"""
        filament = msg["payload"]

        if msg["type"] == "added":
            if "vendor" not in filament:
                vendor_id = filament.get("vendor_id")
                if vendor_id and vendor_id in self.vendors_cache:
                    filament["vendor"] = self.vendors_cache[vendor_id]
            self.filaments_cache[filament["id"]] = filament
        elif msg["type"] == "updated":
            if "vendor" not in filament:
                vendor_id = filament.get("vendor_id")
                if vendor_id and vendor_id in self.vendors_cache:
                    filament["vendor"] = self.vendors_cache[vendor_id]
            self.filaments_cache[filament["id"]] = filament
            for spool in self.spools_cache.values():
                if spool.get("filament", {}).get("id") == filament["id"]:
                    spool["filament"] = filament
                    if not spool.get("archived", False):
                        self.handle_spool_update(spool)
        elif msg["type"] == "deleted":
            filament_id = filament["id"]
            if filament_id in self.filaments_cache:
                del self.filaments_cache[filament_id]
        else:
            self._log_info(f"Got unknown filament update msg: {msg}")

    def handle_spool_update_msg(self, msg: Dict):
        """Handles spool update msgs received via WS"""
        spool = msg["payload"]

        if msg["type"] == "added":
            if "filament" not in spool:
                filament_id = spool.get("filament_id")
                if filament_id and filament_id in self.filaments_cache:
                    spool["filament"] = self.filaments_cache[filament_id]
            if "id" in spool:
                self.spools_cache[spool["id"]] = spool
            self.handle_spool_update(spool)
        elif msg["type"] == "updated":
            spool_id = spool.get("id")
            old_spool = self.spools_cache.get(spool_id) if spool_id else None
            old_filament = old_spool.get("filament") if old_spool else None

            if "filament" not in spool:
                filament_id = spool.get("filament_id")
                if filament_id and filament_id in self.filaments_cache:
                    spool["filament"] = self.filaments_cache[filament_id]
            if "id" in spool:
                self.spools_cache[spool["id"]] = spool

            new_filament = spool.get("filament")
            if (
                old_filament
                and new_filament
                and old_filament.get("id") != new_filament.get("id")
                and not self.config.create_per_spool
            ):
                old_filament_id = old_filament["id"]
                has_remaining_spools = any(
                    s.get("filament", {}).get("id") == old_filament_id
                    and not s.get("archived", False)
                    for s in self.spools_cache.values()
                )
                if not has_remaining_spools:
                    old_filament_copy = old_filament.copy()
                    for suffix in self.get_config_suffix():
                        for variant in self.config.variants.split(","):
                            self.add_sm2s_to_filament(old_filament_copy, suffix, variant)
                            self.delete_filament(old_filament_copy)

            self.handle_spool_update(spool)
        elif msg["type"] == "deleted":
            spool_id = spool.get("id")
            if spool_id and spool_id in self.spools_cache:
                old_spool = self.spools_cache[spool_id]
                del self.spools_cache[spool_id]
                if "filament" in old_spool:
                    self.handle_spool_update(old_spool)
        else:
            self._log_debug(f"Got unknown spool update msg: {msg}")

    async def connect_updates(self):
        """Connect to Spoolman and receive updates for vendors, filaments, and spools"""
        ws_url = "ws" + self.config.spoolman_url[4::] + "/api/v1/"
        while True:
            try:
                async for connection in connect(ws_url):
                    try:
                        async for msg in connection:
                            try:
                                parsed_msg = json.loads(msg)
                                self._log_debug(f"WS-msg {msg}")
                                resource = parsed_msg.get("resource")

                                if resource == "vendor":
                                    self.handle_vendor_update_msg(parsed_msg)
                                elif resource == "filament":
                                    self.handle_filament_update_msg(parsed_msg)
                                elif resource == "spool":
                                    self.handle_spool_update_msg(parsed_msg)
                                else:
                                    self._log_debug(
                                        f"Got unknown resource type: {resource}"
                                    )
                            except json.JSONDecodeError as ex:
                                self._log_error(
                                    f"Failed to parse WebSocket message: {ex}"
                                )
                                continue
                    except Exception as ex:  # pylint: disable=broad-exception-caught
                        self._log_error(f"WebSocket connection error: {ex}")
                        await asyncio.sleep(5)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self._log_error(f"Failed to connect to WebSocket at {ws_url}: {ex}")
                await asyncio.sleep(5)

    def run_once(self):
        """Run once to update all filaments"""
        if self.config.delete_all:
            self.delete_all_filaments()

        try:
            self.load_and_update_all_filaments()
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
            json.JSONDecodeError,
        ) as ex:
            self._log_error(f"Failed to load filaments: {type(ex).__name__}")
            raise
        except Exception as ex:  # pylint: disable=broad-exception-caught
            self._log_error(f"Unexpected error while loading filaments: {ex}")
            if self.config.verbose:
                traceback.print_exc()
            raise

    def run_with_updates(self):
        """Run continuously with WebSocket updates"""
        if self.config.delete_all:
            self.delete_all_filaments()

        # Keep retrying initial load until successful
        retry_delay = 5
        self._log_debug("Update mode enabled - will retry initial load until successful")
        while True:
            try:
                self.load_and_update_all_filaments()
                self._log_debug("Initial data load successful")
                break
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.HTTPError,
                json.JSONDecodeError,
            ) as ex:
                self._log_error(
                    f"Initial load failed: {type(ex).__name__}. "
                    f"Retrying in {retry_delay} seconds..."
                )
                time.sleep(retry_delay)
                continue
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self._log_error(f"Unexpected error: {ex}")
                if self.config.verbose:
                    traceback.print_exc()
                time.sleep(retry_delay)
                continue

        # Start WebSocket connection
        self._log_info("Waiting for updates...")
        try:
            asyncio.run(self.connect_updates())
        except KeyboardInterrupt:
            self._log_info("Shutting down gracefully...")
        except Exception as ex:  # pylint: disable=broad-exception-caught
            self._log_error(f"Failed to maintain WebSocket connection: {ex}")
            if self.config.verbose:
                traceback.print_exc()
            raise

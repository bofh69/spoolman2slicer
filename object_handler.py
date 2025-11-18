"""Object handler for managing Spoolman entities (vendors, filaments, spools)"""

import logging
import json
import sys
import time
from typing import Any, Dict, Callable, Optional, List

import requests

REQUEST_TIMEOUT_SECONDS = 10


class ObjectHandler:
    """
    Generic handler for Spoolman objects (vendors, filaments, spools).

    Manages caching, API loading, and update message handling for an object type.
    Supports hierarchical relationships (e.g., vendor -> filament -> spool).
    """

    def __init__(
        self,
        name: str,
        api_endpoint: str,
        parent_handlers: Optional[Dict[str, "ObjectHandler"]] = None,
        on_update_callback: Optional[Callable[[Dict, str], None]] = None,
    ):
        """
        Initialize obj handler.

        Args:
            name: Object name (e.g., 'vendor', 'filament', 'spool')
            api_endpoint: API endpoint path (e.g., '/api/v1/vendor')
            parent_handlers: Dict of parent obj handlers for relationship resolution
                           e.g., {'vendor': vendor_handler} for filaments
            on_update_callback: Optional callback when obj is updated
                              Args: (obj_dict, msg_type: 'added'|'updated'|'deleted')
        """
        self.name = name
        self.api_endpoint = api_endpoint
        self.cache: Dict[int, Dict] = {}
        self.parent_handlers = parent_handlers or {}
        self.child_handlers: Dict[str, "ObjectHandler"] = {}
        self.on_update_callback = on_update_callback

    def _resolve_parent_references(self, obj: Dict) -> None:
        """
        Resolve parent obj references in the obj dict.

        For example, resolve vendor_id to vendor object in a filament.
        Modifies obj in-place by adding parent objects.
        """
        for parent_name, parent_handler in self.parent_handlers.items():
            # Check if parent object is already embedded
            if parent_name in obj:
                # Even if embedded, ensure it's the latest from cache
                parent_id = obj[parent_name].get("id")
                if parent_id and parent_id in parent_handler.cache:
                    obj[parent_name] = parent_handler.cache[parent_id]
                continue

            # Look for parent_id field (e.g., vendor_id for vendor)
            parent_id_field = f"{parent_name}_id"
            parent_id = obj.get(parent_id_field)

            if parent_id and parent_id in parent_handler.cache:
                obj[parent_name] = parent_handler.cache[parent_id]

    def _load_objects_from_spoolman(
        self, url: str, max_retries: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Load objects json data from Spoolman with retry logic.

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
                    logging.info("Retry attempt %d of %d", attempt + 1, max_retries)

                logging.debug("Fetching data from %s", url)
                response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()  # Raise exception for HTTP errors

                try:
                    data = json.loads(response.text)
                    logging.info(
                        "Successfully loaded %d spools from Spoolman", len(data)
                    )
                    return data
                except json.JSONDecodeError as ex:
                    logging.error(
                        "Failed to parse JSON response from Spoolman at %s"
                        + "Response (first 500 chars): %s",
                        url,
                        response.text[:500],
                    )
                    raise json.JSONDecodeError(
                        f"Invalid JSON response from Spoolman: {ex.msg}",
                        ex.doc,
                        ex.pos,
                    ) from ex

            except requests.exceptions.ConnectionError as ex:
                last_exception = ex
                error_msg = "Could not connect to Spoolman at %s: %s"
                if attempt == max_retries - 1:
                    logging.error("Could not connect to Spoolman at %s: %s", url, ex)
                    print("\nPlease check:", file=sys.stderr)
                    print("  1. Is Spoolman running?", file=sys.stderr)
                    print("  2. Is the URL correct?", file=sys.stderr)
                    print(
                        f"  3. Can you access {url} in a web browser?", file=sys.stderr
                    )
                else:
                    logging.info(
                        "Could not connect to Spoolman at %s. (attempt %d/%d)",
                        url,
                        attempt + 1,
                        max_retries,
                    )
                    wait_time = 2**attempt  # Exponential backoff: 1, 2, 4 seconds
                    logging.info("Waiting %d seconds before retry...", wait_time)
                    time.sleep(wait_time)
                continue

            except requests.exceptions.Timeout as ex:
                last_exception = ex
                error_msg = (
                    f"Request to Spoolman at {url} timed out after "
                    f"{REQUEST_TIMEOUT_SECONDS} seconds"
                )
                if attempt == max_retries - 1:
                    logging.error(error_msg)
                    print(
                        "\nThe server is taking too long to respond.", file=sys.stderr
                    )
                    print(
                        "Please check if Spoolman is running and responsive.",
                        file=sys.stderr,
                    )
                else:
                    logging.debug(
                        "%s (attempt %d/%d)", error_msg, attempt + 1, max_retries
                    )
                    wait_time = 2**attempt
                    logging.info("Waiting %d seconds before retry...", wait_time)
                    time.sleep(wait_time)
                continue

            except requests.exceptions.HTTPError as ex:
                logging.error(
                    "HTTP error %s from Spoolman at %s: %s",
                    ex.response.status_code,
                    url,
                    str(ex),
                )
                raise

        # If we get here, all retries failed
        if last_exception:
            raise last_exception

        # Should never reach here, but just in case
        raise RuntimeError(
            f"Failed to load data from {url} after {max_retries} attempts"
        )

    def load_from_api(self, base_url: str) -> None:
        """
        Load objs from API and populate cache.

        Args:
            base_url: Base URL for Spoolman (e.g., 'http://localhost:7912')
            load_func: Function to load data from URL
                      (e.g., load_filaments_from_spoolman)
        """
        url = base_url + self.api_endpoint
        logging.debug("Loading %ss from Spoolman", self.name)

        objs = self._load_objects_from_spoolman(url)

        for obj in objs:
            self._resolve_parent_references(obj)
            obj_id = obj.get("id")
            if obj_id:
                self.cache[obj_id] = obj

        logging.info("Loaded %d %ss", len(self.cache), self.name)

    def handle_update_message(self, msg: Dict) -> None:
        """
        Handle WebSocket update message for this obj.

        Args:
            msg: WebSocket message with 'type' and 'payload' fields
                 type: 'added' | 'updated' | 'deleted'
                 payload: obj object
        """
        msg_type = msg.get("type")
        obj = msg.get("payload")

        if not obj:
            logging.warning("Received %s message without payload: %s", self.name, msg)
            return

        if msg_type == "added":
            self._handle_added(obj)
        elif msg_type == "updated":
            self._handle_updated(obj)
        elif msg_type == "deleted":
            self._handle_deleted(obj)
        else:
            logging.info("Got unknown %s update msg type: %s", self.name, msg_type)

    def _handle_added(self, obj: Dict) -> None:
        """Handle obj addition"""
        self._resolve_parent_references(obj)
        obj_id = obj.get("id")

        if obj_id:
            self.cache[obj_id] = obj

        if self.on_update_callback:
            self.on_update_callback(obj, "added")

    def _handle_updated(self, obj: Dict) -> None:
        """Handle obj update"""
        self._resolve_parent_references(obj)
        obj_id = obj.get("id")

        if obj_id:
            self.cache[obj_id] = obj

        # Propagate update to children
        self._propagate_to_children(obj)

        if self.on_update_callback:
            self.on_update_callback(obj, "updated")

    def _handle_deleted(self, obj: Dict) -> None:
        """Handle obj deletion"""
        obj_id = obj.get("id")

        if obj_id and obj_id in self.cache:
            del self.cache[obj_id]

        if self.on_update_callback:
            self.on_update_callback(obj, "deleted")

    def _propagate_to_children(self, obj: Dict) -> None:
        """
        Update all child objs that reference this obj.

        For example, when a vendor is updated, update all filaments that
        reference that vendor, and then propagate further to spools.
        """
        obj_id = obj.get("id")
        if not obj_id:
            return

        for _child_name, child_handler in self.child_handlers.items():
            # Find all children that reference this obj
            for child in child_handler.cache.values():
                # Check if child references this obj
                parent_ref = child.get(self.name, {})
                if parent_ref.get("id") == obj_id:
                    # Update the reference
                    child[self.name] = obj
                    # Recursively propagate to grandchildren
                    child_handler._propagate_to_children(  # pylint: disable=protected-access
                        child
                    )
                    # Trigger callback if needed
                    if child_handler.on_update_callback:
                        child_handler.on_update_callback(child, "updated")

    def get(self, obj_id: int) -> Optional[Dict]:
        """Get a obj by ID from cache"""
        return self.cache.get(obj_id)

    def get_all(self) -> List[Dict]:
        """Get all objs from cache"""
        return list(self.cache.values())

    def __repr__(self):
        return f"ObjectHandler(name={self.name}, cached={len(self.cache)})"

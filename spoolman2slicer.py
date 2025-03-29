#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Program to load filaments from Spoolman and create slicer filament configuration.
"""

import argparse
import asyncio
import json
import os
import time
import sys

from jinja2 import Environment, FileSystemLoader, TemplateNotFound
import requests
from websockets.client import connect

DEFAULT_TEMPLATE_PREFIX = "default."
DEFAULT_TEMPLATE_SUFFIX = ".template"
FILENAME_TEMPLATE = "filename.template"

ORCASLICER = "orcaslicer"
PRUSASLICER = "prusaslicer"
SLICER = "slic3r"
SUPERSLICER = "superslicer"
VERSION = "0.0.2"

parser = argparse.ArgumentParser(
    description="Fetches filaments from Spoolman and creates slicer filament config files.",
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
    default="http://mainsailos.local:7912",
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
    "--variant",
    metavar="VALUE1,VALUE2..",
    default="",
    help="write one template per variant, separated by comma",
)

parser.add_argument(
    "-D",
    "--delete-all",
    action="store_true",
    help="delete all filament configs before adding existing ones",
)

args = parser.parse_args()

template_path = os.path.expanduser("~/.config/spoolman2slicer/templates-" + args.slicer)

if not os.path.exists(template_path):
    script_dir = os.path.dirname(__file__)
    print(
        (
            f'ERROR: No templates found in "{template_path}".\n'
            "\n"
            "Install them with:\n"
            "\n"
            "mkdir -p ~/.config/spoolman2slicer\n"
            f"cp -r {script_dir}/templates-* ~/.config/spoolman2slicer/\n"
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


def add_sm2s_to_filament(filament, suffix, variant):
    """Adds the sm2s object to filament"""
    sm2s = {
        "name": parser.prog,
        "version": VERSION,
        "now": time.asctime(),
        "now_int": int(time.time()),
        "slicer_suffix": suffix,
        "variant": variant.strip(),
    }
    filament["sm2s"] = sm2s


def get_config_suffix():
    """Returns the slicer's config file prefix"""
    if args.slicer == SUPERSLICER:
        return ["ini"]
    if args.slicer == ORCASLICER:
        return ["json", "info"]

    raise ValueError("That slicer is not yet supported")


def load_filaments_from_spoolman(url: str):
    """Load filaments json data from Spoolman"""
    data = requests.get(url, timeout=10)
    return json.loads(data.text)


def get_filament_filename(filament):
    """Returns the filament's config filename"""
    template = templates.get_template(FILENAME_TEMPLATE)
    return args.dir + "/" + template.render(filament).strip()


def get_cached_filename_from_filaments_id(filament):
    """Returns the cached (old) filename for the filament"""
    return filament_id_to_filename.get(
        f"{filament['id']}-{filament['sm2s']['slicer_suffix']}"
    )


def set_cached_filename_from_filaments_id(filament, filename):
    """Stores the filename for the filament in a cache"""
    filament_id_to_filename[f"{filament['id']}-{filament['sm2s']['slicer_suffix']}"] = (
        filename
    )


def get_default_template_for_suffix(suffix):
    """Get the template filename for the given suffix"""
    return f"{DEFAULT_TEMPLATE_PREFIX}{suffix}{DEFAULT_TEMPLATE_SUFFIX}"


def delete_filament(filament, is_update=False):
    """Delete the filament's file if no longer in use"""
    filename = get_cached_filename_from_filaments_id(filament)

    if not filename in filename_usage:
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

    filament_id = filament["id"]

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
    old_filament_text = filament_id_to_content.get(filament_id)

    if old_filament_text == filament_text and old_filename == filename:
        if args.verbose:
            print("Same content, file not updated")
        return

    print(f"Writing to: {filename}")

    with open(filename, "w", encoding="utf-8") as cfg_file:
        print(filament_text, file=cfg_file)
    filament_id_to_content[filament_id] = filament_text

    if args.verbose:
        print()


def load_and_update_all_filaments(url: str):
    """Load the filaments from Spoolman and store them in the files"""
    spools = load_filaments_from_spoolman(url + "/api/v1/spool")

    for spool in spools:
        filament = spool["filament"]
        for suffix in get_config_suffix():
            for variant in args.variant.split(","):
                add_sm2s_to_filament(filament, suffix, variant)
                write_filament(filament)


def handle_filament_update(filament):
    """Handles update of a filament"""
    for variant in args.variant.split(","):
        for suffix in get_config_suffix():
            add_sm2s_to_filament(filament, suffix, variant)
            delete_filament(filament, is_update=True)
            write_filament(filament)


def handle_spool_update_msg(msg):
    """Handles spool update msgs received via WS"""

    spool = msg["payload"]
    filament = spool["filament"]
    if msg["type"] == "added":
        for variant in args.variant.split(","):
            for suffix in get_config_suffix():
                add_sm2s_to_filament(filament, suffix, variant)
                write_filament(filament)
    elif msg["type"] == "updated":
        handle_filament_update(filament)
    elif msg["type"] == "deleted":
        for variant in args.variant.split(","):
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
    async for connection in connect("ws" + args.url[4::] + "/api/v1/filament"):
        async for msg in connection:
            msg = json.loads(msg)
            handle_filament_update_msg(msg)


async def connect_spool_updates():
    """Connect to Spoolman and receive updates to the filaments"""
    async for connection in connect("ws" + args.url[4::] + "/api/v1/spool"):
        async for msg in connection:
            msg = json.loads(msg)
            handle_spool_update_msg(msg)


async def connect_updates():
    """Connect to spoolman to get updates"""
    await asyncio.gather(connect_filament_updates(), connect_spool_updates())


if args.delete_all:
    delete_all_filaments()

try:
    load_and_update_all_filaments(args.url)
except requests.exceptions.ConnectionError as ex:
    print("Could not connect to SpoolMan:")
    print(ex)
    sys.exit(1)

if args.updates:
    print("Waiting for updates...")
    asyncio.run(connect_updates())

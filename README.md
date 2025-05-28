<!--
SPDX-FileCopyrightText: 2025 Andreas Gruber <grba@keba.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

[![REUSE status](https://api.reuse.software/badge/github.com/bud4ever/spoolman2slicerPro)](https://api.reuse.software/info/github.com/bud4ever/spoolman2slicerPro)
![GitHub Workflow Status](https://github.com/bud4ever/spoolman2slicerPro/actions/workflows/pylint.yml/badge.svg)

# Spoolman2Slicer Pro

## Intro

**spoolman2slicerPro** is a Python utility that exports active spools from [Spoolman](https://github.com/donkie/spoolman) into filament configuration files for:

* [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer)
* [PrusaSlicer](https://www.prusa3d.com/page/prusaslicer_424/)
* [SuperSlicer](https://github.com/supermerill/SuperSlicer)

This fork enhances the original functionality by **injecting the correct Spoolman spool ID automatically into the filament `start_gcode`**:

```gcode
SET_ACTIVE_SPOOL ID=<spool_id>
```

This enables seamless integration with [Moonraker](https://moonraker.readthedocs.io/) and tools like Klipper, allowing automatic spool activation.

## Key Features

* Fetches active spools from Spoolman
* Auto-generates slicer-compatible filament profiles via Jinja2 templates
* Injects correct `SET_ACTIVE_SPOOL ID=<spool_id>` per filament
* Compatible with OrcaSlicer, PrusaSlicer, SuperSlicer
* Supports multiple printer variants
* Can generate templates from existing slicer configs

## Usage

```sh
usage: spoolman2slicer.py [-h] [--version] -d DIR
                          [-s {orcaslicer,prusaslicer,slic3r,superslicer}]
                          [-u URL] [-U] [-v] [-V VALUE1,VALUE2..] [-D]
```

### Example (OrcaSlicer on Linux):

```sh
./spoolman2slicer.py -s orcaslicer -U -d ~/.config/OrcaSlicer/user/default/filament/
```

## Injected G-Code Example

The exported `.config.json` will contain:

```json
"start_gcode": "SET_ACTIVE_SPOOL ID=42\nM109 S[first_layer_temperature]"
```

This allows Moonraker to activate the spool automatically before heating begins.

## Setup

```sh
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```

## New Template Variable

Templates now have access to `{{ spool_id }}`. This can be used like so:

```jinja
"start_gcode": "{% if spool_id %}SET_ACTIVE_SPOOL ID={{ spool_id }}\n{% endif %}M109 S[first_layer_temperature]"
```

## Template Path

Templates are located in:

```sh
~/.config/spoolman2slicer/templates-<slicer>/<material>.<suffix>.template
```

If no material-specific template is found, `default.<suffix>.template` is used.

## Creating Templates from Existing Configs

Use the helper script:

```sh
./create_template_files.py -s orcaslicer -v
```

## Contributing

* Format with `make fmt`
* Lint with `make lint`
* PRs welcome for new slicers or advanced integrations

## License

This project is licensed under GPL-3.0-or-later.

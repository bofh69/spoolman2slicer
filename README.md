<!--
SPDX-FileCopyrightText: 2024 Sebastian Andersson <sebastian@bittr.nu>

SPDX-License-Identifier: GPL-3.0-or-later
-->

[![REUSE status](https://api.reuse.software/badge/github.com/bofh69/spoolman2slicer)](https://api.reuse.software/info/github.com/bofh69/spoolman2slicer)
![GitHub Workflow Status](https://github.com/bofh69/spoolman2slicer/actions/workflows/pylint.yml/badge.svg)

# Spoolman to slicer config generator
Create slicer filament configuration files from the spools in
[Spoolman](https://github.com/Donkie/Spoolman).

My templates are included for:
* [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer)
* [SuperSlicer](https://github.com/supermerill/SuperSlicer)

They are easy to update with your settings.

It should be possible to use it with
[slic3r](https://github.com/slic3r/Slic3r)
and [PrusaSlicer](https://github.com/prusa3d/PrusaSlicer) too, but there are no included templates for them.

## Usage

```sh
usage: spoolman2slicer.py [-h] [--version] -d DIR
                          [-s {orcaslicer,prusaslicer,slic3r,superslicer}]
                          [-u URL] [-U] [-D]

Fetches filaments from Spoolman and creates slicer filament config files.

options:
  -h, --help            show this help message and exit
  --version             show program\'s version number and exit
  -d DIR, --dir DIR     the filament config dir
  -s {orcaslicer,prusaslicer,slic3r,superslicer}, --slicer {orcaslicer,prusaslicer,slic3r,superslicer}
                        the slicer
  -u URL, --url URL     URL for the Spoolman installation
  -U, --updates         keep running and update filament configs if they\'re
                        updated in Spoolman
  -v, --verbose         verbose output
  -D, --delete-all      delete all filament configs before adding existing
                        ones
```

## Prepare for running

Run:
```sh
virtualenv venv
. venv/bin/activate
pip install -r requirements.txt
```


## Configuring the filament config templates

### Intro

spoolman2slicer uses [Jinja2](https://palletsprojects.com/p/jinja/)
templates for the configuration files it creates and it also uses
such a template for the configuration files' names.

### Where the files are read from

The templates are stored with the filaments' material's name in
`$HOME/.config/spoolman2slicer/templates-<slicer>/<material>.<suffix>.template`.

Where `slicer` is the used slicer (superslicer or orcaslicer).
`<material>` is the material used in the filament in Spoolman, ie PLA, ABS etc.
`<suffix>` is `ini` for Super Slicer, `info` and `json` for Orca Slicer
(it uses two files per filament).

### Available variables in the templates

The variables available to use in the templates comes from the return
data from Spoolman's filament request, described
[here](https://donkie.github.io/Spoolman/#tag/filament/operation/Get_filament_filament__filament_id__get).

spoolman2slicer also adds its own fields under the `sm2s` field:
* name - the name of the tool's program file.
* version - the version of the tool.
* now - the time when the file is created.
* now_int - the time when the file is created as the number of seconds since UNIX' epoch.
* slicer_suffix - the filename's suffix.


The available variables, and their values, can be printed by spoolman2slicer when
the filament is about to be written. Use the `-v` argument as argument
to spoolman2slicer when it is started.

With my Spoolman install the output can look like this (after pretty printing it):
```python
{
  'id': 17,
  'registered': '2024-10-08T12:23:04Z',
  'name': 'Gilford PLA+ Black',
  'vendor': {
    'id': 8,
    'registered': '2024-10-08T12:20:15Z',
    'name': 'Gilford',
    'extra': {}
  },
  'material': 'PLA',
  'price': 250.0,
  'density': 1.24,
  'diameter': 1.75,
  'weight': 1000.0,
  'spool_weight': 116.0,
  'article_number': '102001A',
  'settings_extruder_temp': 190,
  'settings_bed_temp': 60,
  'color_hex': '000000',
  'extra': {
    'pressure_advance': '0.045'
  },
  'sm2s': {
    'name': 'spoolman2slicer.py',
    'version': '0.0.1',
    'now': 'Sun Jan 26 10:57:51 2025',
    'now_int': 1737885471,
    'slicer_suffix': 'ini'
  }
}
```

### Writing the templates

The default templates are based on mine. They assume there is an extra
Spoolman filament field defined called "pressure_advance" and sets the
pressure advance settings based on it. The Orca Slicer files also assumes
one had added the Voron filaments in Orca Slicer as they inherit from them.

When making your own, it is better to copy your existing filament settings
files (one per material) and update the files' fields to use
the available variables.

To generate your own templates, copy your existing filament settings
from the slicer's config dir (on linux: `~/.config/SuperSlicer/filament/` or
`~/.config/OrcaSlicer/user/default/filament/`) to the template dir and
name it like described above.

In the templates, variables are surrounded by `{` and `}`.
For variables with values that contain more variables, you write all
the variable names with a dot between. Ie the vendor's name (`Gilford`
above) is written as: `{vendor.name}`. Be careful to use the same style as
the original file. If the file wrote `"Gilford"`, remember to keep the
`"` characters around the variable.

There is one special template file, the `filename.template`. It is used to create
the name of the generated files. Just copy the default one.

The templates are quite advanced. Follow the link above to jinja2 to
read its documentation.


## Run

### Ubuntu SuperSlicer
```sh
./spoolman2slicer.py -U -d ~/.config/SuperSlicer/filament/
```
### Ubuntu OrcaSlicer
```sh
./spoolman2slicer.py -s orcaslicer -U -d ~/.config/OrcaSlicer/user/default/filament/
```

### MacOs OrcaSlicer
```sh
./spoolman2slicer.py -s orcaslicer -U -d  ~/Library/Application\ Support/OrcaSlicer/user/default/filament
```

See the other options above.

## Development

Please format the code with `make fmt` and lint it with `make lint` before making a PR.

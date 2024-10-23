<!--
SPDX-FileCopyrightText: 2024 Sebastian Andersson <sebastian@bittr.nu>

SPDX-License-Identifier: GPL-3.0-or-later
-->

[![REUSE status](https://api.reuse.software/badge/github.com/bofh69/nfc2klipper)](https://api.reuse.software/info/github.com/bofh69/sm2ss)
![GitHub Workflow Status](https://github.com/bofh69/sm2ss/actions/workflows/pylint.yml/badge.svg)

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


## Config file templates

spoolman2slicer uses [Jinja2](https://palletsprojects.com/p/jinja/)
templates for the configuration files it creates. They are stored with
the filaments' material's name in `templates-<slicer>/`.
If the material's template isn't found, `default.<suffix>.template`
is used, where `suffix` is the config files suffix (`ini` for Super Slicer,
`info` and `json` for Orca Slicer).

The variables available in the templates is the return data from
Spoolman's filament request, described
[here](https://donkie.github.io/Spoolman/#tag/filament/operation/Get_filament_filament__filament_id__get).

They are also printed when the `-v` argument is used and
the filament is about to be written.

The default templates assumes there is an extra field defined called
"pressure_advance" and sets the pressure advance settings based on it.

sm2s also adds its own fields under the sm2s field:
* name - the name of the tool's program file.
* version - the version of the tool.
* now - the time when the file is created.
* now_int - the time when the file is created as the number of seconds since UNIX' epoch.
* slicer_suffix - the filename's suffix.

To generate your own templates, copy your existing filament settings
from the slicers config dir (on linux: `~/.config/SuperSlicer/filament/`,
`~/.config/OrcaSlicer/user/default/filament/`) to the template dir with
the material's name plus "<suffix>.template", then change the fields'
values like the provided template files.

The filename used for the filaments is created by
the `filename.template` template.


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

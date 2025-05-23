<!--
SPDX-FileCopyrightText: 2024 Sebastian Andersson <sebastian@bittr.nu>

SPDX-License-Identifier: GPL-3.0-or-later
-->

[![REUSE status](https://api.reuse.software/badge/github.com/bofh69/spoolman2slicer)](https://api.reuse.software/info/github.com/bofh69/spoolman2slicer)
![GitHub Workflow Status](https://github.com/bofh69/spoolman2slicer/actions/workflows/pylint.yml/badge.svg)

# Spoolman to slicer config generator

## Intro

A python program to export active Spoolman spools' data to filament
configurations files for:

* [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer)
* [PrusaSlicer](https://www.prusa3d.com/page/prusaslicer_424/)
* [SuperSlicer](https://github.com/supermerill/SuperSlicer)

It is easy be extended it to support more slicers.

The filament configuration files are based on templates. My templates
are included in the repo, but you should make your own based on your
settings. See below for how to do that.

<!--
It should be possible to use it with
[slic3r](https://github.com/slic3r/Slic3r)
and [PrusaSlicer](https://github.com/prusa3d/PrusaSlicer) too, but there are no included templates for them.
-->

## The workflow

You add your spools' manufacturers, filaments and the spools to Spoolman.

For each filament that has at least one active spool, spoolman2slicer creates a
filament configuration.

The next time you start the slicer you will see the available filaments.

My templates contain a "filament_start_gcode" command, `ASSERT_ACTIVE_FILAMENT ID={{id}}`,
which comes from
[this file](https://github.com/bofh69/nfc2klipper/blob/v0.0.4/klipper-spoolman.cfg) in
my other repo, [nfc2klipper](https://github.com/bofh69/nfc2klipper).
It will run whenever the print starts to use that filament.

That macro checks that the `active_filament` variable is the same as the choosen filament.

The `active_filament` variable is set by first calling `SET_ACTIVE_FILAMENT ID=` and the id.
That is called automatically by nfc2klipper.

There is a Moonraker agent [spool2klipper](https://github.com/bofh69/spool2klipper)
that can be used to update the active_filament variable whenever the spool is changed
in moonraker (via frontends, code macros) etc.


## Usage

```sh
usage: spoolman2slicer.py [-h] [--version] -d DIR
                          [-s {orcaslicer,prusaslicer,slic3r,superslicer}]
                          [-u URL] [-U] [-v] [-V VALUE1,VALUE2..] [-D]

Fetches filaments from Spoolman and creates slicer filament config files.

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  -d DIR, --dir DIR     the slicer's filament config dir
  -s {orcaslicer,prusaslicer,slic3r,superslicer}, --slicer {orcaslicer,prusaslicer,slic3r,superslicer}
                        the slicer
  -u URL, --url URL     URL for the Spoolman installation
  -U, --updates         keep running and update filament configs if they'reupdated in Spoolman
  -v, --verbose         verbose output
  -V VALUE1,VALUE2.., --variants VALUE1,VALUE2..
                        write one template per value, separated by comma
  -D, --delete-all      delete all filament configs before adding existing
                        ones
```

## Prepare for running

Run:
```sh
python3 -m venv venv
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
`<configdir>/spoolman2slicer/templates-<slicer>/<material>.<suffix>.template`.

`<configdir>` depends on the operating system:

| OS      | Path                                |
| :------ | :---------------------------------- |
| Linux   | `$HOME/.config`                     |
| MacOS   | `$HOME/Library/Application Support` |
| Windows | `%APPDATA%`                         |

`slicer` is the used slicer (superslicer or orcaslicer).
`<material>` is the material used in the filament in Spoolman, ie PLA, ABS etc.
`<suffix>` is `ini` for Super Slicer, `info` and `json` for Orca Slicer
(it uses two files per filament).

If the material isn't found, "default" is used as the material name.


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
* variant - one of the comma separated values given to the `--variants` argument, or an empty string.
* spoolman_url - the URL to spoolman.


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
    'slicer_suffix': 'ini',
    'variants': 'printer1',
    'spoolman_url': 'http://mainsailos.local:7912'
  }
}
```

### Creating templates from existing config

The `create_template_files.py` program can create basic template files
by copying existing filament config files.

Run it like this:
```sh
./create_template_files.py -s orcaslicer -v
```

If the program doesn't find the slicers' config dir, use the -d option:
```sh
./create_template_files.py -s orcaslicer -v -d "path/to/slicers/filament/config/dir"
```

If that's needed, please create/update a github issue with your operating
system, the slicer and the path where you found the filament config files.

---

If needed, the program will create the templates' config dir and
copy the `filename.template` file there.

For every filament config file in the slicer, it will create a template
file for its material, unless the material already has a template file.

The generated files might work for you, but you should check them
before using them. The start gcode probably needs updates as well as
the first layer temperatures.


### Writing the templates

The default templates as well as the generated template files are based
on my settings. They assume there is an extra
Spoolman filament field defined called "pressure_advance" and sets the
pressure advance settings based on it. The Orca Slicer files also assumes
one has added the Voron filaments in Orca Slicer as they inherit from them (but that's not
the case for the generated files).

When making your own, it is best to start with the generated files and
update the files' fields to fit your preferences.

In the templates, variables are surrounded by `{{` and `}}`.
For variables with values that contain more variables, you write all
the variable names with a dot between. Ie the vendor's name (`Gilford`
above) is written as: `{{vendor.name}}`. Be careful to use the same style as
the original file. If the file wrote `"Gilford"`, remember to keep the
`"` characters around the variable.

There is one special template file, the `filename.template`. It is used to create
the name of the generated files. Just use the default one, unless you
want different styles for your filenames.

You should also have a `default.<suffix>.template` file (or two with
OrcaSlicer, one for the .info file as well). It will be used if there is no
material specific template file. I've just copied the PLA templates.


The templates are quite advanced. Follow the link above to jinja2 to
read its documentation.

The [Jinja Playground](https://github.com/bofh69/jinja-playground) program can help
when editing the templates, by providing instant feedback.


## Generating for multiple printers, the variants argument

When using the `--variants` argument, it should have two or more more
values, separated by commas. Ie `--variants printer_small,printer_big`.

spoolman2slicer then generates one set of files per value.
Each time `sm2s.variant` will have one of the given values.

The templates can check the variable and output different fields or values depending on it.
Ie:
```
start_filament_gcode = "; Filament gcode\nSET_PRESSURE_ADVANCE={% if sm2s.variant == "printer_big %}{{extra.pressure_advance_big|default(0)|float}}{% else %}"{{extra.pressure_advance_small|default(0)|float}}{% endif %}\n"
```

The default `filename.template` file uses the variant variable to put
the variant first in the filename, if given, but the other template files don't use it.


## Run

### Ubuntu & OrcaSlicer
```sh
./spoolman2slicer.py -s orcaslicer -U -d ~/.config/OrcaSlicer/user/default/filament/
```

### Ubuntu & PrusaSlicer
```sh
./spoolman2slicer.py -s prusaslicer -U -d ~/.var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer/filament/
```

### Ubuntu & SuperSlicer
```sh
./spoolman2slicer.py -U -d ~/.config/SuperSlicer/filament/
```

### MacOs & OrcaSlicer
```sh
./spoolman2slicer.py -s orcaslicer -U -d  ~/Library/Application\ Support/OrcaSlicer/user/default/filament
```

See the other options above.

## Development

Please format the code with `make fmt` and lint it with `make lint` before making a PR.

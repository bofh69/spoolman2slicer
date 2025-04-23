#!/bin/sh
#
# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later


VERSION=$(git describe --tags)

sed -i "s/^VERSION = \".*\"\$/VERSION = \"${VERSION}\"/g" -- *.py

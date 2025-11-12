<!--
SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Release Process

This document describes how to publish a new release of spoolman2slicer to PyPI.

## Prerequisites

Before publishing a release, ensure that:
1. All tests pass on the main branch
2. The code has been reviewed and approved
3. You have configured PyPI trusted publishing (see below)

## PyPI Trusted Publishing Setup

This project uses PyPI's Trusted Publishing feature for secure package publishing without using API tokens.

### One-time Setup on PyPI:

1. Go to https://pypi.org/manage/account/publishing/
2. Add a new pending publisher with the following details:
   - PyPI Project Name: `spoolman2slicer`
   - Owner: `bofh69`
   - Repository name: `spoolman2slicer`
   - Workflow name: `publish-pypi.yml`
   - Environment name: `pypi`

Note: For the first release, you may need to manually create the project on PyPI or use TestPyPI first.

## Publishing a Release

To publish a new release:

1. **Create a GitHub Release:**
   - Go to https://github.com/bofh69/spoolman2slicer/releases/new
   - Create a new tag in the format `vX.Y.Z` (e.g., `v0.1.0`)
   - Add a release title and description with release notes
   - Click "Publish release"

   Note: Creating the release will automatically create the git tag, so you don't need to create and push the tag separately.

2. **Automatic Publishing:**
   The GitHub Actions workflow will automatically:
   - Trigger when the release is published
   - Update the version in Python files using `update_version.sh`
   - Build the package (source distribution and wheel)
   - Publish to PyPI using trusted publishing

3. **Verify the release:**
   - Check the GitHub Actions workflow run at https://github.com/bofh69/spoolman2slicer/actions
   - Verify the package appears on PyPI at https://pypi.org/project/spoolman2slicer/

## Version Numbering

This project follows semantic versioning (MAJOR.MINOR.PATCH):
- **MAJOR**: Incompatible API changes
- **MINOR**: New functionality in a backward-compatible manner
- **PATCH**: Backward-compatible bug fixes

Tags should follow the format: `vX.Y.Z` (e.g., `v0.1.0`, `v1.0.0`)

## Troubleshooting

### Workflow fails with "Trusted publishing exchange failure"
- Ensure the PyPI trusted publisher is configured correctly
- Verify the workflow name and environment match the PyPI settings

### Version mismatch
- Ensure the git tag is pushed before creating the release
- The `update_version.sh` script updates the VERSION variable in Python files from git tags

### Build failures
- Check that all dependencies are correctly specified in `pyproject.toml`
- Ensure `MANIFEST.in` includes all necessary non-Python files

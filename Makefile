# SPDX-FileCopyrightText: 2025 2024 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

.SILENT:

VENV:=venv
VENV_TIMESTAMP:=$(VENV)/.timestamp
PIP:=$(VENV)/bin/pip3
BLACK:=$(VENV)/bin/black
PYLINT:=$(VENV)/bin/pylint
REUSE:=$(VENV)/bin/reuse
PYTEST:=$(VENV)/bin/pytest

SRC=$(wildcard *.py)
SRC_TEST=$(wildcard tests/*.py)

help:
	@echo Available targets:
	@echo fmt - formats the python files.
	@echo lint - check the python files with pylint.
	@echo test - run the test suite.
	@echo test-cov - run tests with coverage report.
	@echo clean - remove venv directory.

$(VENV_TIMESTAMP): pyproject.toml
	@echo Building $(VENV)
	python3 -m venv $(VENV)
	$(PIP) install -e .
	$(PIP) install .[dev]
	touch $@

$(BLACK): $(VENV_TIMESTAMP)
$(PYLINT): $(VENV_TIMESTAMP)
$(REUSE): $(VENV_TIMESTAMP)
$(PYTEST): $(VENV_TIMESTAMP)
$(PYTEST): $(VENV_TIMESTAMP)

fmt: $(BLACK)
	$(BLACK) $(SRC) $(SRC_TEST)

lint: $(PYLINT)
	$(PYLINT) $(SRC)

reuse: $(REUSE)
	$(REUSE) lint

test: $(PYTEST)
	$(PYTEST) tests/ -v

test-cov: $(PYTEST)
	$(PYTEST) tests/ -v --cov=. --cov-report=term --cov-report=html

clean:
	@rm -rf $(VENV) 2>/dev/null
	@rm -rf .pytest_cache htmlcov .coverage 2>/dev/null

.PHONY: clean fmt lint reuse test test-cov

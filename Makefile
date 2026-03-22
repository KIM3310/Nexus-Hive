.SHELLFLAGS := -eu -o pipefail -c
PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_STAMP := $(VENV)/.installed-dev

.PHONY: install lint test verify run

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)

$(VENV_STAMP): pyproject.toml requirements.txt
	@if [ ! -x "$(VENV_PYTHON)" ] || ! $(VENV_PYTHON) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then \
		rm -rf $(VENV); \
		$(PYTHON) -m venv $(VENV); \
	fi
	@if ! $(VENV_PYTHON) -m pip --version >/dev/null 2>&1; then \
		$(VENV_PYTHON) -m ensurepip --upgrade; \
	fi
	$(VENV_PYTHON) -m pip install -U pip
	$(VENV_PYTHON) -m pip install -e ".[dev]"
	touch $(VENV_STAMP)

install: $(VENV_STAMP)

lint: install
	$(VENV_PYTHON) -m ruff check .

test: install
	$(VENV_PYTHON) -m pytest -q

verify: lint test

run: install
	$(VENV_PYTHON) -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

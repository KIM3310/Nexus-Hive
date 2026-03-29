.SHELLFLAGS := -eu -o pipefail -c
BOOTSTRAP_PYTHON ?= python3.11
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_STAMP := $(VENV)/.installed-dev

.PHONY: install lint test smoke verify run

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)

$(VENV_STAMP): pyproject.toml requirements.txt
	@if [ ! -x "$(VENV_PYTHON)" ] || ! $(VENV_PYTHON) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then \
		rm -rf $(VENV); \
		$(BOOTSTRAP_PYTHON) -m venv $(VENV); \
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

smoke: install
	@set -eu; \
	PORT=8098; \
	LOG=/tmp/nexus-hive-smoke.log; \
	$(VENV_PYTHON) -m uvicorn main:app --host 127.0.0.1 --port $$PORT >$$LOG 2>&1 & \
	pid=$$!; \
	trap 'kill $$pid >/dev/null 2>&1 || true' EXIT INT TERM; \
	for _ in 1 2 3 4 5 6 7 8 9 10; do \
		if curl -fsS "http://127.0.0.1:$$PORT/health" >/dev/null 2>&1; then \
			break; \
		fi; \
		sleep 1; \
	done; \
	curl -fsS "http://127.0.0.1:$$PORT/health" >/dev/null; \
	curl -fsS "http://127.0.0.1:$$PORT/api/runtime/brief" >/dev/null; \
	curl -fsS "http://127.0.0.1:$$PORT/api/runtime/warehouse-brief" >/dev/null; \
	echo "smoke ok: http://127.0.0.1:$$PORT"

verify: lint test smoke

run: install
	$(VENV_PYTHON) -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

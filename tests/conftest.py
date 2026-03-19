"""
Pytest configuration for Nexus-Hive test suite.

Provides shared fixtures and test ordering to prevent cross-test
audit state contamination.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List

import pytest


# The audit path used by test_runtime_endpoints.py
_RUNTIME_TEST_AUDIT_PATH = (
    Path(tempfile.gettempdir()) / "nexus_hive_query_audit_test.jsonl"
)


@pytest.fixture(autouse=True)
def _clean_shared_audit_state(request: pytest.FixtureRequest) -> None:
    """Clean the shared audit file before runtime_endpoints tests.

    This prevents audit entries written by other test modules from
    leaking into runtime endpoint assertions that expect a clean state.
    """
    if "test_runtime_endpoints" in str(request.fspath):
        import config as _cfg
        audit_path = _cfg.AUDIT_LOG_PATH
        if audit_path.exists():
            audit_path.unlink()

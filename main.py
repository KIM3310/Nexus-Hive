"""Nexus-Hive Agent API - Thin FastAPI entrypoint.

Delegates to: config, policy/, graph/, services/, routes/, middleware.
"""
import os, sys
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from logging_config import configure_logging
configure_logging()

from config import AUDIT_LOG_PATH  # noqa: F401 (monkeypatched in tests)
import config as _config_module
from policy.engine import evaluate_sql_policy  # noqa: F401
from graph import ask_ollama, build_graph, translator_node, executor_node, visualizer_node  # noqa: F401
from services.build_helpers import build_runtime_brief, build_runtime_meta  # noqa: F401
from policy.governance import build_warehouse_brief  # noqa: F401
from policy.audit import write_query_audit_snapshot as _write_query_audit_snapshot
from services.openai_helpers import call_openai_moderation, call_openai_reviewer_demo_summary  # noqa: F401
from security import apply_operator_session
from middleware import session_and_logging_middleware
from routes import ALL_ROUTERS, configure_ask

def _sync_audit_log_path() -> None:
    """Propagate any monkeypatched AUDIT_LOG_PATH back to config."""
    current = globals().get("AUDIT_LOG_PATH")
    if current is not None and current != _config_module.AUDIT_LOG_PATH:
        _config_module.AUDIT_LOG_PATH = current

def write_query_audit_snapshot(**kwargs):
    _sync_audit_log_path()
    return _write_query_audit_snapshot(**kwargs)

graph = build_graph()
configure_ask(graph, write_query_audit_snapshot)

app = FastAPI(
    title="Nexus-Hive Agent API",
    description="Multi-agent NL-to-SQL BI copilot with governed analytics, audit trails, and multi-warehouse support.",
    version="0.2.0", docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "https://nexus-hive.pages.dev"],
    allow_origin_regex=r"^https://([a-z0-9-]+\.)?nexus-hive\.pages\.dev$",
    allow_credentials=False, allow_methods=["*"], allow_headers=["*"],
)
# Store lazy resolvers on app.state so the reviewer-demo route reads the
# correct module-level references even when main.py is loaded multiple times.
_g = globals()
app.state._resolve_moderation = lambda: _g["call_openai_moderation"]
app.state._resolve_summary = lambda: _g["call_openai_reviewer_demo_summary"]

@app.middleware("http")
async def _middleware(request: Request, call_next):
    return await session_and_logging_middleware(request, call_next, _sync_audit_log_path, apply_operator_session)

for router in ALL_ROUTERS:
    app.include_router(router)

frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
os.makedirs(frontend_path, exist_ok=True)
app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

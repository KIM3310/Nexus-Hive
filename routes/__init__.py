"""
FastAPI route modules for Nexus-Hive.
"""

from routes.health_meta import router as health_meta_router
from routes.warehouse import router as warehouse_router
from routes.auth import router as auth_router
from routes.schemas import router as schemas_router
from routes.policy import router as policy_router
from routes.query_audit import router as query_audit_router
from routes.reviewer_demo import router as reviewer_demo_router
from routes.ask import router as ask_router, configure as configure_ask

ALL_ROUTERS = [
    health_meta_router,
    warehouse_router,
    auth_router,
    schemas_router,
    policy_router,
    query_audit_router,
    reviewer_demo_router,
    ask_router,
]

__all__ = ["ALL_ROUTERS", "configure_ask"]

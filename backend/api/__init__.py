"""HTTP routes. All business logic lives in the packages these import."""

from backend.api import (
    admin_routes,
    auth_routes,
    chat_routes,
    classroom_routes,
    dashboard_routes,
    diagnostic_routes,
    health,
    marks_routes,
    qa_routes,
    session_report_routes,
    socratic_routes,
)

ROUTERS = [
    health.router,
    auth_routes.router,
    admin_routes.router,
    classroom_routes.router,
    session_report_routes.router,
    chat_routes.router,
    qa_routes.router,
    socratic_routes.router,
    diagnostic_routes.router,
    dashboard_routes.router,
    marks_routes.router,
]

__all__ = ["ROUTERS"]


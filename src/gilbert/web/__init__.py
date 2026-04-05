"""Gilbert web server — FastAPI app factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from gilbert.core.app import Gilbert

_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))


def create_app(gilbert: Gilbert) -> FastAPI:
    """Create the FastAPI application wired to a running Gilbert instance."""
    app = FastAPI(title="Gilbert", docs_url=None, redoc_url=None)

    # Store gilbert instance for route access
    app.state.gilbert = gilbert

    # Auth middleware (works even when auth is disabled — falls through to SYSTEM)
    from gilbert.web.auth import AuthMiddleware

    app.add_middleware(AuthMiddleware)

    # Static files
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    # Routes
    from gilbert.web.routes.auth import router as auth_router
    from gilbert.web.routes.dashboard import router as dashboard_router
    from gilbert.web.routes.system import router as system_router

    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(system_router)

    return app

"""Gilbert web server — FastAPI app factory."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from gilbert.core.app import Gilbert

_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))


class NoCacheHTMLMiddleware(BaseHTTPMiddleware):
    """Prevent browsers from caching HTML responses."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


def create_app(gilbert: Gilbert) -> FastAPI:
    """Create the FastAPI application wired to a running Gilbert instance."""
    app = FastAPI(title="Gilbert", docs_url=None, redoc_url=None)

    # Store gilbert instance for route access
    app.state.gilbert = gilbert

    # Auth middleware (works even when auth is disabled — falls through to SYSTEM)
    from gilbert.web.auth import AuthMiddleware

    app.add_middleware(AuthMiddleware)
    app.add_middleware(NoCacheHTMLMiddleware)

    # Static files
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    # Serve generated output files (TTS audio, etc.) so speakers can fetch them
    from gilbert.core.output import OUTPUT_DIR

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")

    # Routes
    from gilbert.web.routes.auth import router as auth_router
    from gilbert.web.routes.chat import router as chat_router
    from gilbert.web.routes.dashboard import router as dashboard_router
    from gilbert.web.routes.entities import router as entities_router
    from gilbert.web.routes.roles import router as roles_router
    from gilbert.web.routes.system import router as system_router

    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(dashboard_router)
    app.include_router(entities_router)
    app.include_router(roles_router)
    app.include_router(system_router)

    return app

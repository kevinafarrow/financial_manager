"""FastAPI app factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .alerts import send_boot_notice
from .config import Config
from .state import AppState

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(state: AppState | None = None) -> FastAPI:
    appstate = state or AppState(Config())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if appstate.vault.initialized and not appstate.unlocked:
            send_boot_notice(appstate.config, http_client=appstate.http_client)
        yield
        if appstate.unlocked:
            appstate.lock()

    app = FastAPI(title="Financial Manager", lifespan=lifespan)
    app.state.appstate = appstate

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # Cookie-auth CSRF defense: mutating API calls must carry a custom header,
        # which cross-site form posts cannot add.
        if (request.url.path.startswith("/api/")
                and request.method in MUTATING_METHODS
                and request.headers.get("x-requested-with") != "XMLHttpRequest"):
            return JSONResponse({"detail": "missing X-Requested-With header"}, status_code=403)
        return await call_next(request)

    from .api import (accounts, auth_routes, budgets_api, categories, chat_api,
                      imports, queue, receipts_api, recurring_api, reports_api,
                      rules, settings_api, system, transactions, transfers_api)

    app.include_router(system.router)
    app.include_router(auth_routes.router)
    app.include_router(accounts.router)
    app.include_router(categories.router)
    app.include_router(imports.router)
    app.include_router(queue.router)
    app.include_router(rules.router)
    app.include_router(transfers_api.router)
    app.include_router(recurring_api.router)
    app.include_router(transactions.router)
    app.include_router(budgets_api.router)
    app.include_router(budgets_api.goals_router)
    app.include_router(reports_api.router)
    app.include_router(receipts_api.router)
    app.include_router(settings_api.router)
    app.include_router(chat_api.router)

    if STATIC_DIR.exists():  # serve the built frontend
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            candidate = STATIC_DIR / full_path
            if full_path and candidate.is_file() and candidate.resolve().is_relative_to(STATIC_DIR):
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")

    return app

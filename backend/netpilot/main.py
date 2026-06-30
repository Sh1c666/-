"""FastAPI application entrypoint.

Serves the JSON API under ``/api`` and, when the frontend has been built
(``frontend/dist``), serves the single-page app at ``/`` with SPA fallback so
deep links work. In dev, run the Vite dev server (``npm run dev``) separately
and it will proxy ``/api`` here.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.routes import router
from .config import FRONTEND_DIST, startup_settings

app = FastAPI(
    title="NetPilot",
    description="AI Network Troubleshooting Copilot — LLM-guided, layer-by-layer network diagnosis.",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=startup_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

INDEX_HTML = FRONTEND_DIST / "index.html"

if INDEX_HTML.exists():
    # Serve hashed Vite assets directly.
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str) -> FileResponse:
        # Don't shadow the API (it's registered earlier, but be safe).
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(INDEX_HTML))
else:
    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "name": "NetPilot",
            "version": __version__,
            "message": (
                "Backend is up. Frontend not built yet — run "
                "`cd frontend && npm install && npm run build`, or use `npm run dev`."
            ),
            "docs": "/docs",
        }


def main() -> None:
    """Run with uvicorn using configured host/port (``python -m netpilot``)."""
    import uvicorn

    uvicorn.run(
        "netpilot.main:app",
        host=startup_settings.host,
        port=startup_settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()

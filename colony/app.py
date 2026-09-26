"""Colony Local — FastAPI application entry point."""
import logging

from fastapi import FastAPI

from .api import router
from .config import ensure_env_file, get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Colony Local",
        description="Multi-AI assistant with shared context — runs entirely on your machine.",
        version="0.1.0",
    )

    # No CORS: the UI is served from this same origin, so other local sites
    # can't read or change your settings/key through this API.
    app.include_router(router, prefix="/api")

    from pathlib import Path
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    class RevalidatedStaticFiles(StaticFiles):
        """Tell the browser to re-check every file on each load (a cheap 304 on localhost), so a
        page never runs old JS/CSS after the app is updated."""

        def file_response(self, *args, **kwargs):
            response = super().file_response(*args, **kwargs)
            response.headers["Cache-Control"] = "no-cache"
            return response

    web_dir = Path(__file__).resolve().parent / "web"
    app.mount("/static", RevalidatedStaticFiles(directory=str(web_dir)), name="static")

    @app.get("/")
    async def serve_index():
        index_file = web_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file), headers={"Cache-Control": "no-cache"})
        return {"status": "ok", "message": "Colony Local API is running."}

    @app.get("/favicon.ico")
    async def favicon():
        from fastapi.responses import Response
        return Response(status_code=204)


    @app.on_event("startup")

    async def startup() -> None:
        s = get_settings()
        if not s.openrouter_api_key and not s.openai_api_key:
            logger.warning(
                "⚠️  No API key found. Set OPENROUTER_API_KEY in %s",
                s.data_dir / ".env",
            )
        else:
            logger.info("✅  Colony Local ready — provider: %s",
                        "OpenRouter" if s.openrouter_api_key else "OpenAI")
        logger.info("📁  Data directory: %s", s.data_dir)
        from .core.workspaces import list_workspaces
        for workspace in list_workspaces():
            logger.info("🗂  Workspace %s: %s", workspace.name,
                        " | ".join(f"{r.name}={r.model}" for r in workspace.roles))

    return app


app = create_app()


def run(reload: bool = False) -> None:
    """Called by `colony` CLI command and `python -m colony.app`.
    reload=True restarts the server whenever the code changes (development only)."""
    from pathlib import Path

    import uvicorn
    ensure_env_file()
    s = get_settings()
    logger.info("🚀  Starting Colony Local on http://%s:%s", s.host, s.port)
    uvicorn.run(
        "colony.app:app",
        host=s.host,
        port=s.port,
        reload=reload,
        reload_dirs=[str(Path(__file__).resolve().parent)] if reload else None,
        log_level="info",
    )


if __name__ == "__main__":
    run()

"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.release_routes import router as release_router
from app.config import get_settings
from app.logging_config import setup_logging


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import logging

    # Load settings from .env on startup (get_settings reads .env on each call).
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    jira_ok = bool(settings.jira_email and settings.jira_api_token.get_secret_value())
    github_ok = bool(settings.github_personal_access_token.get_secret_value())
    logger.info("[CONFIG] Jira MCP credentials configured: %s", jira_ok)
    logger.info("[CONFIG] GitHub MCP token configured: %s", github_ok)
    logger.info("[CONFIG] LLM enabled: %s", settings.llm_enabled)
    if settings.llm_enabled:
        logger.info("[CONFIG] LLM provider: %s, model: %s", settings.llm_provider, settings.llm_model)
    else:
        logger.warning(
            "[CONFIG] LLM not configured – set LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_BASE_URL"
        )
    logger.info("[CONFIG] Release database: %s", settings.release_db_path)
    if not jira_ok:
        logger.warning(
            "[CONFIG] JIRA_EMAIL / JIRA_API_TOKEN missing – Jira validation will fail"
        )
    logger.info("Backend ready at http://0.0.0.0:8000 — waiting for requests")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Release Automation Backend",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(release_router)
    return app


app = create_app()

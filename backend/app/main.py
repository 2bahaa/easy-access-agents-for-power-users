"""FastAPI application factory. Run with: uv run uvicorn app.main:app --reload"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_error_handlers
from app.api.routers import agents, conversations, health, providers, runs, skills, tools
from app.config import Settings, get_settings
from app.db.session import create_engine, create_sessionmaker
from app.runtime.providers.registry import ProviderRegistry, build_default_providers
from app.services.skill_service import seed_builtin_skills
from app.tools.registry import ToolRegistry, build_default_registry
from app.worker.run_worker import RunWorker

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    provider_registry: ProviderRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
) -> FastAPI:
    """Build the app. Registries can be injected (tests use a fake provider)."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        app.state.sessionmaker = create_sessionmaker(engine)
        try:
            async with app.state.sessionmaker() as session:
                await seed_builtin_skills(session, settings.skills_dir)
        except Exception:
            # Keep serving so /api/health can report the problem.
            logger.exception("Startup DB tasks failed (is the database migrated?)")
        worker: RunWorker | None = None
        if settings.run_worker_embedded:
            worker = RunWorker(
                settings,
                app.state.sessionmaker,
                app.state.provider_registry,
                app.state.tool_registry,
            )
            worker.start()
        app.state.run_worker = worker
        yield
        if worker is not None:
            await worker.stop(cancel_runs=True)
        await engine.dispose()

    app = FastAPI(title="Easy Access Agents", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.tool_registry = tool_registry or build_default_registry()
    app.state.provider_registry = provider_registry or build_default_providers(
        settings.ollama_base_url
    )
    app.state.run_worker = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    for module in (health, agents, skills, tools, providers, conversations, runs):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()

"""FastAPI application factory. Run with: uv run uvicorn app.main:app --reload"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_error_handlers
from app.api.routers import agents, health, skills, tools
from app.config import Settings, get_settings
from app.db.session import create_engine, create_sessionmaker
from app.services.skill_service import seed_builtin_skills
from app.tools.registry import build_default_registry

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
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
            logger.exception("Skill seeding failed (is the database migrated?)")
        yield
        await engine.dispose()

    app = FastAPI(title="Easy Access Agents", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.tool_registry = build_default_registry()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    for router in (health.router, agents.router, skills.router, tools.router):
        app.include_router(router, prefix="/api")
    return app


app = create_app()

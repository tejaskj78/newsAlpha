import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router
from app.config import get_settings
from app.db import init_engine, is_initialized
from app.jobs import Jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not is_initialized():
        init_engine(settings.database_url)
    if not hasattr(app.state, "jobs"):
        app.state.jobs = Jobs(settings)
    scheduler = None
    if settings.embedded_worker:
        from app.worker import start_background

        scheduler = start_background(app.state.jobs)
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


def create_app(jobs: Jobs | None = None) -> FastAPI:
    app = FastAPI(title="NewsAlpha", version=__version__, lifespan=lifespan)
    if jobs is not None:
        app.state.jobs = jobs
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()

"""
Gativa Backend — FastAPI application entry point
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import connect_to_mongo, close_mongo_connection
from app.core.sqlite_store import init_sqlite_db
from app.api import health, analyses, simulations


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic."""
    init_sqlite_db()
    await connect_to_mongo()
    yield
    await close_mongo_connection()


app = FastAPI(
    title="Gativa API",
    description="Smart Traffic Analysis and Infrastructure Recommendation API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, prefix="/api")
app.include_router(analyses.router, prefix="/api")
app.include_router(simulations.router, prefix="/api")

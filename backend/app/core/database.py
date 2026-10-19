"""MongoDB connection management using motor (async driver)."""
import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import get_settings
from app.core.sqlite_store import init_sqlite_db

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_to_mongo() -> None:
    global _client, _db
    # Always ensure local durable SQLite store is ready
    init_sqlite_db()
    settings = get_settings()
    if not settings.mongodb_uri or not settings.mongodb_uri.strip():
        logger.warning(
            "MONGODB_URI not configured. Operating in SQLite durable local persistence mode (backend/data/gativa.db)."
        )
        return

    try:
        logger.info("Attempting MongoDB connection...")
        _client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=2000)
        _db = _client[settings.database_name]
        await _client.admin.command("ping")
        logger.info("MongoDB connection established (database: %s)", settings.database_name)
    except Exception as exc:
        _client = None
        _db = None
        logger.warning(
            "MongoDB connection failed: %s. Operating in in-memory session persistence mode.",
            exc,
        )


async def close_mongo_connection() -> None:
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB connection closed")



def is_mongodb_connected() -> bool:
    return _db is not None


def get_persistence_mode() -> str:
    if is_mongodb_connected():
        return "mongodb"
    return "sqlite"


def get_database() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError(
            "Database not initialized. Ensure connect_to_mongo() was called during startup."
        )
    return _db

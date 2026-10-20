"""
SQLite persistent storage manager for Gativa.
Provides durable local persistence when an external MongoDB instance is not configured or unavailable.
Stores analysis results, traffic telemetry, engineering recommendations, and cached OSM networks in backend/data/gativa.db.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Locate database path in backend/data/gativa.db
DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DB_DIR / "gativa.db"


_db_initialized = False
_db_init_error: Optional[str] = None


def init_sqlite_db() -> None:
    """Initialize SQLite database tables and indices."""
    global _db_initialized, _db_init_error
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(DB_PATH), timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    analysis_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS traffic_flow (
                    analysis_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS recommendations (
                    analysis_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS osm_cache (
                    cache_key TEXT PRIMARY KEY,
                    osm_xml TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS congestion_summaries (
                    sim_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.commit()
            _db_initialized = True
            _db_init_error = None
            logger.info("Initialized SQLite persistent store at %s", DB_PATH)
    except Exception as exc:
        _db_initialized = False
        _db_init_error = str(exc)
        logger.error("Failed to initialize SQLite persistent store: %s", exc)


def get_sqlite_status(include_internals: bool = True) -> dict[str, Any]:
    """Return health status of the SQLite persistent storage layer."""
    global _db_initialized, _db_init_error
    if not _db_initialized and _db_init_error is None:
        init_sqlite_db()

    status_dict: dict[str, Any] = {
        "status": "healthy" if _db_initialized else "degraded",
        "initialized": _db_initialized,
        "error": _db_init_error,
    }
    if _db_init_error:
        status_dict["error_type"] = "StorageInitializationError"
        status_dict["message"] = "SQLite persistent storage is currently unavailable"
    if include_internals:
        status_dict["path"] = str(DB_PATH)
    return status_dict


def _get_connection() -> sqlite3.Connection:
    global _db_initialized, _db_init_error
    if not _db_initialized:
        init_sqlite_db()
    if not _db_initialized:
        raise RuntimeError("SQLite persistent store is unavailable")
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def save_analysis_sync(analysis_id: str, data: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    json_data = json.dumps(data)
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO analyses (analysis_id, data, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(analysis_id) DO UPDATE SET
                data = excluded.data,
                created_at = excluded.created_at;
            """,
            (analysis_id, json_data, now),
        )
        conn.commit()


def get_analysis_sync(analysis_id: str) -> Optional[dict[str, Any]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM analyses WHERE analysis_id = ?", (analysis_id,))
        row = cursor.fetchone()
        if row:
            return json.loads(row["data"])
    return None


def save_traffic_flow_sync(analysis_id: str, data: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    json_data = json.dumps(data)
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO traffic_flow (analysis_id, data, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(analysis_id) DO UPDATE SET
                data = excluded.data,
                created_at = excluded.created_at;
            """,
            (analysis_id, json_data, now),
        )
        conn.commit()


def get_traffic_flow_sync(analysis_id: str) -> Optional[dict[str, Any]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM traffic_flow WHERE analysis_id = ?", (analysis_id,))
        row = cursor.fetchone()
        if row:
            return json.loads(row["data"])
    return None


def save_recommendations_sync(analysis_id: str, data: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    json_data = json.dumps(data)
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO recommendations (analysis_id, data, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(analysis_id) DO UPDATE SET
                data = excluded.data,
                created_at = excluded.created_at;
            """,
            (analysis_id, json_data, now),
        )
        conn.commit()


def get_recommendations_sync(analysis_id: str) -> Optional[dict[str, Any]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM recommendations WHERE analysis_id = ?", (analysis_id,))
        row = cursor.fetchone()
        if row:
            return json.loads(row["data"])
    return None


def save_osm_cache_sync(cache_key: str, osm_xml: str, metadata: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(metadata)
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO osm_cache (cache_key, osm_xml, metadata, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                osm_xml = excluded.osm_xml,
                metadata = excluded.metadata,
                created_at = excluded.created_at;
            """,
            (cache_key, osm_xml, meta_json, now),
        )
        conn.commit()


def get_osm_cache_sync(cache_key: str) -> Optional[tuple[str, dict[str, Any]]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT osm_xml, metadata FROM osm_cache WHERE cache_key = ?", (cache_key,))
        row = cursor.fetchone()
        if row:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            return row["osm_xml"], metadata
    return None


def save_congestion_summary_sync(sim_id: str, data: dict[str, Any]) -> None:
    """Persist a post-simulation congestion summary keyed by simulation ID."""
    now = datetime.now(timezone.utc).isoformat()
    json_data = json.dumps(data)
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO congestion_summaries (sim_id, data, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(sim_id) DO UPDATE SET
                data = excluded.data,
                created_at = excluded.created_at;
            """,
            (sim_id, json_data, now),
        )
        conn.commit()


def get_congestion_summary_sync(sim_id: str) -> Optional[dict[str, Any]]:
    """Retrieve a stored congestion summary by simulation ID."""
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM congestion_summaries WHERE sim_id = ?", (sim_id,))
        row = cursor.fetchone()
        if row:
            return json.loads(row["data"])
    return None

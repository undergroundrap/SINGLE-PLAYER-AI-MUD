"""
vector_db.py — SQLite-backed persistence layer with in-memory LRU cache.

Previously used LanceDB (a vector database). LanceDB added lancedb, pandas,
pyarrow, numpy, and tantivy as dependencies with zero benefit — the game never
used vector search. Replaced with stdlib sqlite3: faster, zero extra deps,
trivially debuggable with any SQLite browser.

Interface is identical to the old VectorDBManager so no callers needed changes.
"""

import sqlite3
import json
import os
import time
from typing import Dict, Any, Optional


class DBManager:
    def __init__(self, db_path: str = "./data/mud.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # WAL mode: readers don't block writers, writers don't block readers
        self._conn.execute("PRAGMA journal_mode=WAL")
        # NORMAL sync: safe on crash, much faster than FULL
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # Flush any leftover WAL from a previous session on startup
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._init_tables()

        # In-memory LRU cache — checked before every DB read
        self._player_cache: Dict[str, tuple] = {}   # id -> (data, timestamp)
        self._zone_cache:   Dict[str, tuple] = {}
        self._cache_limit = 200

    # ── Schema ───────────────────────────────────────────────────────────────

    def _init_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS players (
                id         TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS zones (
                id         TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
        """)
        self._conn.commit()

    # ── Players ───────────────────────────────────────────────────────────────

    async def save_player(self, player_id: str, player_data: Dict[str, Any]):
        player_data["id"] = player_id
        now = time.time()
        self._player_cache[player_id] = (player_data, now)
        self._evict(self._player_cache)
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO players (id, data, updated_at) VALUES (?, ?, ?)",
                (player_id, json.dumps(player_data), now),
            )
            self._conn.commit()
        except Exception as e:
            print(f"DB Error saving player: {e}")

    async def get_player(self, player_id: str) -> Optional[Dict[str, Any]]:
        if player_id in self._player_cache:
            data, _ = self._player_cache[player_id]
            self._player_cache[player_id] = (data, time.time())
            return data
        try:
            row = self._conn.execute(
                "SELECT data FROM players WHERE id = ?", (player_id,)
            ).fetchone()
            if row:
                data = json.loads(row[0])
                self._player_cache[player_id] = (data, time.time())
                return data
        except Exception as e:
            print(f"DB Error getting player: {e}")
        return None

    async def delete_player(self, player_id: str) -> dict:
        """Delete a single player and all zones that belong exclusively to them."""
        player_data = await self.get_player(player_id)
        if not player_data:
            return {"deleted": False, "error": "Player not found"}

        zone_ids = set(player_data.get("visited_zone_ids") or [])
        if player_data.get("current_zone_id"):
            zone_ids.add(player_data["current_zone_id"])

        self._player_cache.pop(player_id, None)

        try:
            self._conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
            deleted_zones = 0
            if zone_ids:
                placeholders = ",".join("?" * len(zone_ids))
                deleted_zones = self._conn.execute(
                    f"SELECT COUNT(*) FROM zones WHERE id IN ({placeholders})",
                    list(zone_ids),
                ).fetchone()[0]
                self._conn.execute(
                    f"DELETE FROM zones WHERE id IN ({placeholders})",
                    list(zone_ids),
                )
                for zid in zone_ids:
                    self._zone_cache.pop(zid, None)
            self._conn.commit()
            return {"deleted": True, "player_id": player_id, "zones_removed": deleted_zones}
        except Exception as e:
            return {"deleted": False, "error": str(e)}

    def get_all_players(self) -> list:
        """Return raw dicts for all players — used by the load-game screen."""
        try:
            rows = self._conn.execute(
                "SELECT data FROM players ORDER BY updated_at DESC"
            ).fetchall()
            return [json.loads(r[0]) for r in rows]
        except Exception as e:
            print(f"DB Error listing players: {e}")
            return []

    # ── Zones ─────────────────────────────────────────────────────────────────

    async def save_zone(self, zone_id: str, zone_data: Dict[str, Any]):
        zone_data["id"] = zone_id
        now = time.time()
        self._zone_cache[zone_id] = (zone_data, now)
        self._evict(self._zone_cache)
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO zones (id, data, updated_at) VALUES (?, ?, ?)",
                (zone_id, json.dumps(zone_data), now),
            )
            self._conn.commit()
        except Exception as e:
            print(f"DB Error saving zone: {e}")

    async def get_zone(self, zone_id: str) -> Optional[Dict[str, Any]]:
        if zone_id in self._zone_cache:
            data, _ = self._zone_cache[zone_id]
            self._zone_cache[zone_id] = (data, time.time())
            return data
        try:
            row = self._conn.execute(
                "SELECT data FROM zones WHERE id = ?", (zone_id,)
            ).fetchone()
            if row:
                data = json.loads(row[0])
                self._zone_cache[zone_id] = (data, time.time())
                return data
        except Exception as e:
            print(f"DB Error getting zone: {e}")
        return None

    # ── Admin ─────────────────────────────────────────────────────────────────

    def reset_all(self):
        """Wipe all persisted data and caches — called by the admin reset endpoint."""
        self._player_cache.clear()
        self._zone_cache.clear()
        try:
            self._conn.executescript("DELETE FROM players; DELETE FROM zones;")
            self._conn.commit()
        except Exception as e:
            print(f"DB Error on reset: {e}")

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _evict(self, cache: dict):
        """Drop the least-recently-used entry when the cache is over its limit."""
        if len(cache) > self._cache_limit:
            oldest = min(cache, key=lambda k: cache[k][1])
            del cache[oldest]


vec_db = DBManager()

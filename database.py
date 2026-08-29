"""
Capa de acceso a datos (SQLite) para el bot de quedadas.

Toda la persistencia pasa por la clase Database. Se abre y cierra una
conexión por operación (en vez de mantener una conexión global) para evitar
problemas de concurrencia entre corrutinas del bot; para el volumen de datos
de un servidor de amistades esto es más que suficiente y evita bugs sutiles.
"""
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

logger = logging.getLogger("quedadas.database")

DB_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DB_DIR / "quedadas.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    event_date TEXT NOT NULL,      -- almacenado como DD/MM/AAAA
    event_time TEXT NOT NULL,      -- almacenado como HH:MM
    creator_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active | closed | cancelled
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance (
    event_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL,          -- attending | not_attending
    responded_at TEXT NOT NULL,
    PRIMARY KEY (event_id, user_id),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_guild_status ON events(guild_id, status);
CREATE INDEX IF NOT EXISTS idx_attendance_event ON attendance(event_id);
"""


class Database:
    """Wrapper async sobre SQLite. Una instancia se crea en bot.py y se cuelga
    de `bot.db` para que cogs y vistas puedan acceder a ella."""

    def __init__(self, path: Path = DB_PATH):
        self.path = path

    async def init(self) -> None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.executescript(SCHEMA)
            await db.commit()
        logger.info(f"Base de datos inicializada en {self.path}")

    # ---------------- eventos ----------------

    async def create_event(self, *, guild_id: int, channel_id: int, name: str,
                            description: str, event_date: str, event_time: str,
                            creator_id: int) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """INSERT INTO events
                   (guild_id, channel_id, name, description, event_date, event_time,
                    creator_id, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
                (guild_id, channel_id, name, description, event_date, event_time,
                 creator_id, now),
            )
            await db.commit()
            return cursor.lastrowid

    async def set_message_id(self, event_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE events SET message_id = ? WHERE id = ?", (message_id, event_id))
            await db.commit()

    async def get_event(self, event_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM events WHERE id = ?", (event_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update_event(self, event_id: int, *, name: str, description: str,
                            event_date: str, event_time: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """UPDATE events SET name = ?, description = ?, event_date = ?, event_time = ?
                   WHERE id = ?""",
                (name, description, event_date, event_time, event_id),
            )
            await db.commit()

    async def set_event_status(self, event_id: int, status: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE events SET status = ? WHERE id = ?", (status, event_id))
            await db.commit()

    async def list_events(self, guild_id: int, statuses: Optional[list] = None,
                           limit: int = 25) -> list:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            if statuses:
                placeholders = ",".join("?" * len(statuses))
                query = (
                    f"SELECT * FROM events WHERE guild_id = ? AND status IN ({placeholders}) "
                    f"ORDER BY created_at DESC LIMIT ?"
                )
                params = (guild_id, *statuses, limit)
            else:
                query = "SELECT * FROM events WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?"
                params = (guild_id, limit)
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def list_events_for_startup(self) -> list:
        """Eventos activos o cerrados (de cualquier servidor) que necesitan que
        se vuelva a registrar su vista persistente al reiniciar el bot."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM events WHERE status IN ('active', 'closed') AND message_id IS NOT NULL"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    # ---------------- asistencia ----------------

    async def set_attendance(self, event_id: int, user_id: int, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO attendance (event_id, user_id, status, responded_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(event_id, user_id) DO UPDATE SET
                       status = excluded.status,
                       responded_at = excluded.responded_at""",
                (event_id, user_id, status, now),
            )
            await db.commit()

    async def get_attendance_counts(self, event_id: int) -> dict:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT status, COUNT(*) FROM attendance WHERE event_id = ? GROUP BY status",
                (event_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                counts = {"attending": 0, "not_attending": 0}
                for status, count in rows:
                    counts[status] = count
                return counts

    async def get_attendees(self, event_id: int, status: str) -> list:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT user_id FROM attendance WHERE event_id = ? AND status = ? ORDER BY responded_at",
                (event_id, status),
            ) as cursor:
                rows = await cursor.fetchall()
                return [r[0] for r in rows]

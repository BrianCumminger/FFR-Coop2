"""
FFR Co-op Server V2

HTTP:
    GET /version    — returns server version string

WebSocket (at /ws):
    Client → Server:
        {"type": "init", "player": str, "limit": int}
        {"type": "join", "player": str, "team": str}
        {"type": "sync", "data": str}
        {"type": "message", "message": str}

    Server → Client:
        {"type": "init_response", "team": str}
        {"type": "join_response", "data": str}
        {"type": "sync_response", "data": str, "playeritems": [str]}
        {"type": "message", "player": str, "message": str}
        {"type": "error", "error": str}
"""

import asyncio
import json
import logging
import os
import random
import sqlite3
import time

from aiohttp import web

VERSION = "2.0"
DATA_LENGTH = 27  # Number of tracked key items

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)


class GameDB:
    """SQLite-backed game state storage with 24h TTL."""

    def __init__(self, db_path="coop.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS games (
                team         TEXT PRIMARY KEY,
                players      TEXT NOT NULL,
                data         TEXT NOT NULL,
                playeritems  TEXT NOT NULL,
                player_limit INTEGER NOT NULL DEFAULT 0,
                last_active  REAL NOT NULL
            )
        """)
        self._conn.commit()

    def create_game(self, team, player, limit):
        """Create a new game. Returns True on success, False if team already exists."""
        try:
            self._conn.execute(
                "INSERT INTO games (team, players, data, playeritems, player_limit, last_active) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    team,
                    json.dumps([player]),
                    "0" * DATA_LENGTH,
                    json.dumps([""] * DATA_LENGTH),
                    limit,
                    time.time(),
                ),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_game(self, team):
        """Load a game by team number. Returns a dict or None."""
        row = self._conn.execute("SELECT * FROM games WHERE team = ?", (team,)).fetchone()
        if row is None:
            return None
        return {
            "team": row["team"],
            "players": json.loads(row["players"]),
            "data": row["data"],
            "playeritems": json.loads(row["playeritems"]),
            "player_limit": row["player_limit"],
            "last_active": row["last_active"],
        }

    def update_game(self, team, **fields):
        """Update specific fields of a game and refresh last_active."""
        if not fields:
            return
        # Serialize lists to JSON for storage
        for key in ("players", "playeritems"):
            if key in fields and isinstance(fields[key], list):
                fields[key] = json.dumps(fields[key])
        fields["last_active"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [team]
        self._conn.execute(f"UPDATE games SET {set_clause} WHERE team = ?", values)
        self._conn.commit()

    def team_exists(self, team):
        """Check if a team number is already in use."""
        row = self._conn.execute("SELECT 1 FROM games WHERE team = ?", (team,)).fetchone()
        return row is not None

    def cleanup(self, max_age_seconds=86400):
        """Delete games inactive for longer than max_age_seconds."""
        cutoff = time.time() - max_age_seconds
        cursor = self._conn.execute("DELETE FROM games WHERE last_active < ?", (cutoff,))
        self._conn.commit()
        if cursor.rowcount > 0:
            log.info("Cleaned up %d stale game(s)", cursor.rowcount)


class CoopServer:
    """WebSocket + HTTP server for FFR Co-op."""

    def __init__(self, db_path="coop.db"):
        self.db = GameDB(db_path)
        # Maps WebSocket connection → (team, player)
        self.connections: dict[web.WebSocketResponse, tuple[str, str]] = {}

    # ── HTTP ──────────────────────────────────────────────

    async def handle_version(self, request):
        return web.Response(text=VERSION)

    # ── WebSocket ─────────────────────────────────────────

    async def handle_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        log.info("WebSocket connection opened")

        try:
            async for raw_msg in ws:
                if raw_msg.type == web.WSMsgType.TEXT:
                    try:
                        msg = json.loads(raw_msg.data)
                    except json.JSONDecodeError:
                        await self._send(ws, {"type": "error", "error": "Invalid JSON"})
                        continue

                    msg_type = msg.get("type")
                    handler = {
                        "init": self._handle_init,
                        "join": self._handle_join,
                        "sync": self._handle_sync,
                        "message": self._handle_message,
                    }.get(msg_type)

                    if handler:
                        await handler(ws, msg)
                    else:
                        await self._send(ws, {"type": "error", "error": f"Unknown message type: {msg_type}"})

                elif raw_msg.type == web.WSMsgType.ERROR:
                    log.error("WebSocket error: %s", ws.exception())
        finally:
            self.connections.pop(ws, None)
            log.info("WebSocket connection closed")

        return ws

    async def _handle_init(self, ws, msg):
        player = msg.get("player", "").strip()
        limit = msg.get("limit", 0)

        if not player:
            await self._send(ws, {"type": "error", "error": "Player name is required"})
            return

        # Generate a unique 4-digit team number
        random.seed()
        team = None
        for _ in range(10000):
            candidate = str(random.randint(1000, 9999))
            if self.db.create_game(candidate, player, limit):
                team = candidate
                break

        if team is None:
            await self._send(ws, {"type": "error", "error": "Could not generate a team number"})
            return

        self.connections[ws] = (team, player)
        log.info("Team %s created by %s (limit=%s)", team, player, limit)
        await self._send(ws, {"type": "init_response", "team": team})

    async def _handle_join(self, ws, msg):
        player = msg.get("player", "").strip()
        team = msg.get("team", "").strip()

        if not player or not team:
            await self._send(ws, {"type": "error", "error": "Player name and team are required"})
            return

        game = self.db.get_game(team)
        if game is None:
            await self._send(ws, {"type": "error", "error": "Game does not exist"})
            return

        players = game["players"]
        limit = game["player_limit"]

        if player not in players:
            if limit > 0 and len(players) >= limit:
                await self._send(ws, {"type": "error", "error": "Game is currently full"})
                return
            players.append(player)
            self.db.update_game(team, players=players)

        self.connections[ws] = (team, player)
        log.info("Player %s joined team %s", player, team)
        await self._send(ws, {"type": "join_response", "data": game["data"]})

    async def _handle_sync(self, ws, msg):
        conn_info = self.connections.get(ws)
        if conn_info is None:
            await self._send(ws, {"type": "error", "error": "Not connected to a game"})
            return

        team, player = conn_info
        data = msg.get("data", "")

        game = self.db.get_game(team)
        if game is None:
            await self._send(ws, {"type": "error", "error": "Game does not exist"})
            return

        if len(data) != len(game["data"]):
            await self._send(ws, {"type": "error", "error": "Data is malformed"})
            return

        # Merge item data (OR logic)
        server_data = game["data"]
        playeritems = game["playeritems"]
        new_data = []
        for i in range(len(data)):
            if data[i] == "1" or server_data[i] == "1":
                new_data.append("1")
                # Track who found a newly discovered item
                if server_data[i] == "0":
                    playeritems[i] = player
            else:
                new_data.append("0")

        merged = "".join(new_data)
        self.db.update_game(team, data=merged, playeritems=playeritems)

        await self._send(ws, {
            "type": "sync_response",
            "data": merged,
            "playeritems": playeritems,
        })

    async def _handle_message(self, ws, msg):
        conn_info = self.connections.get(ws)
        if conn_info is None:
            await self._send(ws, {"type": "error", "error": "Not connected to a game"})
            return

        team, player = conn_info
        message = msg.get("message", "")

        if not message:
            return

        log.info("[Team %s] %s: %s", team, player, message)
        await self._broadcast_to_team(team, {
            "type": "message",
            "player": player,
            "message": message,
        }, exclude_ws=ws)

    # ── Helpers ───────────────────────────────────────────

    async def _send(self, ws, data):
        """Send a JSON message to a single WebSocket."""
        try:
            await ws.send_json(data)
        except ConnectionResetError:
            pass

    async def _broadcast_to_team(self, team, data, exclude_ws=None):
        """Send a JSON message to all connected players on a team."""
        for conn_ws, (conn_team, _) in list(self.connections.items()):
            if conn_team == team and conn_ws is not exclude_ws:
                await self._send(conn_ws, data)

    async def _cleanup_loop(self, app):
        """Background task that removes stale games every 10 minutes."""
        try:
            while True:
                await asyncio.sleep(600)
                self.db.cleanup()
        except asyncio.CancelledError:
            pass

    # ── App setup ─────────────────────────────────────────

    def create_app(self):
        app = web.Application()
        app.router.add_get("/version", self.handle_version)
        app.router.add_get("/ws", self.handle_ws)
        app.on_startup.append(self._start_cleanup)
        app.on_cleanup.append(self._stop_cleanup)
        return app

    async def _start_cleanup(self, app):
        app["cleanup_task"] = asyncio.create_task(self._cleanup_loop(app))

    async def _stop_cleanup(self, app):
        app["cleanup_task"].cancel()
        await app["cleanup_task"]


def main():
    host = os.environ.get("SERVER_HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("SERVER_PORT", "5555"))
    except ValueError:
        port = 5555
    db_path = os.environ.get("DB_PATH", "coop.db")

    server = CoopServer(db_path=db_path)
    app = server.create_app()

    log.info("Starting FFR Co-op Server V%s on %s:%d", VERSION, host, port)
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    main()

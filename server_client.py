import urllib.request
import urllib.parse
import json
import logging
import threading
import asyncio

try:
    import websockets
except ImportError:
    websockets = None

class BaseServerClient:
    def __init__(self, server, player, team=None, log_callback=None):
        self.server = server
        self.player = player
        self.team = team
        self.log_callback = log_callback

    def _log(self, message):
        if self.log_callback:
            self.log_callback(message)
        else:
            logging.info(message)

    def initialize_team(self, limit):
        raise NotImplementedError

    def join_team(self):
        raise NotImplementedError

    def sync_with_server(self, data_str):
        raise NotImplementedError

    def send_message(self, message):
        """Send a chat message to teammates. No-op on V1."""
        pass


class ServerClientV1(BaseServerClient):
    def initialize_team(self, limit):
        url = f"http://{self.server}/init?player={urllib.parse.quote(self.player)}&limit={limit}"
        self._log(f"Initializing team...")
        try:
            with urllib.request.urlopen(url) as response:
                self.team = response.read().decode('utf-8').strip()
                self._log(f"Successfully created team {self.team}")
        except Exception as e:
            raise ConnectionError(str(e))

    def join_team(self):
        url = f"http://{self.server}/join?team={urllib.parse.quote(self.team)}&player={urllib.parse.quote(self.player)}"
        self._log(f"Joining team {self.team}...")
        try:
            with urllib.request.urlopen(url) as response:
                res = response.read().decode('utf-8').strip()
                if "Error" in res:
                    raise ConnectionError(res)
                self._log(f"Successfully joined team {self.team}")
        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(str(e))

    def sync_with_server(self, data_str):
        url = f"http://{self.server}/coop?team={urllib.parse.quote(self.team)}&player={urllib.parse.quote(self.player)}&data={data_str}"
        try:
            with urllib.request.urlopen(url) as response:
                res_str = response.read().decode('utf-8').strip()
                # Server response is JSON {"data": "10010...", "messages": [], "playeritems": []}
                return json.loads(res_str)
        except Exception as e:
            logging.error(f"Error syncing with server: {e}")
            return None


class ServerClientV2(BaseServerClient):
    """WebSocket-based client for V2 servers."""

    def __init__(self, server, player, team=None, log_callback=None, message_callback=None):
        super().__init__(server, player, team, log_callback)
        self.message_callback = message_callback
        self._ws = None
        self._loop = None
        self._thread = None
        self._connected = threading.Event()
        # For request/response pattern: the caller sets _pending_type, sends a
        # message, then waits on _response_event. The receiver loop sets
        # _response_data and signals the event when a matching response arrives.
        self._pending_type = None
        self._response_data = None
        self._response_event = threading.Event()

    # ── Connection lifecycle ──────────────────────────────

    def connect(self):
        """Establish WebSocket connection and start receiver thread."""
        if websockets is None:
            raise ImportError("The 'websockets' package is required for V2 server connections. "
                              "Install it with: pip install websockets")
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()
        if not self._connected.wait(timeout=10):
            raise ConnectionError("Timed out connecting to server via WebSocket")

    def _run_event_loop(self):
        """Background thread: create an event loop and run the receiver."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._receiver_loop())
        except Exception as e:
            self._log(f"WebSocket connection error: {e}")
        finally:
            self._loop.close()

    async def _receiver_loop(self):
        """Connect to the server and listen for messages."""
        uri = f"ws://{self.server}/ws"
        try:
            async with websockets.connect(uri) as ws:
                self._ws = ws
                self._connected.set()
                self._log("WebSocket connection established")

                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("type")

                    # Check if this is a response to a pending request
                    if self._pending_type and msg_type == self._pending_type:
                        self._response_data = msg
                        self._response_event.set()
                    elif msg_type == "message":
                        # Server-pushed message — deliver via callback
                        if self.message_callback:
                            player = msg.get("player", "")
                            message = msg.get("message", "")
                            self.message_callback(player, message)
                    elif msg_type == "error":
                        error = msg.get("error", "Unknown error")
                        self._log(f"Server error: {error}")
                        # If we're waiting for a response, unblock with the error
                        if self._pending_type:
                            self._response_data = msg
                            self._response_event.set()
        except Exception as e:
            self._log(f"WebSocket disconnected: {e}")
            self._connected.clear()

    def _send_and_wait(self, msg, expected_response_type, timeout=10):
        """Send a JSON message and block until the expected response arrives."""
        self._response_event.clear()
        self._response_data = None
        self._pending_type = expected_response_type

        future = asyncio.run_coroutine_threadsafe(
            self._ws.send(json.dumps(msg)), self._loop
        )
        future.result(timeout=timeout)

        if not self._response_event.wait(timeout=timeout):
            self._pending_type = None
            raise ConnectionError(f"Timed out waiting for {expected_response_type}")

        self._pending_type = None
        response = self._response_data

        # Check for error responses
        if response.get("type") == "error":
            raise ConnectionError(response.get("error", "Unknown server error"))

        return response

    def _send_fire_and_forget(self, msg):
        """Send a JSON message without waiting for a response."""
        if self._ws and self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps(msg)), self._loop
            )

    # ── Public API ────────────────────────────────────────

    def initialize_team(self, limit):
        self._log("Initializing team...")
        response = self._send_and_wait(
            {"type": "init", "player": self.player, "limit": limit},
            "init_response",
        )
        self.team = response["team"]
        self._log(f"Successfully created team {self.team}")

    def join_team(self):
        self._log(f"Joining team {self.team}...")
        response = self._send_and_wait(
            {"type": "join", "player": self.player, "team": self.team},
            "join_response",
        )
        self._log(f"Successfully joined team {self.team}")

    def sync_with_server(self, data_str):
        try:
            response = self._send_and_wait(
                {"type": "sync", "data": data_str},
                "sync_response",
            )
            return {
                "data": response.get("data", ""),
                "playeritems": response.get("playeritems", []),
                "messages": [],  # V2 messages arrive via push, not polling
            }
        except Exception as e:
            logging.error(f"Error syncing with server: {e}")
            return None

    def send_message(self, message):
        """Broadcast a message to all teammates."""
        self._send_fire_and_forget({"type": "message", "message": message})

    def disconnect(self):
        """Close the WebSocket connection."""
        if self._ws and self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)

import urllib.request
import urllib.parse
import json
import logging

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

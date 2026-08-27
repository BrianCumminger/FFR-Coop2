import configparser
import re
import time
import urllib.request
import urllib.parse
import json
import base64
import logging
from bizhawk_client import BizhawkClient
from itemlocationdata import LOCATIONS, ITEMS
from server_client import ServerClientV1, ServerClientV2
import gui

VERSION = "2.0-b6"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

KEYITEM_ORDER = [
    "Lute", "Crown", "Crystal", "Herb", "Key", "TNT", "Adamant", "Slab", "Ruby",
    "Rod", "Floater", "Chime", "Tail", "Cube", "Bottle", "Oxyale", "Ship", "Canoe",
    "Airship", "Bridge", "Canal", "SlabTranslation", "EarthOrb", "FireOrb", "WaterOrb", "AirOrb", "EndGame"
]

# Shard Hunt detection rules: (threshold_version, address, expected_value)
# Listed in descending order; the first entry where detected_version >= threshold wins.
SHARDHUNT_CHECKS = [
    ((4, 9, 8), 0x7BDFE, 0x53),   # 4.9.8 writes mode explicitly
    ((4, 8, 1), 0x48F61, 0x1C),   # 4.8.1 moved the shard icon
    ((4, 8, 0), 0x37761, 0x1C),   # 4.8.0 and earlier (default)
]

class FFRGameInterface:
    def __init__(self, bizhawk_client, log_callback=None):
        self.bizhawk = bizhawk_client
        self.log_callback = log_callback
        
        self.shardhuntmode = False
        self.chaos_defeated = False
        self.item_locations = {}
        
        config = configparser.ConfigParser()
        config.read('config.ini')
        self.show_item_locations = config.getboolean('Settings', 'showitemlocations', fallback=False)

    def _log(self, message):
        if self.log_callback:
            self.log_callback(message)
        else:
            logging.info(message)

    def check_shardhunt_mode(self):
        # Step 1: Read the info string at 0x7BE00 to extract the randomizer version.
        reqs = [
            {"type": "GUARD", "address": 0x3C901, "expected_data": "j6yxpK8=", "domain": "PRG ROM"},
            {"type": "READ", "address": 0x7BE00, "size": 0x200, "domain": "PRG ROM"},
        ]
        res = self.bizhawk.send_command(reqs)
        if not res or len(res) != 2 or res[0].get("type") != "GUARD_RESPONSE" or res[0].get("value") is not True:
            self._log("Failed to verify PRG ROM for Shard Hunt detection. Defaulting to standard mode.")
            return

        # Step 2: Parse the version from the info string.
        version_tuple = None
        try:
            raw_bytes = base64.b64decode(res[1]["value"])
            null_pos = raw_bytes.find(0x00)
            if null_pos != -1:
                raw_bytes = raw_bytes[:null_pos]
            info_str = raw_bytes.decode("ascii", errors="replace")

            match = re.search(r"Version:\s*(\d+)[.\-](\d+)[.\-](\d+)", info_str)
            is_beta = bool(re.search(r"Version:\s*beta", info_str, re.IGNORECASE))
            if match:
                version_tuple = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
                self._log(f"Detected randomizer version {match.group(1)}.{match.group(2)}.{match.group(3)}")
            elif is_beta:
                # Beta builds (e.g. "Version: beta-SHA") should be treated as the newest version.
                version_tuple = (9999, 9999, 9999)
                self._log("Detected beta randomizer build, assuming newest version.")
            else:
                self._log("Failed to parse version from ROM info string. Defaulting to standard detection.")
        except Exception as e:
            self._log(f"Error reading version from ROM: {e}. Defaulting to standard detection.")

        # Step 3: Select the appropriate shard hunt check based on version.
        check_addr = None
        check_val = None
        if version_tuple is not None:
            for threshold, addr, expected in SHARDHUNT_CHECKS:
                if version_tuple >= threshold:
                    check_addr = addr
                    check_val = expected
                    break

        if check_addr is None:
            # Fallback to the default (last entry in SHARDHUNT_CHECKS).
            check_addr = SHARDHUNT_CHECKS[-1][1]
            check_val = SHARDHUNT_CHECKS[-1][2]

        # Step 4: Read the shard hunt flag at the version-appropriate address.
        reqs2 = [
            {"type": "READ", "address": check_addr, "size": 1, "domain": "PRG ROM"},
        ]
        res2 = self.bizhawk.send_command(reqs2)
        if res2 and len(res2) == 1 and res2[0].get("type") == "READ_RESPONSE":
            val = base64.b64decode(res2[0]["value"])
            if val[0] == check_val:
                self.shardhuntmode = True
                self._log("Detected Shard Hunt ROM")
        else:
            self._log("Failed to read shard hunt flag. Defaulting to standard mode.")

    def read_item_locations_from_rom(self):
        if not self.show_item_locations:
            return
            
        self._log("Reading item locations from ROM...")
        
        # Consolidate reads into two blocks for chests (0x3101-0x31FF) and NPCs (0x47A00-0x47A85)
        reqs = [
            #GUARD checks for the string "Final" used in the title screen to verify the read is correct
            {"type": "GUARD", "address": 0x3C901, "expected_data": "j6yxpK8=", "domain": "PRG ROM"},
            {"type": "READ", "address": 0x3100, "size": 0x100, "domain": "PRG ROM"},
            {"type": "READ", "address": 0x47A00, "size": 0x85, "domain": "PRG ROM"}
        ]
            
        res = self.bizhawk.send_command(reqs)
        if not res or len(res) != 3:
            self._log("Failed to read item locations from ROM.")
            return
            
        block1 = base64.b64decode(res[1]["value"]) if res[1].get("type") == "READ_RESPONSE" else None
        block2 = base64.b64decode(res[2]["value"]) if res[2].get("type") == "READ_RESPONSE" else None
        
        if not block1 or not block2:
            self._log("Failed to parse item location blocks from ROM.")
            return
            
        def get_val(addr):
            if 0x3100 <= addr < 0x3200:
                return block1[addr - 0x3100]
            elif 0x47A00 <= addr < 0x47A85:
                return block2[addr - 0x47A00]
            return None
            
        item_id_to_name = {item_id: item_name for item_name, item_id in ITEMS}
        
        self.item_locations = {}
        for loc_name, addr in LOCATIONS:
            val = get_val(addr)
            if val is not None:
                item_name = item_id_to_name.get(val)
                if item_name:
                    self.item_locations[item_name] = loc_name
                    
        self._log(f"Successfully mapped {len(self.item_locations)} item locations.")

    def read_memory_blocks(self):
        # We need several blocks from System Bus
        reqs = [
            {"type": "GUARD", "address": 0x3C901, "expected_data": "j6yxpK8=", "domain": "PRG ROM"},
            {"type": "READ", "address": 0x6000, "size": 0x35, "domain": "System Bus"},  # 0x6000 - 0x6034 (Vehicles and Items)
            {"type": "READ", "address": 0x6200, "size": 0x16, "domain": "System Bus"},  # 0x6200 - 0x6215 (Event flags)
            {"type": "READ", "address": 0x6B86, "size": 1, "domain": "System Bus"},     # 0x6B86 (Chaos animation state)
            {"type": "READ", "address": 0x6C92, "size": 1, "domain": "System Bus"},     # 0x6C92 (something important? I don't remember, it has to do with Chaos battle)
            {"type": "READ", "address": 0x006A, "size": 1, "domain": "System Bus"},     # 0x006A (Battle Formation)
            {"type": "READ", "address": 0x6102, "size": 1, "domain": "System Bus"},     # 0x6102 (Party check)
            {"type": "READ", "address": 0x60FC, "size": 1, "domain": "System Bus"},     # 0x60FC (Battle Type)
        ]
        res = self.bizhawk.send_command(reqs)
        if not res or len(res) != 8:
            return None
            
        if res[0].get("type") == "GUARD_RESPONSE" and res[0].get("value") is False:
            return None
            
        data = {}
        for i in range(1, 8):
            r = res[i]
            if r.get("type") == "READ_RESPONSE":
                data[i - 1] = base64.b64decode(r["value"])
            else:
                return None
                
        # Helper to get 8-bit uint from virtual address mapping
        def u8(addr):
            if 0x6000 <= addr <= 0x6034:
                return data[0][addr - 0x6000]
            elif 0x6200 <= addr <= 0x6215:
                return data[1][addr - 0x6200]
            elif addr == 0x6B86:
                return data[2][0]
            elif addr == 0x6C92:
                return data[3][0]
            elif addr == 0x006A:
                return data[4][0]
            elif addr == 0x6102:
                return data[5][0]
            elif addr == 0x60FC:
                return data[6][0]
            return 0
            
        return u8

    def is_state_ok(self, u8):
        # Validate memory integrity. Key item slots should strictly be 0x00 or 0x01.
        # If they are higher, WRAM is not properly initialized and the read should abort.
        if u8(0x6021) > 1 or u8(0x6022) > 1 or u8(0x6025) > 1: return False
        
        # party has been created
        if u8(0x6102) == 0: return False
        # chaos shaking animation
        if u8(0x6B86) == 0xFF: return True
        # not currently in battle
        if u8(0x60FC) in (0x0B, 0x0C): return False
        return True
        
    def is_chaos_dead(self, u8):
        if u8(0x6B86) == 0xFF and u8(0x6C92) == 0x04 and u8(0x006A) == 0x7B:
            return True
        return False

    def get_local_key_items(self, u8):
        k = {key: False for key in KEYITEM_ORDER}
        
        # simple items
        k["Lute"] = u8(0x6021) > 0
        k["Crown"] = u8(0x6022) > 0
        k["Key"] = u8(0x6025) > 0
        k["Rod"] = u8(0x602A) > 0
        k["Floater"] = u8(0x602B) > 0
        k["Chime"] = u8(0x602C) > 0
        k["Cube"] = u8(0x602E) > 0
        k["Oxyale"] = u8(0x6030) > 0
        k["Canoe"] = u8(0x6012) > 0
        k["Bridge"] = u8(0x6008) > 0
        
        # Orbs logic (Shard Hunt overrides to False)
        k["FireOrb"] = (u8(0x6032) > 0) if not self.shardhuntmode else False
        k["WaterOrb"] = (u8(0x6033) > 0) if not self.shardhuntmode else False
        k["AirOrb"] = (u8(0x6034) > 0) if not self.shardhuntmode else False
        k["EarthOrb"] = (u8(0x6031) > 0) if not self.shardhuntmode else False
        
        # reverse items
        k["Canal"] = (u8(0x600C) == 0)
        
        # complex items
        k["Crystal"] = (u8(0x6023) > 0) or ((u8(0x620A) & 0x02) > 0)
        k["Herb"] = (u8(0x6024) > 0) or ((u8(0x6205) & 0x02) > 0)
        k["TNT"] = (u8(0x6026) > 0) or ((u8(0x6208) & 0x02) > 0)
        k["Adamant"] = (u8(0x6027) > 0) or ((u8(0x6209) & 0x02) > 0)
        k["Slab"] = (u8(0x6028) > 0) or ((u8(0x620B) & 0x02) > 0)
        k["Ruby"] = (u8(0x6029) > 0) or ((u8(0x6214) & 0x01) == 0)
        k["Tail"] = (u8(0x602D) > 0) or ((u8(0x620E) & 0x02) > 0)
        k["Bottle"] = (u8(0x602F) > 0) or ((u8(0x6213) & 0x03) > 0)
        
        k["Ship"] = (u8(0x6000) & 0x01) > 0
        k["SlabTranslation"] = (u8(0x620B) & 0x02) > 0
        
        if self.is_chaos_dead(u8) or self.chaos_defeated:
            self.chaos_defeated = True
            k["EndGame"] = True
            
        return k

    def give_item(self, item, u8):
        reqs = [{"type": "GUARD", "address": 0x3C901, "expected_data": "j6yxpK8=", "domain": "PRG ROM"}]
        
        def write_u8(addr, val):
            b64_val = base64.b64encode(bytes([val])).decode('utf-8')
            reqs.append({"type": "WRITE", "address": addr, "value": b64_val, "domain": "System Bus"})

        item_actions = {
            "Lute": lambda: write_u8(0x6021, 0x01),
            "Crown": lambda: write_u8(0x6022, 0x01),
            "Key": lambda: write_u8(0x6025, 0x01),
            "Rod": lambda: write_u8(0x602A, 0x01),
            "Floater": lambda: write_u8(0x602B, 0x01),
            "Chime": lambda: write_u8(0x602C, 0x01),
            "Cube": lambda: write_u8(0x602E, 0x01),
            "Oxyale": lambda: write_u8(0x6030, 0x01),
            "Ship": lambda: write_u8(0x6000, u8(0x6000) | 0x01),
            "Canoe": lambda: write_u8(0x6012, 0x01),
            "Bridge": lambda: write_u8(0x6008, 0x01),
            "Canal": lambda: write_u8(0x600C, 0x00),
            "Crystal": lambda: write_u8(0x6023, 0x01),
            "Herb": lambda: write_u8(0x6024, 0x01),
            "TNT": lambda: write_u8(0x6026, 0x01),
            "Adamant": lambda: write_u8(0x6027, 0x01),
            "Slab": lambda: write_u8(0x6028, 0x01),
            "Ruby": lambda: write_u8(0x6029, 0x01),
            "Tail": lambda: write_u8(0x602D, 0x01),
            "Bottle": lambda: write_u8(0x602F, 0x01),
            "SlabTranslation": lambda: write_u8(0x620B, u8(0x620B) | 0x02),
            "EarthOrb": lambda: write_u8(0x6031, 0x01),
            "FireOrb": lambda: write_u8(0x6032, 0x01),
            "WaterOrb": lambda: write_u8(0x6033, 0x01),
            "AirOrb": lambda: write_u8(0x6034, 0x01),
        }

        if item in item_actions:
            item_actions[item]()

        if len(reqs) > 1:
            self.bizhawk.send_command(reqs)

    def display_message(self, message):
        req = [{"type": "DISPLAY_MESSAGE", "message": message}]
        self.bizhawk.send_command(req)


class FFRCoopClient:
    def __init__(self, server, player, team=None, log_callback=None, bizhawk_client=None):
        self.server = server
        self.player = player
        self.team = team
        self.log_callback = log_callback
        
        self.server_version = self._get_server_version()
        if self.server_version == "2.0":
            self.server_client = ServerClientV2(server, player, team, log_callback=self._log,
                                               message_callback=self._on_server_message)
            self.server_client.connect()
        elif self.server_version == "0.13;0.13":
            self.server_client = ServerClientV1(server, player, team, log_callback=self._log)
        else:
            raise ConnectionError(f"Unsupported server version '{self.server_version}'")
            
        self.bizhawk = bizhawk_client if bizhawk_client else BizhawkClient(auto_start=True)
        self._external_bizhawk = bool(bizhawk_client)

        if not self._external_bizhawk:
            self.bizhawk.add_connection_callback(self._bizhawk_connection_callback)
            
        self.game = FFRGameInterface(self.bizhawk, self._log)
            
        self.local_items = {k: False for k in KEYITEM_ORDER}
        self.remotely_granted_items = set()
        self._running = False

    def _get_server_version(self):
        """Fetch the server version. Returns "2.0" or "0.13;0.13", or raises ConnectionError."""
        url = f"http://{self.server}/version"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.read().decode('utf-8').strip()
        except Exception as e:
            raise ConnectionError(f"Could not connect to server at {self.server} ({e})")
        
    def _bizhawk_connection_callback(self, connected):
        if connected:
            self._log("Connected to Bizhawk emulator.")
        else:
            self._log("Disconnected from Bizhawk emulator. Waiting for connection...")
            
    def _log(self, message):
        if self.log_callback:
            self.log_callback(message)
        else:
            logging.info(message)

    def _on_server_message(self, player, message):
        """Callback for V2 server-pushed messages."""
        self.game.display_message(message)
        self._log(message)

    def _format_item_message(self, player_name, item_name):
        if item_name == "EndGame":
            return f"{player_name} has defeated Chaos!"
            
        loc = self.game.item_locations.get(item_name)
        if loc:
            return f"{player_name} obtained item: {item_name} (found at {loc})"
        return f"{player_name} obtained item: {item_name}"
        
    def _broadcast_event(self, msg):
        self.game.display_message(msg)
        self._log(msg)
        self.server_client.send_message(msg)

    def initialize_team(self, limit):
        self.server_client.initialize_team(limit)
        self.team = self.server_client.team
        self.server_client.send_message(f"{self.player} has connected.")

    def join_team(self):
        self.server_client.join_team()
        self.team = self.server_client.team
        self.server_client.send_message(f"{self.player} has connected.")

    def wait_for_bizhawk(self):
        while not self.bizhawk.is_connected and self._running:
            time.sleep(1)
            
        if not self._running:
            return
            
        self.game.check_shardhunt_mode()
        self.game.read_item_locations_from_rom()

    def _process_local_changes(self, new_local_items, first_loop):
        for k in KEYITEM_ORDER:
            if new_local_items[k] and not self.local_items[k]:
                if k in self.remotely_granted_items:
                    self.remotely_granted_items.remove(k)
                elif not first_loop:
                    msg = self._format_item_message(self.player, k)
                    self._broadcast_event(msg)
                    
        self.local_items = new_local_items

    def _process_remote_changes(self, server_res, u8):
        remote_data = server_res.get("data", "")
        messages = server_res.get("messages", [])
        playeritems = server_res.get("playeritems", [])
        
        if len(remote_data) == len(KEYITEM_ORDER):
            items_received = []
            for i, k in enumerate(KEYITEM_ORDER):
                remote_has_item = (remote_data[i] == '1')
                if remote_has_item and not self.local_items[k] and k != "EndGame":
                    # Item found by teammate, give to local player
                    self.game.give_item(k, u8)
                    self.remotely_granted_items.add(k)
                    items_received.append(k)
                    
                    # On V1, generate the "who obtained it" message locally
                    # from sync data. On V2, this message arrives via push
                    # from the obtainer's client, so skip it here.
                    if not isinstance(self.server_client, ServerClientV2):
                        obtainer = playeritems[i] if i < len(playeritems) else "Someone"
                        msg = self._format_item_message(obtainer, k)
                        self.game.display_message(msg)
                        self._log(msg)
            
            if items_received:
                word = "item" if len(items_received) == 1 else "items"
                items_str = ", ".join(items_received)
                msg = f"Giving {word} to local player: {items_str}"
                self.game.display_message(msg)
                self._log(msg)
        
        for msg in messages:
            self.game.display_message(msg)
            self._log(msg)

    def run(self):
        self._running = True
        self.wait_for_bizhawk()
        
        if not self._running:
            return
            
        self._log("Starting main loop...")
        
        last_sync_time = 0
        last_data_str = ""
        first_loop = True
        
        while self._running:
            time.sleep(1)
            if not self.bizhawk.is_connected:
                continue

            if not getattr(self, 'server_ready', True):
                continue

            u8 = self.game.read_memory_blocks()
            if not u8:
                continue
                
            if not self.game.is_state_ok(u8):
                continue
                
            new_local_items = self.game.get_local_key_items(u8)
            
            self._process_local_changes(new_local_items, first_loop)
            first_loop = False
            
            # Convert to string (EndGame is local-only, never synced)
            data_str = "".join(["1" if (self.local_items[k] and k != "EndGame") else "0" for k in KEYITEM_ORDER])
            
            current_time = time.time()
            if data_str != last_data_str or (current_time - last_sync_time) >= 5:
                # Sync with server
                server_res = self.server_client.sync_with_server(data_str)
                last_sync_time = current_time
                last_data_str = data_str
                
                if server_res:
                    self._process_remote_changes(server_res, u8)
                        
    def stop(self):
        self._running = False
        # Do not stop bizhawk if it was provided externally, let the creator manage it
        if not hasattr(self, '_external_bizhawk') or not self._external_bizhawk:
            self.bizhawk.stop()

if __name__ == '__main__':
    gui._main_()
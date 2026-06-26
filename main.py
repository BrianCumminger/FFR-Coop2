import argparse
import configparser
import time
import urllib.request
import urllib.parse
import json
import base64
import logging
import sys
from bizhawk_client import BizhawkClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

KEYITEM_ORDER = [
    "Lute", "Crown", "Crystal", "Herb", "Key", "TNT", "Adamant", "Slab", "Ruby",
    "Rod", "Floater", "Chime", "Tail", "Cube", "Bottle", "Oxyale", "Ship", "Canoe",
    "Airship", "Bridge", "Canal", "SlabTranslation", "EarthOrb", "FireOrb", "WaterOrb", "AirOrb", "EndGame"
]

class FFRCoopClient:
    def __init__(self, server, player, team=None):
        self.server = server
        self.player = player
        self.team = team
        self.shardhuntmode = False
        self.bizhawk = BizhawkClient(auto_start=True)
        self.local_items = {k: False for k in KEYITEM_ORDER}
        self.chaos_defeated_remotely = False
        
    def initialize_team(self, limit):
        url = f"http://{self.server}/init?player={urllib.parse.quote(self.player)}&limit={limit}"
        logging.info(f"Initializing team: {url}")
        try:
            with urllib.request.urlopen(url) as response:
                self.team = response.read().decode('utf-8').strip()
                logging.info(f"Successfully created team {self.team}")
        except Exception as e:
            logging.error(f"Failed to initialize team: {e}")
            sys.exit(1)

    def join_team(self):
        url = f"http://{self.server}/join?team={urllib.parse.quote(self.team)}&player={urllib.parse.quote(self.player)}"
        logging.info(f"Joining team {self.team}: {url}")
        try:
            with urllib.request.urlopen(url) as response:
                res = response.read().decode('utf-8').strip()
                if "Error" in res:
                    logging.error(f"Failed to join team: {res}")
                    sys.exit(1)
                logging.info(f"Successfully joined team {self.team}")
        except Exception as e:
            logging.error(f"Failed to join team: {e}")
            sys.exit(1)

    def wait_for_bizhawk(self):
        logging.info("Waiting for Bizhawk connection...")
        while not self.bizhawk.is_connected:
            time.sleep(1)
        logging.info("Connected to Bizhawk!")
        
        # Check for Shard Hunt mode
        req = [{"type": "READ", "address": 0x37761, "size": 1, "domain": "PRG ROM"}]
        res = self.bizhawk.send_command(req)
        if res and res[0].get("type") == "READ_RESPONSE":
            val = base64.b64decode(res[0]["value"])
            if val[0] == 0x1C:
                self.shardhuntmode = True
                logging.info("Detected Shard Hunt ROM")
        else:
            logging.warning("Failed to read PRG ROM to detect Shard Hunt. Defaulting to standard mode.")

    def read_memory_blocks(self):
        # We need several blocks from System Bus
        # Block 0: 0x0000 - 0x006B (covers 0x0000 Ship, 0x0008 Bridge, 0x000C Canal, 0x0012 Canoe, 0x0021-0x0034 Items, 0x006A btlformation)
        # Wait, the user said writes are relative to save ram so we add 0x6000. 
        # In ffr_team.lua: Lute was check u8(0x6021), write w_u8(0x0021). Wait! 0x0021 in Battery RAM == 0x6021 in System Bus.
        # But if we use System Bus for reading AND writing, we just use 0x6000 offsets for both.
        # The user clarification: "The writes in the giveItemFunctions table are relative to save ram, so they can be mapped into the "System Bus" domain by adding 0x6000 to them."
        # This confirms we use 0x6000 offsets for both reads and writes.
        # Let's do reads via System Bus directly.
        reqs = [
            {"type": "READ", "address": 0x6000, "size": 0x35, "domain": "System Bus"},  # 0x6000 - 0x6034
            {"type": "READ", "address": 0x6200, "size": 0x16, "domain": "System Bus"},  # 0x6200 - 0x6215
            {"type": "READ", "address": 0x6B86, "size": 1, "domain": "System Bus"},     # 0x6B86 (Chaos Result)
            {"type": "READ", "address": 0x6C92, "size": 1, "domain": "System Bus"},     # 0x6C92 (Chaos Battle Type)
            {"type": "READ", "address": 0x006A, "size": 1, "domain": "System Bus"},     # 0x006A (Battle Formation)
            {"type": "READ", "address": 0x6102, "size": 1, "domain": "System Bus"},     # 0x6102 (Party check)
            {"type": "READ", "address": 0x60FC, "size": 1, "domain": "System Bus"},     # 0x60FC (Battle Type)
        ]
        res = self.bizhawk.send_command(reqs)
        if not res or len(res) != 7:
            return None
            
        data = {}
        for i, r in enumerate(res):
            if r.get("type") == "READ_RESPONSE":
                data[i] = base64.b64decode(r["value"])
            else:
                return None
                
        # Helper to get u8
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
        
        if self.is_chaos_dead(u8) or self.chaos_defeated_remotely:
            k["EndGame"] = True
            
        return k

    def give_item(self, item, u8):
        logging.info(f"Giving item to local player: {item}")
        reqs = []
        
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

        if item == "EndGame": 
            self.chaos_defeated_remotely = True
        elif item in item_actions:
            item_actions[item]()

        if reqs:
            self.bizhawk.send_command(reqs)

    def display_message(self, message):
        req = [{"type": "DISPLAY_MESSAGE", "message": message}]
        self.bizhawk.send_command(req)

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

    def run(self):
        self.wait_for_bizhawk()
        logging.info("Starting main loop...")
        
        last_sync_time = 0
        last_data_str = ""
        
        while True:
            time.sleep(1)
            if not self.bizhawk.is_connected:
                continue

            u8 = self.read_memory_blocks()
            if not u8:
                continue
                
            if not self.is_state_ok(u8):
                continue
                
            self.local_items = self.get_local_key_items(u8)
            
            # Convert to string
            data_str = "".join(["1" if self.local_items[k] else "0" for k in KEYITEM_ORDER])
            
            current_time = time.time()
            if data_str != last_data_str or (current_time - last_sync_time) >= 5:
                # Sync with server
                server_res = self.sync_with_server(data_str)
                last_sync_time = current_time
                last_data_str = data_str
                
                if server_res:
                    remote_data = server_res.get("data", "")
                    messages = server_res.get("messages", [])
                    playeritems = server_res.get("playeritems", [])
                    
                    if len(remote_data) == len(KEYITEM_ORDER):
                        for i, k in enumerate(KEYITEM_ORDER):
                            remote_has_item = (remote_data[i] == '1')
                            if remote_has_item and not self.local_items[k]:
                                # Item found by teammate, give to local player
                                self.give_item(k, u8)
                                
                                obtainer = playeritems[i] if i < len(playeritems) else "Someone"
                                if k == "EndGame":
                                    self.display_message(f"{obtainer} has defeated Chaos!")
                                else:
                                    self.display_message(f"{obtainer} obtained item: {k}")
                    
                    for msg in messages:
                        self.display_message(msg)

if __name__ == "__main__":
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    default_server = config.get('Settings', 'ServerAddress', fallback=None)
    default_player = config.get('Settings', 'DefaultPlayer', fallback='LazyRacer')

    parser = argparse.ArgumentParser(description="FFR Coop Python CLI Client")
    parser.add_argument("--player", type=str, default=default_player, help="Player name")
    parser.add_argument("--join", type=str, help="Team number to join")
    parser.add_argument("--init", type=int, nargs="?", const=50, metavar="LIMIT", help="Initialize a new team with player limit (default 50)")
    parser.add_argument("--server", type=str, default=default_server, help="Server address/port (e.g., ffr.dpldocs.info:5555)")
    
    args = parser.parse_args()

    if not args.server:
        print("Error: ServerAddress is not configured in config.ini and no --server argument was provided.")
        sys.exit(1)

    if not args.join and not args.init:
        print("Error: Must specify either --join <team number> to join, or --init [limit] to create a team.")
        sys.exit(1)

    client = FFRCoopClient(server=args.server, player=args.player, team=args.join)
    
    try:
        if args.init:
            client.initialize_team(args.init)
        else:
            client.join_team()
            
        client.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        sys.exit(0)

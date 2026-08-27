# Co-op 2.0
## for Final Fantasy Randomizer

Co-op play mode for Final Fantasy Randomizer is a game mode where 2 or more players share key items over a network connection. 

This project is a modern client for FFR Co-op written in Python with TK gui components. It uses the Archipelago BizHawk client connector lua instead of a custom connector and requires no extra DLL installation. Both the original Co-op server and the new server included with this project are supported.

![screenshot](resources/screenshot.png)

### Features of 2.0
- Easy to use Python GUI with dark mode support.
- New server uses websockets for instantaneous updates.
- Client supports both the original server and new server.
- Nothing extra to install.
- Client uses standard [Archipelago](https://archipelago.gg/) connector lua script for communication with [BizHawk](https://tasvideos.org/Bizhawk).

### Prerequisites
- [BizHawk](https://tasvideos.org/Bizhawk) (version 2.4 or later recommended)
- Python 3.8 or later (if running from source)
- A [Final Fantasy Randomizer](https://finalfantasyrandomizer.com/) ROM.

### What is Co-op play mode?
Co-op play mode for Final Fantasy Randomizer is where 2 or more players share obtained key items over a network connection. Players match up by one player creating a team on the server, and other players joining that team number. All key items (Lute, Ship, Slab, etc), once obtained, will be sent to all other players. This includes orbs and the slab translation. If the ROM generated is a shard hunt ROM, each player will be required to find their own shards - shards are not shared.

## Running the Client
### Windows

Download the latest release and run the .exe. Load your FFR ROM in BizHawk, open the lua console and load either the included `bizhawk-connector/connector_bizhawk_generic.lua` or the generic BizHawk connector included with [Archipelago](https://archipelago.gg/). Configure the server address/port and your player name in the client and use the connect tab to either create or join a team.

### Running from source

First, install the required dependencies:
```bash
pip install -r requirements.txt
```

You can run the GUI client by executing:
```bash
python gui.py
```

Alternatively, the CLI client can be used:
```bash
# To initialize a new team
python main.py --player YourName --init

# To join an existing team
python main.py --player YourName --join <team_number>
```
You can configure default settings, such as the `ServerAddress`, in `config.ini`.

## Deploying the Server

Version 2.0 of the backend server is located in the `server` directory.

### Using Docker (Recommended)

The easiest way to deploy the server is by using the provided `docker-compose.yml`:
```bash
cd server
docker compose up --build -d
```

### Manual Setup

If you prefer to run the server manually without Docker using Python 3.9 or later:
```bash
cd server
pip install -r requirements.txt
python coop-server.py
```

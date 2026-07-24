import customtkinter as ctk
import configparser
import threading
import datetime
import sys
import os
import tkinter as tk
from main import FFRCoopClient
from bizhawk_client import BizhawkClient

def resource_path(relative_path):
    """ Get absolute path to resource for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# Appearance Mode is set dynamically in __init__
ctk.set_default_color_theme("blue")

CREDITS_TEXT = """Development:
MeridianBC

Testing:
Willcleosis, TrintonGL, monoci85, Falconic, neongrey, MoistMogwai

Special thanks to everyone who has played and given feedback!"""


class CreditsDialog(ctk.CTkToplevel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title("Credits")
        self.geometry("400x350")
        
        # Center window
        self.update_idletasks()
        
        lbl_title = ctk.CTkLabel(self, text="Co-op Play Mode", font=ctk.CTkFont(size=20, weight="bold"))
        lbl_title.pack(pady=(20, 5))
        
        lbl_for = ctk.CTkLabel(self, text="for", font=ctk.CTkFont(size=14))
        lbl_for.pack(pady=0)
        
        lbl_sub = ctk.CTkLabel(self, text="Final Fantasy Randomizer", font=ctk.CTkFont(size=18, weight="bold"))
        lbl_sub.pack(pady=(5, 20))
        
        textbox = ctk.CTkTextbox(self, width=350, height=180, wrap="word")
        textbox.pack(padx=20, pady=10)
        textbox.insert("0.0", CREDITS_TEXT)
        textbox.configure(state="disabled")


class FFRCoopGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("FFR Co-op Client 2.0")
        self.geometry("550x500")
        self.minsize(500, 500)
        
        self.config = configparser.ConfigParser()
        config_files_read = self.config.read('config.ini')
        self.is_first_run = len(config_files_read) == 0
        self.default_server = self.config.get('Settings', 'ServerAddress', fallback='')
        self.default_player = self.config.get('Settings', 'DefaultPlayer', fallback='LazyRacer')
        self.show_timestamps = self.config.getboolean('Settings', 'ShowTimestamps', fallback=True)
        self.appearance_mode = self.config.get('Settings', 'AppearanceMode', fallback='System')
        
        ctk.set_appearance_mode(self.appearance_mode)
        
        self.client = None
        self.client_thread = None
        
        self.bizhawk = BizhawkClient(auto_start=True)
        self.bizhawk.add_connection_callback(self.on_bizhawk_connection_change)

        # Status Images
        self.img_disconnected = tk.PhotoImage(file=resource_path(r"resources\th4.png"))
        self.img_connected = tk.PhotoImage(file=resource_path(r"resources\th3.png"))

        self.lbl_status_icon = ctk.CTkLabel(self, text="", image=self.img_disconnected)

        self.iconbitmap(resource_path(r"resources\ffrcoop2.ico"))

        # Create Tabview
        self.tabview = ctk.CTkTabview(self, width=450, height=400)
        self.tabview.pack(padx=20, pady=(20, 40), fill="both", expand=True)
        
        # Place icon in the bottom padding
        self.lbl_status_icon.place(x=20, rely=0.98, anchor="sw")
        self.lbl_status_icon.lift()

        self.tab_connect = self.tabview.add("Connect")
        self.tab_logs = self.tabview.add("Messages")
        self.tab_settings = self.tabview.add("Settings")
        
        self.build_connect_tab()
        self.build_logs_tab()
        self.build_settings_tab()
        
        if self.is_first_run:
            self.tabview.set("Settings")

    def build_connect_tab(self):
        self.tab_connect.grid_columnconfigure(0, weight=1)
        
        # Player Name
        lbl_player = ctk.CTkLabel(self.tab_connect, text="Player Name:")
        lbl_player.grid(row=0, column=0, pady=(20, 5), padx=20, sticky="w")
        self.entry_player_var = ctk.StringVar(value=self.default_player)
        self.entry_player_var.trace_add("write", self.validate_connect_button)
        self.entry_player = ctk.CTkEntry(self.tab_connect, width=200, textvariable=self.entry_player_var)
        self.entry_player.grid(row=1, column=0, pady=0, padx=20, sticky="w")
        
        # Mode Selection
        self.mode_var = ctk.StringVar(value="Join Team")
        self.seg_mode = ctk.CTkSegmentedButton(self.tab_connect, values=["Join Team", "Create Team"], 
                                               variable=self.mode_var, command=self.on_mode_change)
        self.seg_mode.grid(row=2, column=0, pady=(30, 10), padx=20, sticky="we")
        
        # Team Number or Game Limit Label
        self.lbl_dynamic = ctk.CTkLabel(self.tab_connect, text="Team Number:")
        self.lbl_dynamic.grid(row=3, column=0, pady=(10, 5), padx=20, sticky="w")
        
        # Team Number or Game Limit Entry
        self.entry_dynamic_var = ctk.StringVar()
        self.entry_dynamic_var.trace_add("write", self.validate_connect_button)
        self.entry_dynamic = ctk.CTkEntry(self.tab_connect, width=200, textvariable=self.entry_dynamic_var)
        self.entry_dynamic.grid(row=4, column=0, pady=0, padx=20, sticky="w")
        
        # Connect Button
        self.btn_connect = ctk.CTkButton(self.tab_connect, text="Connect", command=self.on_connect)
        self.btn_connect.grid(row=5, column=0, pady=(40, 20), padx=20, sticky="we")
        
        self.validate_connect_button()

    def build_logs_tab(self):
        self.tab_logs.grid_columnconfigure(0, weight=1)
        self.tab_logs.grid_rowconfigure(1, weight=1)
        
        self.lbl_logs_header = ctk.CTkLabel(self.tab_logs, text="", font=ctk.CTkFont(weight="bold"))
        self.lbl_logs_header.grid(row=0, column=0, pady=(5, 5), sticky="w", padx=10)
        
        self.textbox_logs = ctk.CTkTextbox(self.tab_logs, wrap="word", state="disabled")
        self.textbox_logs.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

    def build_settings_tab(self):
        self.tab_settings.grid_columnconfigure(0, weight=1)
        
        # Server Address
        lbl_server = ctk.CTkLabel(self.tab_settings, text="Server Address:")
        lbl_server.grid(row=0, column=0, pady=(20, 5), padx=20, sticky="w")
        self.entry_server = ctk.CTkEntry(self.tab_settings, width=300)
        self.entry_server.grid(row=1, column=0, pady=0, padx=20, sticky="w")
        self.entry_server.insert(0, self.default_server)
        
        # Default Player Name
        lbl_default_player = ctk.CTkLabel(self.tab_settings, text="Default Player Name:")
        lbl_default_player.grid(row=2, column=0, pady=(10, 5), padx=20, sticky="w")
        self.entry_default_player = ctk.CTkEntry(self.tab_settings, width=300)
        self.entry_default_player.grid(row=3, column=0, pady=0, padx=20, sticky="w")
        self.entry_default_player.insert(0, self.default_player)
        
        # Timestamps Toggle
        self.var_timestamps = ctk.BooleanVar(value=self.show_timestamps)
        self.chk_timestamps = ctk.CTkSwitch(self.tab_settings, text="Show Timestamps in Messages", variable=self.var_timestamps)
        self.chk_timestamps.grid(row=4, column=0, pady=(10, 10), padx=20, sticky="w")
        
        # Appearance Mode
        lbl_appearance = ctk.CTkLabel(self.tab_settings, text="Appearance Mode:")
        lbl_appearance.grid(row=5, column=0, pady=(10, 0), padx=20, sticky="w")
        self.var_appearance = ctk.StringVar(value=self.appearance_mode)
        self.opt_appearance = ctk.CTkOptionMenu(self.tab_settings, values=["System", "Dark", "Light"], variable=self.var_appearance, command=self.on_appearance_change)
        self.opt_appearance.grid(row=6, column=0, pady=(5, 10), padx=20, sticky="w")
        
        # Save Button
        self.btn_save = ctk.CTkButton(self.tab_settings, text="Save Settings", command=self.on_save_settings)
        self.btn_save.grid(row=7, column=0, pady=(20, 10), padx=20, sticky="w")
        
        # Credits Button
        self.btn_credits = ctk.CTkButton(self.tab_settings, text="View Credits", command=self.on_view_credits)
        self.btn_credits.grid(row=8, column=0, pady=(30, 10), padx=20, sticky="e")

    def on_appearance_change(self, new_mode):
        ctk.set_appearance_mode(new_mode)

    def validate_connect_button(self, *args):
        if not hasattr(self, 'btn_connect') or not hasattr(self, 'mode_var'):
            return
            
        mode = self.mode_var.get()
        val = self.entry_dynamic_var.get()
        
        # Enforce digits only
        filtered_val = ''.join(filter(str.isdigit, val))
        if val != filtered_val:
            self.entry_dynamic_var.set(filtered_val)
            val = filtered_val
            
        val = val.strip()
        player_name = self.entry_player_var.get().strip() if hasattr(self, 'entry_player_var') else ""
        
        if not player_name or (mode == "Join Team" and not val):
            self.btn_connect.configure(state="disabled")
        else:
            self.btn_connect.configure(state="normal")

    def on_mode_change(self, value):
        if value == "Join Team":
            self.lbl_dynamic.configure(text="Team Number:")
            self.entry_dynamic.delete(0, 'end')
        else:
            self.lbl_dynamic.configure(text="Player Limit (Optional):")
            self.entry_dynamic.delete(0, 'end')
            self.entry_dynamic.insert(0, "50")

    def log(self, message):
        if self.show_timestamps:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            formatted = f"[{timestamp}] {message}\n"
        else:
            formatted = f"{message}\n"
        
        # Must schedule GUI updates from the main thread
        self.after(0, self._insert_log, formatted)

    def _insert_log(self, text):
        self.textbox_logs.configure(state="normal")
        self.textbox_logs.insert("end", text)
        self.textbox_logs.see("end")
        self.textbox_logs.configure(state="disabled")

    def on_bizhawk_connection_change(self, connected):
        if connected:
            self.log("Connected to Bizhawk emulator.")
        else:
            self.log("Disconnected from Bizhawk emulator. Waiting for connection...")

    def on_save_settings(self):
        new_server = self.entry_server.get().strip()
        new_player = self.entry_default_player.get().strip()
        new_timestamps = self.var_timestamps.get()
        new_appearance = self.var_appearance.get()
        
        if new_player and hasattr(self, 'entry_player_var'):
            self.entry_player_var.set(new_player)
        
        if not self.config.has_section('Settings'):
            self.config.add_section('Settings')
            
        self.config.set('Settings', 'ServerAddress', new_server)
        self.config.set('Settings', 'DefaultPlayer', new_player)
        self.config.set('Settings', 'ShowTimestamps', str(new_timestamps))
        self.config.set('Settings', 'AppearanceMode', new_appearance)
        
        with open('config.ini', 'w') as f:
            self.config.write(f)
            
        self.default_server = new_server
        self.default_player = new_player
        self.show_timestamps = new_timestamps
        self.appearance_mode = new_appearance
        self.log("Settings saved.")

    def on_view_credits(self):
        dialog = CreditsDialog(self)
        dialog.grab_set()

    def on_connect(self):
        if self.client and self.client._running:
            self.client.stop()
            self.btn_connect.configure(text="Connect", fg_color=["#3a7ebf", "#1f538d"])
            self.log("Disconnected.")
            return

        server = self.entry_server.get().strip()
        player = self.entry_player.get().strip()
        mode = self.mode_var.get()
        dynamic_val = self.entry_dynamic.get().strip()

        if not server:
            self.log("ERROR: Server address is required.")
            return
        if not player:
            self.log("ERROR: Player name is required.")
            return

        self.tabview.set("Messages")
        self.btn_connect.configure(text="Disconnect", fg_color=["#c23b22", "#8b0000"])
        self.lbl_logs_header.configure(text=f"Player: {player}  |  Team: Connecting...")
        
        self.log(f"Connecting to server {server} as {player}...")

        # Switch to logs tab and start the client in a background thread
        self.client_thread = threading.Thread(target=self.run_client, args=(server, player, mode, dynamic_val), daemon=True)
        self.client_thread.start()

    def run_client(self, server, player, mode, dynamic_val):
        try:
            limit = int(dynamic_val) if dynamic_val.isdigit() else 50
            self.client = FFRCoopClient(server=server, player=player, team=dynamic_val if mode == "Join Team" else None, log_callback=self.log, bizhawk_client=self.bizhawk)
            self.client.server_ready = False
            
            def server_connect():
                try:
                    if mode == "Join Team":
                        self.client.join_team()
                    else:
                        self.client.initialize_team(limit)
                        
                    self.after(0, lambda: self.lbl_logs_header.configure(text=f"Player: {player}  |  Team: {self.client.team}"))
                    self.after(0, lambda: self.lbl_status_icon.configure(image=self.img_connected))
                    self.client.server_ready = True
                except Exception as e:
                    self.log(f"Fatal Server Error: {e}")
                    self.after(0, self.reset_connect_button)
                    self.client.stop()

            threading.Thread(target=server_connect, daemon=True).start()
            
            self.client.run()
        except Exception as e:
            self.log(f"Fatal Client Error: {e}")
            self.after(0, self.reset_connect_button)

    def reset_connect_button(self):
        self.btn_connect.configure(text="Connect", fg_color=["#3a7ebf", "#1f538d"])
        self.lbl_status_icon.configure(image=self.img_disconnected)
        
    def destroy(self):
        if self.client:
            self.client.stop()
        if hasattr(self, 'bizhawk'):
            self.bizhawk.stop()
        super().destroy()


if __name__ == "__main__":
    app = FFRCoopGUI()
    app.mainloop()

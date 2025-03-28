import asyncio
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import json
import traceback
import threading  # **Added:** Importing threading for running the event loop in a separate thread

from anchorpy import Program, Provider, Wallet, Idl, Context
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from solana.rpc.types import TxOpts
from solana.transaction import Transaction, Signature

import re  # **Added:** Importing the 're' module

# Constants - Update these as per your setup
PROGRAM_ID_STR = "HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut"
IDL_PATH = Path("../target/idl/fancoin.json")  # Path to your IDL
VALIDATOR_KEYPAIR_PATH = "val1-keypair.json"  # Path to your validator keypair
SOLANA_RPC_URL = "http://localhost:8899"       # Update if using a different RPC URL

# Token Program IDs
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
RENT_SYSVAR_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

LAMPORTS_TO_SEND = 10_000_000  # 0.01 SOL

class TokenMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Solana Player Token Monitor")
        self.root.geometry("1200x700")
        
        # Setup UI
        self.setup_ui()
        
        # Initialize data structures
        self.player_data = []
        
        # Start the asyncio event loop in a separate thread
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self.start_loop, daemon=True)
        self.loop_thread.start()
        
        # Schedule the initialization and first data fetch
        asyncio.run_coroutine_threadsafe(self.initialize_program(), self.loop)
        asyncio.run_coroutine_threadsafe(self.fetch_and_display_player_balances(), self.loop)
        
        # Schedule automatic refresh every 5 minutes (300,000 milliseconds)
        self.root.after(300000, self.auto_refresh)
    
    def setup_ui(self):
        # Create a frame for the table
        frame = ttk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create the Treeview
        columns = ("Player Name", "Player PDA", "Reward ATA", "Token Balance", "Status")
        self.tree = ttk.Treeview(frame, columns=columns, show='headings')
        for col in columns:
            self.tree.heading(col, text=col)
            if col == "Status":
                self.tree.column(col, anchor=tk.CENTER, width=150)
            else:
                self.tree.column(col, anchor=tk.CENTER, width=220)
        
        # Add a vertical scrollbar
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self.tree.pack(fill=tk.BOTH, expand=True)
        
        # Define tags for coloring rows
        self.tree.tag_configure("valid", background="lightgreen")
        self.tree.tag_configure("invalid", background="lightcoral")
        self.tree.tag_configure("not_found", background="lightyellow")
        self.tree.tag_configure("error", background="lightblue")
        
        # Add a refresh button and an exit button
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        refresh_btn = ttk.Button(btn_frame, text="Refresh", command=self.refresh_data)
        refresh_btn.pack(side='left')
        
        exit_btn = ttk.Button(btn_frame, text="Exit", command=self.root.destroy)
        exit_btn.pack(side='right')
        
        # Bind double-click event to copy Reward ATA
        self.tree.bind("<Double-1>", self.on_double_click)
        
        # Bind right-click event to show context menu
        self.tree.bind("<Button-3>", self.on_right_click)
        
        # Create a context menu
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Copy Reward ATA", command=self.copy_selected_ata)
    
    def start_loop(self):
        """Run the asyncio event loop."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
    
    async def initialize_program(self):
        """Initialize the Anchor Program."""
        try:
            # Connect to Solana RPC
            self.client = AsyncClient(SOLANA_RPC_URL, commitment=Confirmed)
            
            # Load wallet from validator keypair
            validator_kp = self.load_validator_keypair(VALIDATOR_KEYPAIR_PATH)
            wallet = Wallet(validator_kp)
            
            # Create provider
            provider = Provider(self.client, wallet)
            
            # Load IDL
            if not IDL_PATH.exists():
                self.show_error("Initialization Error", f"IDL file not found at {IDL_PATH.resolve()}")
                self.root.destroy()
                return
            with IDL_PATH.open() as f:
                idl_json = f.read()
            idl = Idl.from_json(idl_json)
            
            # Program ID
            program_id = Pubkey.from_string(PROGRAM_ID_STR)
            
            # Create Program object
            self.program = Program(idl, program_id, provider)
            print("Program loaded successfully.")
        except Exception as e:
            self.show_error("Initialization Error", f"Failed to initialize program:\n{e}")
            traceback.print_exc()
            self.root.destroy()
    
    async def fetch_player_pdas_map(self) -> dict:
        """
        Returns a dict:
          {
             "<player_name>": {
                "index":  <u32 index in the anchor code>,
                "pda":    <Pubkey for PlayerPda>,
                "reward_address": <Pubkey for TokenAccount>,
                "player_wallet": <Pubkey for Player's Wallet>
             },
             ...
          }
        """
        try:
            # Derive DApp PDA
            seeds_dapp = [b"dapp"]
            (dapp_pda, bump_dapp) = Pubkey.find_program_address(seeds_dapp, self.program.program_id)
            self.dapp_pda = dapp_pda
            
            # Fetch DApp account
            dapp_data = await self.program.account["DApp"].fetch(dapp_pda)
            total_count = dapp_data.global_player_count
            print(f"[DEBUG] DApp has {total_count} players.")
            
            # Fetch all PlayerPda accounts
            all_records = await self.program.account["PlayerPda"].all()
            print(f"[DEBUG] Found {len(all_records)} PlayerPda records on-chain.")
            
            # Derive PDA to index mapping
            pda_to_index = {}
            for i in range(total_count):
                seed_index_bytes = i.to_bytes(4, "little")
                (pda, _) = Pubkey.find_program_address([b"player_pda", seed_index_bytes], self.program.program_id)
                pda_to_index[str(pda)] = i
            
            # Build the name map with reward_address and player_wallet
            name_map = {}
            for rec in all_records:
                pkey_str = str(rec.public_key)
                if pkey_str in pda_to_index:
                    real_idx = pda_to_index[pkey_str]
                    player_name = rec.account.name  # The "name" field on your PlayerPda
                    player_wallet = rec.account.authority  # Assuming 'authority' is the player's wallet
                    name_map[player_name] = {
                        "index": real_idx,
                        "pda": rec.public_key,
                        "reward_address": rec.account.reward_address,
                        "player_wallet": player_wallet
                    }
                else:
                    # Handle any leftover or mismatched records if necessary
                    pass
            
            return name_map
        except Exception as e:
            self.show_error("Data Fetch Error", f"Failed to fetch PlayerPda accounts:\n{e}")
            traceback.print_exc()
            return {}
    
    async def fetch_and_display_player_balances(self):
        """Fetch player balances and display them in the Treeview."""
        try:
            # Clear existing data in the table
            self.tree.delete(*self.tree.get_children())
            
            # Fetch player map
            name_map = await self.fetch_player_pdas_map()
            if not name_map:
                print("[INFO] No players found to display.")
                return
            
            # Iterate over each player and fetch ATA balance
            for player_name, info in name_map.items():
                player_pda = info["pda"]
                reward_ata = info["reward_address"]
                player_wallet = info["player_wallet"]
                
                # Fetch TokenAccount balance using Solana RPC
                try:
                    token_balance_resp = await self.client.get_token_account_balance(reward_ata, commitment=Confirmed)
                    if token_balance_resp.value:
                        token_balance = float(token_balance_resp.value.ui_amount)  # Retrieves balance in human-readable format
                        status = "Valid"
                        tag = "valid"
                    else:
                        token_balance = "N/A"
                        status = "Not Found"
                        tag = "not_found"
                    
                    # Insert into the table with appropriate tag
                    self.tree.insert("", "end", values=(
                        player_name,
                        str(player_pda),
                        str(reward_ata),
                        token_balance,
                        status
                    ), tags=(tag,))
                
                except RPCException as e:
                    # Handle RPC exceptions gracefully
                    self.tree.insert("", "end", values=(
                        player_name,
                        str(player_pda),
                        str(reward_ata),
                        "N/A",
                        "Error"
                    ), tags=("error",))
                    print(f"[ERROR] Unexpected error for player {player_name}: {e}")
                except Exception as e:
                    # Handle any other unexpected errors
                    self.tree.insert("", "end", values=(
                        player_name,
                        str(player_pda),
                        str(reward_ata),
                        "N/A",
                        "Error"
                    ), tags=("error",))
                    print(f"[ERROR] Unexpected error for player {player_name}: {e}")
            
            print("[INFO] Player balances updated.")
        except Exception as e:
            self.show_error("Display Error", f"Failed to display player balances:\n{e}")
            traceback.print_exc()
    
    def refresh_data(self):
        """Handle the Refresh button click."""
        asyncio.run_coroutine_threadsafe(self.fetch_and_display_player_balances(), self.loop)
    
    async def auto_refresh_coroutine(self):
        """Coroutine to handle automatic refreshing."""
        while True:
            await self.fetch_and_display_player_balances()
            await asyncio.sleep(300)  # 5 minutes
    
    def auto_refresh(self):
        """Start the auto-refresh coroutine."""
        asyncio.run_coroutine_threadsafe(self.auto_refresh_coroutine(), self.loop)
    
    def load_validator_keypair(self, filename="val1-keypair.json") -> Keypair:
        """Load from raw 64-byte secret in a JSON array, e.g. [12,34,56,...]."""
        try:
            with Path(filename).open() as f:
                secret = json.load(f)
            # Assuming the JSON is a list of integers representing the keypair bytes
            return Keypair.from_bytes(bytes(secret[0:64]))
        except Exception as e:
            self.show_error("Keypair Load Error", f"Failed to load validator keypair from {filename}:\n{e}")
            raise
    
    def on_double_click(self, event):
        """
        Handle double-click event on the Treeview.
        If the Reward ATA column is double-clicked, copy its value to the clipboard.
        """
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not item or not column:
            return
        column_index = int(column.replace('#', '')) -1
        if column_index == 2:  # 'Reward ATA' is the third column (index 2)
            ata = self.tree.set(item, "Reward ATA")
            self.root.clipboard_clear()
            self.root.clipboard_append(ata)
            messagebox.showinfo("Copied", f"Reward ATA '{ata}' copied to clipboard.")
    
    def on_right_click(self, event):
        """
        Handle right-click event on the Treeview to show a context menu.
        """
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)
    
    def copy_selected_ata(self):
        """
        Copy the Reward ATA of the selected row to the clipboard.
        """
        selected_items = self.tree.selection()
        if not selected_items:
            return
        for item in selected_items:
            ata = self.tree.set(item, "Reward ATA")
            self.root.clipboard_clear()
            self.root.clipboard_append(ata)
            messagebox.showinfo("Copied", f"Reward ATA '{ata}' copied to clipboard.")
    
    def show_error(self, title, message):
        """Safely display an error message from the asyncio thread."""
        self.root.after(0, lambda: messagebox.showerror(title, message))

def main():
    root = tk.Tk()
    app = TokenMonitorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()

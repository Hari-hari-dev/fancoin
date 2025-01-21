###########################################
# tk_onchain_playerlist.py
###########################################

import asyncio
import tkinter as tk
import traceback

###########################################
# 1) These lines mimic your existing script's globals + anchor setup
###########################################
from solders.pubkey import Pubkey
from anchorpy import Program, Provider, Wallet, Idl

program = None
provider = None
program_id = None
dapp_pda = None

###########################################
# 2) The function that fetches on-chain players
###########################################
async def get_all_onchain_players_alt() -> list[str]:
    """
    Original logic:
      - Uses program.account["PlayerPda"].all() to retrieve all PlayerPda accounts
      - Extracts the .name field from each record
    Returns a list of player names found on-chain.
    """
    global program
    if program is None:
        raise ValueError("Program is not initialized. Check anchor setup.")
    print("[DEBUG] Retrieving all PlayerPda accounts via anchorpy...")

    all_records = await program.account["PlayerPda"].all()
    print(f"[DEBUG] Found {len(all_records)} PlayerPda records on-chain.")

    # Extract the 'name' field from each player's account data
    player_names = []
    for record in all_records:
        account_data = record.account
        player_names.append(account_data.name)

    print(f"[DEBUG] Extracted {len(player_names)} player names from chain.")
    return player_names

def run_get_all_onchain_players_sync() -> list[str]:
    """
    Synchronously fetch the on-chain player list by
    running the async function in a local event loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(get_all_onchain_players_alt())
    except Exception as e:
        print("Error fetching on-chain players:", e)
        traceback.print_exc()
        return []
    finally:
        loop.close()

###########################################
# 3) The Tkinter GUI
###########################################
class PlayerListApp:
    def __init__(self, master, player_names: list[str]):
        """
        player_names is the raw list of on-chain names from get_all_onchain_players_alt().
        We'll build an ID -> Name mapping by enumerating them:
          { "0":"Alice", "1":"Bob", ... }
        so we can do substring searches on the ID.
        """
        self.master = master
        self.master.title("On-chain Player List - Search by ID")

        # Build dictionary: "id_str" -> name
        self.id_to_name = {}
        for i, pname in enumerate(player_names):
            self.id_to_name[str(i)] = pname

        self.build_gui()

    def build_gui(self):
        top_frame = tk.Frame(self.master)
        top_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(top_frame, text="Search ID#:").pack(side="left")

        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(top_frame, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", self.on_search)

        self.listbox = tk.Listbox(self.master, height=10)
        self.listbox.pack(fill="both", expand=True, padx=10, pady=5)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        self.detail_label = tk.Label(self.master, anchor="w")
        self.detail_label.pack(fill="x", padx=10, pady=5)

        # Initially show all IDs
        self.update_list(list(self.id_to_name.keys()))

    def on_search(self, event):
        query = self.search_var.get()
        if not query:
            # Show all
            self.update_list(list(self.id_to_name.keys()))
            return

        # Substring match on the "id_str"
        filtered = [id_str for id_str in self.id_to_name if query in id_str]
        self.update_list(filtered)

    def update_list(self, id_list):
        self.listbox.delete(0, tk.END)
        # Sort them by numeric ID
        sorted_ids = sorted(id_list, key=lambda x: int(x))
        for s in sorted_ids:
            self.listbox.insert(tk.END, s)

    def on_select(self, event):
        selection = event.widget.curselection()
        if not selection:
            return
        idx = selection[0]
        selected_id_str = event.widget.get(idx)
        name = self.id_to_name.get(selected_id_str, "Unknown")

        self.detail_label.config(
            text=f"ID: {selected_id_str}, Name: {name}"
        )

###########################################
# 4) The main flow that sets up Anchor + runs the Tk GUI
###########################################
def main():
    import sys
    import os
    from solana.rpc.async_api import AsyncClient
    from solana.rpc.commitment import Confirmed
    from anchorpy import Wallet, Provider

    global program, provider, program_id, dapp_pda

    # 1) Basic anchor setup
    print("[INFO] Setting up anchor environment...")

    try:
        client = AsyncClient("http://localhost:8899", commitment=Confirmed)
        wallet = Wallet.local()
        provider = Provider(client, wallet)

        # Load IDL from your 'fancoin.json' or similar
        from pathlib import Path
        idl_path = Path("../target/idl/fancoin.json")
        if not idl_path.exists():
            print(f"IDL file not found: {idl_path}")
            return

        with idl_path.open() as f:
            from anchorpy import Idl
            idl_json = f.read()
            idl = Idl.from_json(idl_json)

        from solders.pubkey import Pubkey
        program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")

        from anchorpy import Program
        program = Program(idl, program_id, provider)

        # (Optional) derive a DApp PDA if needed
        (dapp_pda, _) = Pubkey.find_program_address([b"dapp"], program_id)
        print(f"[DEBUG] dapp_pda => {dapp_pda}")

    except Exception as e:
        print("[ERROR] Anchor environment setup failed:", e)
        traceback.print_exc()
        return

    # 2) Now fetch the real on-chain players
    player_names = run_get_all_onchain_players_sync()
    if not player_names:
        print("No on-chain players found, or error occurred. Exiting.")
        return

    # 3) Launch the Tk GUI
    import tkinter
    root = tkinter.Tk()
    app = PlayerListApp(root, player_names)
    root.mainloop()

    # 4) Cleanup: close RPC client
    if provider and provider.connection:
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(provider.connection.close())
            loop.close()
        except:
            pass
    print("Closed RPC client. Exiting.")

if __name__ == "__main__":
    main()

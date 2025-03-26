import asyncio
import json
import re
import traceback
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from anchorpy import Program, Provider, Context, Idl
from anchorpy.provider import Wallet
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed

# --------------------------
# CONFIG & CONSTANTS
# --------------------------
RPC_URL = "http://localhost:8899"
PROGRAM_ID_STR = "HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut"

# The IDL path => update if your path differs:
IDL_PATH = Path("../target/idl/fancoin.json")

# The local .txt containing game + mint_authority PDAs
GAME_PDA_TXT = Path("game_pda.txt")
MINT_AUTH_PDA_TXT = Path("mint_auth_pda.txt")
MINTED_MINT_PDA_TXT = Path("minted_mint_pda.txt")
VALIDATOR_PDA_TXT = Path("validator_pda.txt")

# Name of the accounts in your IDL
GAME_STR = "Game"
PLAYER_PDA_STR = "PlayerPda"

# SPL Token Program (just an example ID)
SPL_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")

# -----------------------------------------------------------------------
# load_keypair
# -----------------------------------------------------------------------
def load_keypair(json_path: str = "val1-keypair.json") -> Keypair:
    data = json.loads(Path(json_path).read_text())
    return Keypair.from_bytes(bytes(data[:64]))

# -----------------------------------------------------------------------
# find_associated_token_address
# -----------------------------------------------------------------------
def find_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """
    Derive the Associated Token Account (ATA) for a given owner + mint.
    seeds = [owner, SPL_TOKEN_PROGRAM_ID, mint]
    """
    # If your code uses the standard "Associated Token Program" ID,
    # you might need to use ATokenGPv4k... instead. Adjust as needed.
    # For demonstration, we'll keep the same approach:
    from solders.pubkey import Pubkey
    ATA_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
    seeds = [bytes(owner), bytes(SPL_TOKEN_PROGRAM_ID), bytes(mint)]
    (ata, _) = Pubkey.find_program_address(seeds, ATA_PROGRAM_ID)
    return ata

# -----------------------------------------------------------------------
# get_balance_or_zero
# -----------------------------------------------------------------------
async def get_balance_or_zero(client: AsyncClient, ata_pubkey: Pubkey) -> float:
    """
    Returns the ui_amount (float) for a token account if it exists, else 0.0
    """
    try:
        resp = await client.get_token_account_balance(ata_pubkey)
        if resp.value:
            return resp.value.ui_amount or 0.0
    except Exception:
        pass
    return 0.0

# -----------------------------------------------------------------------
# fetch_paid_players
# -----------------------------------------------------------------------
async def fetch_paid_players(program: Program, game_pda: Pubkey):
    """Return a list of (player_pda_pubkey, player_account_data) for all who have pending_paid == True."""
    # If needed, you can fetch the game account here:
    # game_data = await program.account[GAME_STR].fetch(game_pda)

    all_player_records = await program.account[PLAYER_PDA_STR].all()

    paid_list = []
    for rec in all_player_records:
        acct = rec.account
        if acct.pending_paid is True:
            paid_list.append((rec.public_key, acct))

    return paid_list

# -----------------------------------------------------------------------
# _async_fetch_balances_with_commission
# -----------------------------------------------------------------------
async def _async_fetch_balances_with_commission():
    """
    Asynchronously:
      1) Connect to Solana
      2) Load IDL + Program
      3) Derive Commission ATA (validator's keypair + minted mint)
      4) Get Commission ATA balance
      5) Fetch 'paid_players' => each with a reward_address
      6) For each, fetch get_token_account_balance
      7) Return list of rows + top row for commission
    """
    client = AsyncClient(RPC_URL, commitment=Confirmed)
    validator_kp = load_keypair("val1-keypair.json")
    validator_wallet = Wallet(validator_kp)

    provider = Provider(client, validator_wallet)

    # Read IDL
    with IDL_PATH.open("r", encoding="utf-8") as f:
        idl_json = f.read()
    idl = Idl.from_json(idl_json)

    program_id = Pubkey.from_string(PROGRAM_ID_STR)
    program = Program(idl, program_id, provider)

    # Read game_pda + minted_mint
    if not GAME_PDA_TXT.exists() or not MINTED_MINT_PDA_TXT.exists():
        print("[ERROR] Missing game_pda.txt or minted_mint_pda.txt")
        await provider.connection.close()
        return []

    game_pda = Pubkey.from_string(GAME_PDA_TXT.read_text().strip())
    minted_mint = Pubkey.from_string(MINTED_MINT_PDA_TXT.read_text().strip())
    print(f"[INFO] game_pda={game_pda}")
    print(f"[INFO] minted_mint={minted_mint}")

    # Derive commission ATA based on the validator key
    commission_ata = find_associated_token_address(validator_kp.pubkey(), minted_mint)
    print(f"[INFO] Commission ATA => {commission_ata}")

    # 1) Fetch the commission ATA balance
    comm_balance = await get_balance_or_zero(client, commission_ata)

    # 2) Gather paid players + their balances
    paid_players = await fetch_paid_players(program, game_pda)
    print(f"[INFO] Found {len(paid_players)} players with pending_paid==true.")

    results = []
    # Top row => commission
    # We'll display "Commission ATA" as the "name" column
    # and the public key + balance
    results.append((
        "Commission ATA",
        str(commission_ata),
        f"{comm_balance}"
    ))

    # Then the rest => players
    for (player_pda_pubkey, acct) in paid_players:
        player_name_str = acct.name
        user_ata_pubkey = acct.reward_address

        if user_ata_pubkey is None or user_ata_pubkey == Pubkey.default():
            results.append((player_name_str, str(user_ata_pubkey), "No ATA"))
            continue

        # Try get the user ATA balance
        try:
            balance_resp = await provider.connection.get_token_account_balance(user_ata_pubkey)
            if balance_resp.value:
                ui_amount = balance_resp.value.ui_amount or 0.0
                results.append((player_name_str, str(user_ata_pubkey), f"{ui_amount}"))
            else:
                results.append((player_name_str, str(user_ata_pubkey), "N/A"))
        except Exception as e:
            results.append((player_name_str, str(user_ata_pubkey), f"Error: {e}"))

    # close connection
    await provider.connection.close()
    return results

def fetch_data_with_commission():
    """Synchronous wrapper that returns the list of (name, address, balance)."""
    return asyncio.run(_async_fetch_balances_with_commission())

# -----------------------------------------------------------------------
# TKINTER GUI
# -----------------------------------------------------------------------
def show_balances_in_tk():
    """
    Builds a simple Tkinter UI to show:
      1) Commission ATA + its balance (top row)
      2) Each "pending_paid" player's ATA + balance
      in a scrollable Treeview.
    """
    data = fetch_data_with_commission()

    root = tk.Tk()
    root.title("Paid Players & Commission ATA Balances")

    columns = ("Name", "Address / ATA", "Balance")
    tree = ttk.Treeview(root, columns=columns, show="headings", height=15)
    for col in columns:
        tree.heading(col, text=col)
        tree.column(col, width=250)  # adjust as desired

    # Scrollbar
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)

    # Place the scrollbar and tree side by side
    scrollbar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)

    # Insert rows
    for (name_str, addr_str, balance_str) in data:
        tree.insert("", "end", values=(name_str, addr_str, balance_str))

    # Start
    root.mainloop()


if __name__ == "__main__":
    show_balances_in_tk()

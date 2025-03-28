import asyncio
import json
import traceback
import re
from pathlib import Path

from anchorpy import Program, Provider, Context, Idl
from anchorpy.provider import Wallet
from anchorpy.program.namespace.instruction import AccountMeta
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed

# --------------------------
# CONFIG & CONSTANTS
# --------------------------
RPC_URL = "http://localhost:8899"
PROGRAM_ID_STR = "HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut"

# The IDL path => update if your path differs:
IDL_PATH = Path("../target/idl/fancoin.json")

# The local .txt containing dapp + mint_authority PDAs
DAPP_PDA_TXT = Path("dapp_pda.txt")
MINT_AUTH_PDA_TXT = Path("mint_auth_pda.txt")
MINTED_MINT_PDA_TXT = Path("minted_mint_pda.txt")

# We'll also store a "validator_pda.txt" if your code does so:
VALIDATOR_PDA_TXT = Path("validator_pda.txt")

# Name of the account => "PlayerPda"
PLAYER_PDA_STR = "PlayerPda"
DAPP_STR = "Dapp"

# Regex to parse "Program X consumed N of M compute units"
CU_REGEX = re.compile(r"Program \S+ consumed (\d+) of (\d+) compute units")

SPL_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL") 
# Replace with the real Associated Token Program ID if not done yet

# -----------------------------------------------------------------------
# HELPER: find_associated_token_address
# -----------------------------------------------------------------------
def find_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """
    Derive the Associated Token Account (ATA) for a given owner + mint.
    This uses the standard approach:
      seeds = [wallet_pubkey, SPL_TOKEN_PROGRAM_ID, mint_pubkey]
      program_id = Associated Token Program
    """
    seeds = [
        bytes(owner),
        bytes(SPL_TOKEN_PROGRAM_ID),
        bytes(mint)
    ]
    (ata, _) = Pubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
    return ata

# -----------------------------------------------------------------------
# load_keypair
# -----------------------------------------------------------------------
def load_keypair(json_path: str = "val1-keypair.json") -> Keypair:
    data = json.loads(Path(json_path).read_text())
    return Keypair.from_bytes(bytes(data[:64]))

# -----------------------------------------------------------------------
# get_balance_or_zero
# -----------------------------------------------------------------------
async def get_balance_or_zero(client: AsyncClient, ata_pubkey: Pubkey) -> float:
    """
    Returns the ui_amount for a token account if it exists, else 0.0
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
async def fetch_paid_players(program: Program, dapp_pda: Pubkey):
    """
    Return a list of tuples: (public_key_of_player_pda, player_account_data)
    where pending_paid == True.
    """
    # Not strictly necessary to read the dapp, but if you need it:
    dapp_data = await program.account[DAPP_STR].fetch(dapp_pda)
    total_count = dapp_data.player_count

    all_player_records = await program.account[PLAYER_PDA_STR].all()
    paid_list = []
    for rec in all_player_records:
        acct = rec.account
        if acct.pending_paid is True:
            paid_list.append((rec.public_key, acct))

    return paid_list

# -----------------------------------------------------------------------
# validate_player_pubg_time_slim
# -----------------------------------------------------------------------
async def validate_player_pubg_time_slim(
    program: Program,
    dapp_pda: Pubkey,
    validator_kp: Keypair,
    system_program_id: Pubkey,
    player_name_pda: Pubkey,
    player_pda: Pubkey,
    fancy_mint: Pubkey,
    mint_authority: Pubkey,
    user_ata: Pubkey,
    validator_pda: Pubkey,
    name_str: str,
    new_time_seconds: int,
    commission_ata: Pubkey = None,
):
    """
    Calls validate_player_pubg_time_slim(mint_pubkey, name, new_time_seconds).
    leftover:
      [0] => player_name_pda
      [1] => player_pda
      [2] => fancy_mint
      [3] => mint_authority
      [4] => user_ata
      [5] => validator_pda
      [6] => commission_ata (optional)
    """
    leftover = [
        AccountMeta(pubkey=player_name_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=player_pda,       is_signer=False, is_writable=True),
        AccountMeta(pubkey=fancy_mint,       is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint_authority,   is_signer=False, is_writable=False),
        AccountMeta(pubkey=user_ata,         is_signer=False, is_writable=True),
        AccountMeta(pubkey=validator_pda,    is_signer=False, is_writable=True),
    ]

    # If we have a commission_ata, push it in leftover[6]
    if commission_ata is not None:
        leftover.append(AccountMeta(pubkey=commission_ata, is_signer=False, is_writable=True))

    ctx = Context(
        accounts={
            "dapp": dapp_pda,
            "validator": validator_kp.pubkey(),
            "token_program": SPL_TOKEN_PROGRAM_ID,
            "system_program": system_program_id,
        },
        signers=[validator_kp],
        remaining_accounts=leftover,
    )

    tx_sig = await program.rpc["validate_player_pubg_time_slim"](
        fancy_mint,  
        name_str,
        new_time_seconds,
        ctx=ctx
    )
    return tx_sig

# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------
async def main():
    print("[INFO] Starting script...")

    # 1) Setup client + read IDL
    client = AsyncClient(RPC_URL, commitment=Confirmed)
    validator_kp = load_keypair("val1-keypair.json")
    validator_wallet = Wallet(validator_kp)

    provider = Provider(client, validator_wallet)

    with IDL_PATH.open("r", encoding="utf-8") as f:
        idl_json = f.read()
    idl = Idl.from_json(idl_json)

    program_id = Pubkey.from_string(PROGRAM_ID_STR)
    program = Program(idl, program_id, provider)

    # 2) Read the PDAs
    if not DAPP_PDA_TXT.exists() or not MINTED_MINT_PDA_TXT.exists() or not MINT_AUTH_PDA_TXT.exists():
        print("[ERROR] Missing one of the necessary .txt files: dapp_pda, minted_mint_pda, mint_auth_pda.")
        return

    dapp_pda = Pubkey.from_string(DAPP_PDA_TXT.read_text().strip())
    minted_mint = Pubkey.from_string(MINTED_MINT_PDA_TXT.read_text().strip())
    mint_auth_pda = Pubkey.from_string(MINT_AUTH_PDA_TXT.read_text().strip())
    print(f"[INFO] dapp_pda={dapp_pda}")
    print(f"[INFO] minted_mint={minted_mint}")
    print(f"[INFO] mint_auth_pda={mint_auth_pda}")

    # Optionally load the validator_pda
    if VALIDATOR_PDA_TXT.exists():
        validator_pda = Pubkey.from_string(VALIDATOR_PDA_TXT.read_text().strip())
    else:
        print("[WARN] No validator_pda.txt found; re-deriving with minted_mint + validator_pubkey.")
        (validator_pda, _) = Pubkey.find_program_address(
            [b"validator", bytes(minted_mint), bytes(validator_kp.pubkey())],
            program_id
        )

    # If you want to derive a commission ATA for *some* owner. Let's assume it's the validator’s pubkey:
    # If your code sets `dapp.commission_percent > 0`, your on-chain program will handle it.
    commission_ata = find_associated_token_address(validator_kp.pubkey(), minted_mint)
    print(f"[INFO] Commission ATA = {commission_ata}")

    # 3) fetch players who have pending_paid == true
    paid_players = await fetch_paid_players(program, dapp_pda)
    if not paid_players:
        print("[INFO] No players with pending_paid == true. Exiting.")
        await provider.connection.close()
        return

    print(f"[INFO] Found {len(paid_players)} players with pending_paid==true.")
    
    # 4) Ask once for the new_time_seconds
    user_input = input("Enter new_time_seconds for ALL players (blank to skip): ").strip()
    if not user_input:
        print("[SKIP] No input => skipping all players.")
        await provider.connection.close()
        return

    try:
        new_time_seconds = int(user_input)
    except ValueError:
        print("[ERROR] Invalid integer => cannot proceed.")
        await provider.connection.close()
        return

    # 5) For each player => call validate + show minted amounts
    for (player_pda_pubkey, acct) in paid_players:
        player_name_str = acct.name
        print("-----------------------------------------------")
        print(f"Player = {player_name_str}")
        print(f"player_pda_pubkey = {player_pda_pubkey}")
        print(f"pending_dapp_time_ms= {acct.pending_dapp_time_ms}, last_claim_ts={acct.last_claim_ts}")

        # Derive leftover accounts
        (player_name_pda, _bump) = Pubkey.find_program_address(
            [b"player_name", bytes(dapp_pda), player_name_str.encode("utf-8")],
            program_id
        )
        user_ata_pubkey = acct.reward_address

        # Fetch balances BEFORE
        before_user_balance = await get_balance_or_zero(client, user_ata_pubkey)
        before_comm_balance = await get_balance_or_zero(client, commission_ata)

        # Perform the instruction
        try:
            tx_sig = await validate_player_pubg_time_slim(
                program=program,
                dapp_pda=dapp_pda,
                validator_kp=validator_kp,
                system_program_id=SYS_PROGRAM_ID,
                player_name_pda=player_name_pda,
                player_pda=player_pda_pubkey,
                fancy_mint=minted_mint,
                mint_authority=mint_auth_pda,
                user_ata=user_ata_pubkey,
                validator_pda=validator_pda,
                name_str=player_name_str,
                new_time_seconds=new_time_seconds,
                commission_ata=commission_ata,  # <-- pass it in
            )
            print(f"[SUCCESS] => TX Sig = {tx_sig}")

            # parse logs => compute units
            tx_details = await provider.connection.get_transaction(
                tx_sig, 
                commitment=Confirmed, 
                encoding='json'
            )
            if tx_details.value and tx_details.value.transaction.meta:
                logs = tx_details.value.transaction.meta.log_messages or []
                print("[DEBUG] Transaction Logs:")
                for line in logs:
                    print("  ", line)
                    match_cu = CU_REGEX.search(line)
                    if match_cu:
                        consumed = match_cu.group(1)
                        limit = match_cu.group(2)
                        print(f"    => [CU] consumed {consumed} of {limit} compute units")
            else:
                print("[DEBUG] No transaction meta/logs found.")

        except Exception as e:
            print(f"[ERROR] => {e}")
            traceback.print_exc()
            continue

        # Fetch balances AFTER
        after_user_balance = await get_balance_or_zero(client, user_ata_pubkey)
        after_comm_balance = await get_balance_or_zero(client, commission_ata)

        user_minted = after_user_balance - before_user_balance
        comm_minted = after_comm_balance - before_comm_balance

        print(f"Minted to {player_name_str} => {user_minted} tokens (in user_ata)")
        print(f"Minted to Commission    => {comm_minted} tokens (in commission_ata)")

    # Done
    await provider.connection.close()
    print("[INFO] Completed all players.")


if __name__ == "__main__":
    asyncio.run(main())

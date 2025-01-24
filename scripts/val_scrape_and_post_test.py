import asyncio
import socket
import struct
import a2s
import re
import json
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from pathlib import Path
from enum import IntEnum
import traceback
import json
import os
# anchorpy
from anchorpy import Program, Provider, Wallet, Idl, Context
from anchorpy.program.namespace.instruction import AccountMeta

# solana / solders
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException

# Constants
SPL_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

class GameStatus(IntEnum):
    Probationary = 0
    Whitelisted = 1
    Blacklisted = 2
###############################################################################
# 1) Load Validator Keypair
###############################################################################
def load_validator_keypair(filename="val1-keypair.json") -> Keypair:
    """Load from raw 64-byte secret in a JSON array, e.g. [12,34,56,...]."""
    def load_keypair(path: str) -> Keypair:
        with Path(path).open() as f:
            secret = json.load(f)
        return Keypair.from_bytes(bytes(secret[0:64]))
    return load_keypair(filename)

###############################################################################
# 2) Debug-check DApp
###############################################################################
async def debug_check_dapp_pda():
    dapp_data = await program.account["DApp"].fetch(dapp_pda)
    print("[DEBUG] DApp Account Data:")
    print(f"         owner                = {dapp_data.owner}")
    print(f"         global_player_count  = {dapp_data.global_player_count}")
    print(f"         mint_pubkey         = {dapp_data.mint_pubkey}")

###############################################################################
# 3) On-chain fetch: build name -> { index, pda, reward_address }
###############################################################################
async def fetch_player_pdas_map() -> dict:
    """
    Returns a dict:
      {
         "<player_name>": {
            "index":  <u32 index in the anchor code>,
            "pda":    <Pubkey for PlayerPda>,
            "reward_address": <Pubkey for TokenAccount>
         },
         ...
      }
    
    We assume seeds=[b"player_pda", i32_as_le_bytes] for each new player.
    We'll re-derive each player's address to figure out their 'index'.
    """
    all_records = await program.account["PlayerPda"].all()
    print(f"[DEBUG] Found {len(all_records)} PlayerPda records on-chain.")

    # Fetch DApp data to get total player count
    dapp_data = await program.account["DApp"].fetch(dapp_pda)
    total_count = dapp_data.global_player_count

    # Derive PDA to index mapping
    pda_to_index = {}
    for i in range(total_count):
        seed_index_bytes = i.to_bytes(4, "little")
        (pda, _) = Pubkey.find_program_address([b"player_pda", seed_index_bytes], program.program_id)
        pda_to_index[str(pda)] = i

    # Build the name map with reward_address
    name_map = {}
    for rec in all_records:
        pkey_str = str(rec.public_key)
        if pkey_str in pda_to_index:
            real_idx = pda_to_index[pkey_str]
            player_name = rec.account.name  # The "name" field on your PlayerPda
            name_map[player_name] = {
                "index": real_idx,
                "pda": rec.public_key,
                "reward_address": rec.account.reward_address  # Added reward_address
            }
        else:
            # Handle any leftover or mismatched records if necessary
            pass

    return name_map

def find_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """
    Derive the Associated Token Account (ATA) for a given owner and mint.
    """
    return Pubkey.find_program_address(
        [
            owner.to_bytes(),
            SPL_TOKEN_PROGRAM_ID.to_bytes(),
            mint.to_bytes()
        ],
        ASSOCIATED_TOKEN_PROGRAM_ID
    )[0]

async def initialize_dapp(program: Program, client: AsyncClient) -> Pubkey:
    """Initialize the DApp, returning the DApp PDA."""
    print("Initializing DApp account...")
    dapp_pda, dapp_bump = Pubkey.find_program_address([b"dapp"], program.program_id)
    print(f"DApp PDA: {dapp_pda}, Bump: {dapp_bump}")

    # Check if DApp account already exists
    dapp_account = await client.get_account_info(dapp_pda, commitment=Confirmed)
    if dapp_account.value is None:
        try:
            tx = await program.rpc["initialize_dapp"](
                ctx=Context(
                    accounts={
                        "dapp": dapp_pda,
                        "user": program.provider.wallet.public_key,
                        "system_program": SYS_PROGRAM_ID,
                    },
                    signers=[program.provider.wallet.payer],
                )
            )
            print(f"DApp initialized successfully. Transaction Signature: {tx}")
        except RPCException as e:
            print(f"Error initializing DApp: {e}")
            traceback.print_exc()
            raise
    else:
        print("DApp account already exists. Skipping initialization.")

    return dapp_pda

async def initialize_mint(program: Program, client: AsyncClient, dapp_pda: Pubkey) -> (Pubkey, Pubkey):
    """
    Initialize the Mint for the DApp, returning (mint_authority_pda, mint_for_dapp_pda).
    Sets dapp.mint_pubkey on-chain.
    """
    print("\nInitializing Mint for DApp...")

    # seeds for each PDA
    mint_authority_pda, _ = Pubkey.find_program_address([b"mint_authority"], program.program_id)
    mint_for_dapp_pda, _  = Pubkey.find_program_address([b"my_spl_mint"], program.program_id)

    # Check if they might already exist
    mint_auth_acct = await client.get_account_info(mint_authority_pda, commitment=Confirmed)
    mint_acct      = await client.get_account_info(mint_for_dapp_pda, commitment=Confirmed)
    if mint_auth_acct.value is not None and mint_acct.value is not None:
        print("Mint + MintAuthority accounts already exist; skipping.")
        return (mint_authority_pda, mint_for_dapp_pda)

    try:
        token_pid = SPL_TOKEN_PROGRAM_ID

        tx = await program.rpc["initialize_mint"](
            ctx=Context(
                accounts={
                    "dapp":            dapp_pda,
                    "mint_authority":  mint_authority_pda,
                    "mint_for_dapp":   mint_for_dapp_pda,
                    "payer":           program.provider.wallet.public_key,
                    "token_program":   token_pid,
                    "system_program":  SYS_PROGRAM_ID,
                    "rent": Pubkey.from_string("SysvarRent111111111111111111111111111111111"),
                },
                signers=[program.provider.wallet.payer],
            )
        )
        print(f"InitializeMint => Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error initializing the mint: {e}")
        traceback.print_exc()
        raise

    return (mint_authority_pda, mint_for_dapp_pda)

async def initialize_game(
    program: Program, client: AsyncClient, game_number: int, description: str, dapp_pda: Pubkey
) -> Pubkey:
    """Initialize the Game, returning the Game PDA."""
    print("\nInitializing Game account...")
    game_pda, game_bump = Pubkey.find_program_address(
        [b"game", game_number.to_bytes(4, "little")], program.program_id
    )
    print(f"Game PDA: {game_pda}, Bump: {game_bump}")

    game_account = await client.get_account_info(game_pda, commitment=Confirmed)
    if game_account.value is None:
        try:
            tx = await program.rpc["initialize_game"](
                game_number,
                description,
                ctx=Context(
                    accounts={
                        "game": game_pda,
                        "dapp": dapp_pda,
                        "user": program.provider.wallet.public_key,
                        "system_program": SYS_PROGRAM_ID,
                    },
                    signers=[program.provider.wallet.payer],
                )
            )
            print(f"Game initialized successfully. Transaction Signature: {tx}")
        except RPCException as e:
            print(f"Error initializing Game: {e}")
            traceback.print_exc()
            raise
    else:
        print("Game account already exists. Skipping initialization.")

    return game_pda

async def register_validator_pda(
    program: Program,
    client: AsyncClient,
    game_pda: Pubkey,
    game_number: int,
    validator_kp: Keypair
) -> Pubkey:
    """Create a new validator PDA for the given user-based seeds."""
    print("\nRegistering a new Validator PDA (user-based seeds)...")
    game_number_bytes = game_number.to_bytes(4, "little")
    validator_key_bytes = bytes(validator_kp.pubkey())
    seeds = [b"validator", game_number_bytes, validator_key_bytes]
    validator_pda, validator_pda_bump = Pubkey.find_program_address(seeds, program.program_id)
    print(f"[DEBUG] Derived validator_pda = {validator_pda}, Bump = {validator_pda_bump}")

    try:
        tx_sig = await program.rpc["register_validator_pda"](
            game_number,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "validator_pda": validator_pda,
                    "user": validator_kp.pubkey(),
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[validator_kp],
            )
        )
        print(f"ValidatorPda registered. Tx Sig: {tx_sig}")
    except RPCException as e:
        print(f"Error registering Validator PDA: {e}")
        traceback.print_exc()
        raise

    return validator_pda

async def punch_in(program: Program, game_pda: Pubkey, game_number: int, validator_kp: Keypair, validator_pda: Pubkey):
    """Punch in as validator for the given game."""
    print("\nPunching In as Validator...")
    try:
        tx = await program.rpc["punch_in"](
            game_number,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "validator_pda": validator_pda,  # Added validator_pda
                    "validator": validator_kp.pubkey(),
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[validator_kp],
            )
        )
        print(f"Punched in successfully. Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error punching in: {e}")
        traceback.print_exc()
        raise

async def register_player_pda(
    program: Program,
    client: AsyncClient,
    dapp_pda: Pubkey,
    name: str,
    fancy_mint: Pubkey,  # Add this parameter
):
    """Register a PlayerPda using the dapp.global_player_count approach."""
    print("\nRegistering a new Player PDA...")

    # 1) Fetch the DApp to get global_player_count
    dapp_data = await program.account["DApp"].fetch(dapp_pda)
    current_count = dapp_data.global_player_count
    print(f"[DEBUG] dapp.global_player_count = {current_count}")

    # 2) Derive the new player_pda
    player_pda, p_bump = Pubkey.find_program_address(
        [b"player_pda", current_count.to_bytes(4, "little")],
        program.program_id
    )
    print(f"[DEBUG] Derived player_pda = {player_pda}, Bump = {p_bump}")

    # 3) Derive the user's ATA using the custom function
    user_pubkey = program.provider.wallet.public_key
    user_ata = find_associated_token_address(user_pubkey, fancy_mint)
    print(f"[DEBUG] Derived user_ata = {user_ata}")

    # 4) Verify the ATA exists and is owned by the Token program
    account_info = await client.get_account_info(user_ata, commitment=Confirmed)
    if account_info.value is None:
        print(f"[ERROR] ATA {user_ata} does not exist. It should have been created during registration.")
        return
    owner = Pubkey.from_bytes(account_info.value.owner)
    if owner != SPL_TOKEN_PROGRAM_ID:
        print(f"[ERROR] ATA {user_ata} is not owned by the SPL Token program. Owner: {owner}")
        return
    print(f"[DEBUG] Verified ATA {user_ata} exists and is owned by the SPL Token program.")

    try:
        tx_sig = await program.rpc["register_player_pda"](
            name,
            ctx=Context(
                accounts={
                    "dapp": dapp_pda,
                    "fancy_mint": fancy_mint,               # Pass fancy_mint
                    "player_pda": player_pda,
                    "user": user_pubkey,
                    "user_ata": user_ata,                   # Pass user_ata
                    "token_program": SPL_TOKEN_PROGRAM_ID,
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                    "rent": Pubkey.from_string("SysvarRent111111111111111111111111111111111"),
                },
                signers=[program.provider.wallet.payer],
            )
        )
        print(f"PlayerPda '{name}' created => {player_pda}. Tx Sig: {tx_sig}")
    except RPCException as e:
        print(f"Error registering PlayerPda '{name}': {e}")
        traceback.print_exc()
        raise

async def submit_minting_list_with_leftover(
    program: Program,
    dapp_pda: Pubkey,
    game_pda: Pubkey,
    game_number: int,
    validator_kp: Keypair,
    validator_pda: Pubkey,
    fancy_mint: Pubkey,
    mint_auth_pda: Pubkey,
    leftover_player_pda: Pubkey,
    leftover_player_ata: Pubkey,
):
    """
    Example usage: single leftover (PlayerPda, ATA) => one "player_id".
    The on-chain code expects leftover=2 per player => [PlayerPda, ATA].
    
    NOTE: Mark the PlayerPda leftover as `is_writable=True` so we can update it on-chain.
    """
    print("\nSubmitting Minting List => leftover [PlayerPda, ATA]...")

    # leftover => 2 per player
    leftover_accounts = [
        # IMPORTANT: Mark the PlayerPda as is_writable=True
        AccountMeta(pubkey=leftover_player_pda, is_signer=False, is_writable=True),
        # The ATA also needs to be writable if we do a `mint_to` on it
        AccountMeta(pubkey=leftover_player_ata, is_signer=False, is_writable=True),
    ]

    # We'll pass a single "player_id"
    player_ids = [1]  # example

    try:
        token_pid = SPL_TOKEN_PROGRAM_ID

        tx_sig = await program.rpc["submit_minting_list"](
            game_number,
            player_ids,
            ctx=Context(
                accounts={
                    "game":           game_pda,
                    "validator_pda":  validator_pda,
                    "validator":      validator_kp.pubkey(),
                    "fancy_mint":     fancy_mint,
                    "dapp":           dapp_pda,
                    "mint_authority": mint_auth_pda,
                    "token_program":  token_pid,
                },
                signers=[validator_kp],
                remaining_accounts=leftover_accounts,
            ),
        )
        print(f"Minting list submitted. Tx: {tx_sig}")
    except RPCException as e:
        print(f"Error in submit_minting_list: {e}")
        traceback.print_exc()

async def verify_ata(client: AsyncClient, ata_pubkey: Pubkey) -> bool:
    """Verify that the ATA exists and is owned by the SPL Token program."""
    account_info = await client.get_account_info(ata_pubkey, commitment=Confirmed)
    if account_info.value is None:
        print(f"[ERROR] ATA {ata_pubkey} does not exist.")
        return False
    owner = Pubkey.from_bytes(account_info.value.owner)
    if owner != SPL_TOKEN_PROGRAM_ID:
        print(f"[ERROR] ATA {ata_pubkey} is not owned by the SPL Token program. Owner: {owner}")
        return False
    print(f"[DEBUG] Verified ATA {ata_pubkey} exists and is owned by the SPL Token program.")
    return True

async def fetch_player_pdas_map(program: Program, dapp_pda: Pubkey) -> dict:
    """
    Returns a dict:
      {
         "<player_name>": {
            "index":  <u32 index in the anchor code>,
            "pda":    <Pubkey for PlayerPda>,
            "reward_address": <Pubkey for TokenAccount>
         },
         ...
      }
    """
    all_records = await program.account["PlayerPda"].all()
    print(f"[DEBUG] Found {len(all_records)} PlayerPda records on-chain.")

    # Fetch DApp data to get total player count
    dapp_data = await program.account["DApp"].fetch(dapp_pda)
    total_count = dapp_data.global_player_count

    # Derive PDA to index mapping
    pda_to_index = {}
    for i in range(total_count):
        seed_index_bytes = i.to_bytes(4, "little")
        (pda, _) = Pubkey.find_program_address([b"player_pda", seed_index_bytes], program.program_id)
        pda_to_index[str(pda)] = i

    # Build the name map with reward_address
    name_map = {}
    for rec in all_records:
        pkey_str = str(rec.public_key)
        if pkey_str in pda_to_index:
            real_idx = pda_to_index[pkey_str]
            player_name = rec.account.name  # The "name" field on your PlayerPda
            name_map[player_name] = {
                "index": real_idx,
                "pda": rec.public_key,
                "reward_address": rec.account.reward_address  # Added reward_address
            }
        else:
            # Handle any leftover or mismatched records if necessary
            pass

    return name_map

async def submit_minting_list_with_leftover(
    game_number: int,
    matched_names: list[str],
    name_map: dict,
):
    """
    This breaks the matched names into chunks of CHUNK_SIZE (3 here).
    For each chunk, we:
     1) Build numeric player_ids (u32),
     2) Pass actual PlayerPda and reward_address (ATA),
     3) Call `submit_minting_list`.
    """
    validator_kp = load_validator_keypair()
    validator_pubkey = validator_kp.pubkey()

    # Derive the validator_pda
    seeds_val = [b"validator", game_number.to_bytes(4, "little"), bytes(validator_pubkey)]
    (validator_pda, bump_val) = Pubkey.find_program_address(seeds_val, program.program_id)

    # Fetch DApp's mint_pubkey
    dapp_data = await program.account["DApp"].fetch(dapp_pda)
    fancy_mint_pk = dapp_data.mint_pubkey

    # Derive mint_authority
    (mint_auth_pda, bump_mint_auth) = Pubkey.find_program_address([b"mint_authority"], program_id)

    # SysvarRent
    rent_sysvar_pubkey = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

    # Initialize validator_pda if not already initialized
    try:
        await program.account["ValidatorPda"].fetch(validator_pda)
        print(f"[DEBUG] validator_pda {validator_pda} already initialized.")
    except:
        print(f"[INFO] validator_pda {validator_pda} not found. Initializing...")
        ctx_init_val = Context(
            accounts={
                "game": game_pda,
                "validator_pda": validator_pda,
                "validator": validator_pubkey,
                "user": validator_kp,  # Ensure the validator keypair is a signer
                "system_program": SYS_PROGRAM_ID,
            },
            signers=[validator_kp],
        )
        # Invoke the register_validator_pda instruction
        try:
            tx_sig_init_val = await program.rpc["register_validator_pda"](
                game_number,
                ctx_init_val
            )
            print(f"[INFO] Registered validator_pda. Tx Sig: {tx_sig_init_val}")
        except RPCException as e:
            print(f"[ERROR] Failed to register validator_pda: {e}")
            traceback.print_exc()
            return  # Exit the function as further steps depend on this

    # Iterate over matched names in chunks
    for start_idx in range(0, len(matched_names), CHUNK_SIZE):
        chunk = matched_names[start_idx : start_idx + CHUNK_SIZE]
        leftover_accounts = []
        numeric_ids = []

        for name in chunk:
            # Look up the player's index + pda + reward_address
            entry = name_map.get(name)
            if entry is None:
                print(f"[WARN] Name={name} not found in name_map. Skipping.")
                continue

            pid = entry["index"]
            player_pda_pubkey = entry["pda"]
            reward_address_pubkey = entry["reward_address"]

            # Append the actual PlayerPda and reward_address (ATA)
            leftover_accounts.append(
                AccountMeta(pubkey=player_pda_pubkey, is_signer=False, is_writable=True)
            )
            leftover_accounts.append(
                AccountMeta(pubkey=reward_address_pubkey, is_signer=False, is_writable=True)
            )
            numeric_ids.append(pid)

        if not numeric_ids:
            print(f"[DEBUG] This chunk is empty, skipping.")
            continue

        print(f"[DEBUG] Submitting chunk => {numeric_ids}")

        # Build AnchorPy Context
        ctx = Context(
            accounts={
                "game":           game_pda,
                "validator_pda":  validator_pda,
                "validator":      validator_pubkey,
                "fancy_mint":     fancy_mint_pk,
                "dapp":           dapp_pda,
                "mint_authority": mint_auth_pda,
                "token_program":  SPL_TOKEN_PROGRAM_ID,
                "rent":           rent_sysvar_pubkey,
                "system_program": SYS_PROGRAM_ID,
                "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
            },
            signers=[validator_kp],
            remaining_accounts=leftover_accounts
        )

        # Call your on-chain `submit_minting_list` instruction
        try:
            tx_sig = await program.rpc["submit_minting_list"](
                game_number,
                numeric_ids,
                ctx=ctx
            )
            print(f"[INFO] submit_minting_list TX => {tx_sig}")

            # Optionally fetch logs
            confirmed_tx = await program.provider.connection.get_transaction(tx_sig, encoding="json")
            if confirmed_tx.value and confirmed_tx.value.transaction.meta:
                logs = confirmed_tx.value.transaction.meta.log_messages or []
                print("[DEBUG] Logs from this chunk's TX:")
                for line in logs:
                    print("   ", line)
            else:
                print("[DEBUG] No logs found or missing transaction meta.")

        except RPCException as exc:
            print(f"[ERROR] chunk submission => {exc}")
            # Optionally, you might want to continue or handle specific errors
            continue

        # Sleep a tiny bit if you want to throttle
        await asyncio.sleep(0.2)

###############################################################################
# 5) Local TFC logic: gather local players from master server
###############################################################################
def parse_response(data):
    servers = []
    for i in range(6, len(data), 6):
        ip = ".".join(map(str, data[i : i + 4]))
        port = struct.unpack(">H", data[i + 4 : i + 6])[0]
        if ip == "0.0.0.0" and port == 0:
            break
        servers.append((ip, port))
    return servers

def query_master_server(region, app_id):
    master_server = ("hl1master.steampowered.com", 27011)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    request = b"\x31\xFF0.0.0.0:0\x00\\gamedir\\tfc\x00"
    response_data = b''

    while True:
        sock.sendto(request, master_server)
        try:
            response_data, _ = sock.recvfrom(4096)
        except socket.timeout:
            print("Request timed out")
            break

        servers = parse_response(response_data)
        if not servers:
            break
        for srv in servers:
            yield srv

def clean_brackets_and_contents(name):
    name = re.sub(r'\^\d', '', name)
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\{.*?\}', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'<.*?>', '', name)
    name = re.sub(r'[\[\]\{\}\(\)<>]', '', name)
    name = re.sub(r'[^a-zA-Z0-9_-]', '', name)
    return name.strip()

def get_player_list_a2s(ip, port):
    import a2s
    try:
        address = (ip, port)
        players = a2s.players(address)
        return players
    except Exception as e:
        print(f"Failed to query server at {ip}:{port}: {e}")
        return []

def decode_and_collect_players(players):
    """
    Returns a dict: name->some placeholder data. 
    We only care about the name keys to match on on-chain records.
    """
    player_data = {}
    for pl in players:
        sanitized_name = clean_brackets_and_contents(pl.name)
        if sanitized_name:
            # We store it in a dict just so we can get distinct names
            player_data[sanitized_name] = True
    return player_data

###############################################################################
# 6) The main function that merges everything
###############################################################################
async def main():
    try:
        print("Setting up provider and loading program IDL...")
        client = AsyncClient("http://localhost:8899", commitment=Confirmed)
        wallet = Wallet.local()

        global provider, program, program_id, dapp_pda, game_pda
        provider = Provider(client, wallet)

        # ───────────────────────────────────────────────────────────
        # Load Validator Keypair (for checking balance)
        validator_kp = load_validator_keypair()
        validator_pubkey = validator_kp.pubkey()
        # ───────────────────────────────────────────────────────────

        # 1) Load the IDL
        idl_path = Path("../target/idl/fancoin.json")
        if not idl_path.exists():
            print(f"[ERROR] IDL file not found at {idl_path.resolve()}")
            return

        with idl_path.open() as f:
            idl_json = f.read()

        program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
        idl = Idl.from_json(idl_json)
        program = Program(idl, program_id, provider)
        print("Program loaded successfully.")

        # 2) Derive PDAs
        game_number = 1
        (game_pda, bump_game) = Pubkey.find_program_address(
            [b"game", game_number.to_bytes(4, "little")], program_id
        )
        (dapp_pda, bump_dapp) = Pubkey.find_program_address([b"dapp"], program_id)
        print(f"[DEBUG] using game_pda={game_pda}")
        print(f"[DEBUG] using dapp_pda={dapp_pda}")

        # 3) Debug-check DApp
        await debug_check_dapp_pda()
        balance_resp = await provider.connection.get_balance(validator_pubkey)
        lamports = balance_resp.value
        sol_balance = lamports / 1e9
        print(f"[INFO] Validator balance: {sol_balance} SOL")
        # 4) Query TFC master server for a list of servers
        print("[INFO] Querying TFC master server for a list of servers.")
        region = 0xFF
        app_id = 20
        tfc_servers = list(query_master_server(region, app_id))
        unique_ips = {}
        for ip, port in tfc_servers:
            if ip not in unique_ips:
                unique_ips[ip] = (ip, port)
        deduped = list(unique_ips.values())
        print(f"[DEBUG] Found {len(deduped)} unique TFC servers.")
        aggregated_local_server_names = set()

        # 5) Fetch all on-chain PlayerPda => build (name -> index, name -> pda, reward_address)
        print("[INFO] Fetching on-chain name->(index, pda, reward_address).")
        name_map = await fetch_player_pdas_map(program, dapp_pda)

        # 6) Register a validator if not already registered
        try:
            await program.account["ValidatorPda"].fetch(validator_pda)
            print(f"[DEBUG] validator_pda {validator_pda} already initialized.")
        except:
            print(f"[INFO] validator_pda {validator_pda} not found. Initializing...")
            try:
                tx_sig_init_val = await program.rpc["register_validator_pda"](
                    game_number,
                    ctx=Context(
                        accounts={
                            "game": game_pda,
                            "validator_pda": validator_pda,
                            "validator": validator_pubkey,
                            "user": validator_kp,
                            "system_program": SYS_PROGRAM_ID,
                        },
                        signers=[validator_kp],
                    )
                )
                print(f"[INFO] Registered validator_pda. Tx Sig: {tx_sig_init_val}")
            except RPCException as e:
                print(f"[ERROR] Failed to register validator_pda: {e}")
                traceback.print_exc()
                return  # Exit the function as further steps depend on this

        # 7) Punch in as validator
        await punch_in(program, game_pda, game_number, validator_kp, validator_pda)  # Pass validator_pda

        # 8) Register a new Player
        player_kp = load_keypair("./player-keypair.json")
        # No need to specify reward_address; it will be set to user_ata
        await register_player_pda(
            program, client, dapp_pda,
            name="Alice",
            fancy_mint=mint_for_dapp_pda  # Pass the mint pubkey here
        )

        # 9) Derive Alice's PlayerPda and ATA
        # Assuming Alice is the first player, index = 0
        alice_pda, _ = Pubkey.find_program_address(
            [b"player_pda", (0).to_bytes(4, "little")],
            program_id
        )
        alice_pubkey = program.provider.wallet.public_key
        alice_ata = find_associated_token_address(alice_pubkey, mint_for_dapp_pda)
        print(f"[DEBUG] Derived Alice's PDA: {alice_pda}")
        print(f"[DEBUG] Derived Alice's ATA: {alice_ata}")

        # 10) Verify Alice's ATA exists and is owned by SPL Token program
        is_valid_ata = await verify_ata(client, alice_ata)
        if not is_valid_ata:
            print("[ERROR] ATA verification failed. Aborting minting.")
            return

        # 11) Now submit a single player's leftover => [alice_pda, alice_ata]
        await submit_minting_list(
            program,
            dapp_pda=dapp_pda,          # Pass in the known DApp
            game_pda=game_pda,
            game_number=game_number,
            validator_kp=validator_kp,
            validator_pda=validator_pda,
            fancy_mint=mint_for_dapp_pda,
            mint_auth_pda=mint_auth_pda,
            leftover_player_pda=alice_pda,
            leftover_player_ata=alice_ata,  # Use the correct ATA
        )

        print("\nAll tests completed successfully.")

    except Exception as e:
        print(f"An unexpected error occurred.\n{e}")
        traceback.print_exc()
    finally:
        await client.close()
        print("[INFO] Solana RPC client closed.")

if __name__ == "__main__":
    asyncio.run(main())

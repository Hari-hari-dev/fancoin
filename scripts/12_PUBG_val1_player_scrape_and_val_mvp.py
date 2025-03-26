import asyncio
import socket
import struct
import a2s
import re
import json
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Anchor / Solana
from solders.rpc.responses import SendTransactionResp  # Ensure this import is present
from anchorpy import Program, Provider, Wallet, Idl, Context
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import Commitment
from solana.rpc.core import RPCException
from solders.system_program import transfer, TransferParams
from solana.rpc.types import TxOpts  # Correct import for transaction options
from solana.transaction import Transaction, Signature  # Import solana-py's Signature class
from anchorpy.program.namespace.instruction import AccountMeta
SPL_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
Confirmed = Commitment("confirmed")  # Ensure this matches your actual Commitment type

###############################################################################
# Globals set after program setup
###############################################################################
program = None
provider = None
program_id = None
dapp_pda = None

CHUNK_SIZE = 3  # how many players to mint per TX
game_pda_str = Path("game_pda.txt").read_text().strip()
mint_auth_pda_str = Path("mint_auth_pda.txt").read_text().strip()
minted_mint_pda_str = Path("minted_mint_pda.txt").read_text().strip()


game_pda = Pubkey.from_string(game_pda_str)
mint_auth_pda = Pubkey.from_string(mint_auth_pda_str)
minted_mint_pda = Pubkey.from_string(minted_mint_pda_str)

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

async def find_users(deduped, aggregated_local_server_names, name_map):
    """
    Encapsulates the logic to find users from the TFC servers and match them with on-chain data.
    
    Args:
        deduped (list): List of deduplicated TFC servers (ip, port).
        aggregated_local_server_names (set): Set to accumulate player names across iterations.
        name_map (dict): Mapping of on-chain player data.
    
    Returns:
        list: List of matched player names.
    """
    # Gather local server players
    local_server_names = set()
    for ip, port in deduped:
        print(f"[DEBUG] Checking server {ip}:{port}")
        try:
            players = get_player_list_a2s(ip, port)
            if players:
                # decode_and_collect_players => name->True
                result_dict = decode_and_collect_players(players)
                local_server_names.update(result_dict.keys())
        except Exception as e:
            print(f"[ERROR] Failed to get players from {ip}:{port} - {e}")
            continue

    print(f"[INFO] Found {len(local_server_names)} distinct players from TFC servers.")
    aggregated_local_server_names.update(local_server_names)

    # Intersection: local server players vs. on-chain
    matched_names = list(aggregated_local_server_names.intersection(set(name_map.keys())))
    print(f"[INFO] matched_names => {matched_names}")
    return matched_names

###############################################################################
# 2) Debug-check DApp
###############################################################################
# async def debug_check_dapp_pda():
#     dapp_data = await program.account["DApp"].fetch(dapp_pda)
#     print("[DEBUG] DApp Account Data:")
#     print(f"         owner                = {dapp_data.owner}")
#     print(f"         global_player_count  = {dapp_data.global_player_count}")
#     print(f"         mint_pubkey         = {dapp_data.mint_pubkey}")
# fix, flavor text, consider using
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
    game_data = await program.account["Game"].fetch(game_pda)
    total_count = game_data.player_count

    # Derive PDA to index mapping
    pda_to_index = {}
    for i in range(total_count):
        seed_index_bytes = i.to_bytes(4, "little")
        (pda, _) = Pubkey.find_program_address([b"player_pda", bytes(game_pda), seed_index_bytes], program.program_id)
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
    seeds = [
        bytes(owner),
        bytes(SPL_TOKEN_PROGRAM_ID),
        bytes(mint),
    ]
    ata, _ = Pubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
    return ata

###############################################################################
# 4) submit_minting_list: advanced leftover approach
###############################################################################
async def submit_minting_list_with_leftover(
    matched_names: list[str],
    name_map: dict,
):
    validator_kp = load_validator_keypair()
    validator_pubkey = validator_kp.pubkey()

    # Derive the validator_pda
    seeds_val = [b"validator", bytes(minted_mint_pda), bytes(validator_pubkey)]
    (validator_pda, bump_val) = Pubkey.find_program_address(seeds_val, program.program_id)

    # Fetch DApp's mint_pubkey
    #dapp_data = await program.account["DApp"].fetch(dapp_pda)
    #fancy_mint_pk = dapp_data.mint_pubkey

    # Derive mint_authority
    #(mint_auth_pda, bump_mint_auth) = Pubkey.find_program_address([b"mint_authority"], program_id)

    # SysvarRent
    rent_sysvar_pubkey = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
    validator_ata = find_associated_token_address(validator_pubkey, minted_mint_pda)

    # Initialize validator_pda if not already initialized
    try:
        await program.account["ValidatorPda"].fetch(validator_pda)
        print(f"[DEBUG] validator_pda {validator_pda} already initialized.")
    except:
        print(f"[INFO] validator_pda {validator_pda} not found. Initializing...")
        # Derive the validator's ATA
        ctx_init_val = Context(
            accounts={
                "game": game_pda,
                "fancy_mint": minted_mint_pda,
                "validator_pda": validator_pda,
                "user": validator_pubkey,
                "validator_ata": validator_ata,
                #"dapp": dapp_pda,
                "token_program": SPL_TOKEN_PROGRAM_ID,
                "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                "system_program": SYS_PROGRAM_ID,
                "rent": rent_sysvar_pubkey,
            },
            signers=[validator_kp],
        )
        # Invoke the register_validator_pda instruction
        try:
            tx_sig_init_val = await program.rpc["register_validator_pda"](
                minted_mint_pda,
                ctx=ctx_init_val
            )
            print(f"[INFO] Registered validator_pda + ATA. Tx Sig: {tx_sig_init_val}")
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
                "game": game_pda,
                "validator_pda": validator_pda,
                "validator": validator_pubkey,
                "fancy_mint": minted_mint_pda,
                #"dapp": dapp_pda,
                "mint_authority": mint_auth_pda,
                "token_program": SPL_TOKEN_PROGRAM_ID,
                #"rent": rent_sysvar_pubkey,
                "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                "system_program": SYSTEM_PROGRAM_ID,

            },
            signers=[validator_kp],
            remaining_accounts=leftover_accounts
        )

        # Call your on-chain `submit_minting_list` instruction
        try:
            tx_sig = await program.rpc["submit_minting_list"](
                minted_mint_pda,
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

    try:
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
        #game_number = 1
        #(game_pda, bump_game) = Pubkey.find_program_address(
        #    [b"game", game_number.to_bytes(4, "little")], program_id
        #)
        #(dapp_pda, bump_dapp) = Pubkey.find_program_address([b"dapp"], program_id)
        print(f"[DEBUG] using game_pda={game_pda}")
        #print(f"[DEBUG] using dapp_pda={dapp_pda}")

        # 3) Debug-check DApp
        #await debug_check_dapp_pda()
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

        while True:

            # 5) Fetch all on-chain PlayerPda => build (name -> index, name -> pda, reward_address)
            print("[INFO] Fetching on-chain name->(index, pda, reward_address).")
            name_map = await fetch_player_pdas_map()

            # Loop to find users 4 times with 5-minute intervals
            for iteration in range(1, 5):  # Iterations 1 through 4
                print(f"\n[INFO] Starting iteration {iteration} of 4.")
                balance_resp = await provider.connection.get_balance(validator_pubkey)
                lamports = balance_resp.value
                sol_balance = lamports / 1e9
                print(f"[INFO] Validator balance: {sol_balance} SOL")
                matched_names = await find_users(deduped, aggregated_local_server_names, name_map)
                aggregated_local_server_names = set()

                # Example: If you only want to do a mint on the first iteration:
                if matched_names and iteration == 1:
                    await submit_minting_list_with_leftover(matched_names, name_map)
                    print(f"[INFO] Minting period finished. Checking validator balance before next wait...")

                    # ───────────────────────────────────────────────────────────
                    # Print validator’s balance (in SOL) before the 5-min sleep

                    # ───────────────────────────────────────────────────────────
                    balance_resp = await provider.connection.get_balance(validator_pubkey)
                    lamports = balance_resp.value
                    sol_balance = lamports / 1e9
                    print(f"[INFO] Validator balance: {sol_balance} SOL")
                    print(f"[INFO] Waiting for ~5 minutes before next scan.")
                    await asyncio.sleep(30)  # Wait for 5 minutes

                else:
                    if matched_names:
                        print(f"[INFO] Matched players found. Checking validator balance before waiting.")
                    else:
                        print("[WARN] No matched players found.")

                    # ───────────────────────────────────────────────────────────
                    # Print validator’s balance (in SOL) before the 5-min sleep
                    balance_resp = await provider.connection.get_balance(validator_pubkey)
                    lamports = balance_resp.value
                    sol_balance = lamports / 1e9
                    print(f"[INFO] Validator balance: {sol_balance} SOL")
                    # ───────────────────────────────────────────────────────────

                    print(f"[INFO] Waiting 5 minutes before next scan.")
                    await asyncio.sleep(30)

    except Exception as e:
        print(f"[ERROR] Unexpected error => {e}")
        traceback.print_exc()
    finally:
        # Clean up
        if provider and provider.connection:
            await provider.connection.close()
        print("[INFO] Solana RPC client closed.")

if __name__ == "__main__":
    asyncio.run(main())

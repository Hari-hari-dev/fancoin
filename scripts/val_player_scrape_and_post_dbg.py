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
#from solana.rpc.api import Pubkey, Keypair
#from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from solders.system_program import transfer, TransferParams
from solana.rpc.types import TxOpts  # Correct import for transaction options
from solana.transaction import Transaction, Signature  # Import solana-py's Signature class
from anchorpy.program.namespace.instruction import AccountMeta

ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
SPL_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
RENT_SYSVAR_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

###############################################################################
# Globals set after program setup
###############################################################################
program = None
provider = None
program_id = None
game_pda = None
dapp_pda = None

CHUNK_SIZE = 3  # how many players to mint per TX
game_pda_str = Path("game_pda.txt").read_text().strip()
mint_auth_pda_str = Path("mint_auth_pda.txt").read_text().strip()
minted_mint_pda_str = Path("minted_mint_pda.txt").read_text().strip()


game_pda = Pubkey.from_string(game_pda_str)
mint_auth_pda = Pubkey.from_string(mint_auth_pda_str)
minted_mint_pda = Pubkey.from_string(minted_mint_pda_str)

# print("Loaded game_pda  =", game_pda)
# print("Loaded mint_auth_pda  =", mint_auth_pda)
# print("Loaded minted_mint_pda =", minted_mint_pda)
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
    game_data = await program.account["Game"].fetch(game_pda)
    print("[DEBUG] Game Account Data:")
    #print(f"         owner                = {game_data.owner}")
    print(f"         player_count  = {game_data.player_count}")
    print(f"         mint_pubkey         = {game_data.mint_pubkey}")

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

    # Fetch Game data to get total player count
    game_data = await program.account["Game"].fetch(game_pda)
    total_count = game_data.player_count

    # Derive PDA to index mapping
    # pda_to_index = {}
    # for i in range(total_count):
    #     seed_index_bytes = i.to_bytes(4, "little")
    #     (pda, _) = Pubkey.find_program_address([b"player_pda", seed_index_bytes], program.program_id)
    #     pda_to_index[str(pda)] = i

    # # Build the name map with reward_address
    pda_to_index = {}
    for i in range(total_count):
        seeds = [
            b"player_pda",
            bytes(game_pda),         # The same 'game' pubkey you used on-chain
            i.to_bytes(4, "little"), # The same little-endian integer
        ]
        (pda, bump) = Pubkey.find_program_address(seeds, program.program_id)
        pda_to_index[str(pda)] = i
            
    
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
def derive_ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """Derive the associated token account (ATA) address for (owner,mint)."""
    seeds = [
        bytes(owner),
        bytes(SPL_TOKEN_PROGRAM_ID),
        bytes(mint),
    ]
    (ata, _) = Pubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
    return ata
###############################################################################
# 4) submit_minting_list: advanced leftover approach
###############################################################################
async def submit_minting_list_with_leftover(matched_names: list[str], name_map: dict):
    validator_kp = load_validator_keypair()
    validator_pubkey = validator_kp.pubkey()

    # 1) validator_pda
    # seeds_val = [b"validator", game_number.to_bytes(4, "little"), bytes(validator_pubkey)]
    # (validator_pda, bump_val) = Pubkey.find_program_address(seeds_val, program.program_id)

    seeds_val = [
        b"validator",
        bytes(minted_mint_pda), 
        bytes(validator_pubkey)
    ]
    (validator_pda, bump_val) = Pubkey.find_program_address(seeds_val, program.program_id)

    # 2) fetch the dapp to get fancy_mint
    game_data = await program.account["Game"].fetch(game_pda)
    fancy_mint_pk = game_data.mint_pubkey

    # 3) find the validator_ata
    validator_ata = derive_ata(validator_pubkey, fancy_mint_pk)

    # 4) fetch or create the validator_pda by calling register_validator_pda if needed
    try:
        await program.account["ValidatorPda"].fetch(validator_pda)
        print(f"[DEBUG] validator_pda {validator_pda} already initialized.")
    except:
        print(f"[INFO] validator_pda {validator_pda} not found. Initializing (and creating ATA={validator_ata})...")
        ctx_init_val = Context(
            accounts={
                "game":            game_pda,
                "fancy_mint":      fancy_mint_pk,
                "validator_pda":   validator_pda,
                "user":            validator_pubkey,
                "validator_ata":   validator_ata,
                #"dapp":            dapp_pda,
                "token_program":   SPL_TOKEN_PROGRAM_ID,
                "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                "system_program":  SYSTEM_PROGRAM_ID,
                "rent":            Pubkey.from_string("SysvarRent111111111111111111111111111111111"),
            },
            signers=[validator_kp],
        )
        try:
            tx_sig_init_val = await program.rpc["register_validator_pda"](
                fancy_mint_pk,
                ctx_init_val
            )
            print(f"[INFO] Registered validator_pda + ATA. Tx Sig: {tx_sig_init_val}")
        except RPCException as e:
            print(f"[ERROR] Failed to register validator_pda: {e}")
            return
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
            print("[DEBUG] This chunk is empty, skipping.")
            continue

        print(f"[DEBUG] Submitting chunk => {numeric_ids}")

        # Build AnchorPy Context
        ctx = Context(
            accounts={
                "game":           game_pda,
                "validator_pda":  validator_pda,
                "validator":      validator_pubkey,
                "fancy_mint":     fancy_mint_pk,
                #"dapp":           dapp_pda,
                "mint_authority": mint_auth_pda,
                "token_program":  SPL_TOKEN_PROGRAM_ID,
                # Add 'rent' if your instruction requires it:
                "rent": RENT_SYSVAR_ID,
                # If your on-chain code also references system_program, associated_token_program,
                # you must pass them as well. Example:
                "system_program": SYSTEM_PROGRAM_ID,
                "associated_token_program": Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"),
            },
            signers=[validator_kp],
            remaining_accounts=leftover_accounts
        )

        # Call your on-chain `submit_minting_list` instruction
        try:
            tx_sig = await program.rpc["submit_minting_list"](
                numeric_ids,
                fancy_mint_pk,
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
        #(game_pda, bump_game) = Pubkey.find_program_address([b"game", game_number.to_bytes(4, "little")], program_id)
        #(dapp_pda, bump_dapp) = Pubkey.find_program_address([b"dapp"], program_id)
        #print(f"[DEBUG] using game_pda={game_pda}")
        #print(f"[DEBUG] using dapp_pda={dapp_pda}")

        # 3) Debug-check DApp
        await debug_check_dapp_pda()

        # 4) Suppose you do your TFC server logic => you get a local list of names
        #    Replace this with actual server querying logic as needed
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
            except:
                pass

        print(f"[INFO] Found {len(local_server_names)} distinct players from TFC servers.")

        # 5) Fetch all on-chain PlayerPda => build (name -> index, name -> pda, name -> reward_address)
        print("[INFO] Fetching on-chain name->(index, pda, reward_address).")
        name_map = await fetch_player_pdas_map()

        # 6) Intersection: local server players vs. on-chain
        matched_names = list(local_server_names.intersection(set(name_map.keys())))
        print(f"[INFO] matched_names => {matched_names}")
        if not matched_names:
            print("[WARN] No matched players found. Exiting.")
            return

        # 7) Submit them in multiple chunks
        await submit_minting_list_with_leftover(matched_names, name_map)

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

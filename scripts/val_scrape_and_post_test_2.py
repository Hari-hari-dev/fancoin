import asyncio
import socket
import struct
import a2s
import re
import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Anchor / Solana
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from anchorpy import Program, Provider, Wallet, Idl, Context
from anchorpy.program.namespace.instruction import AccountMeta

###############################################################################
# Globals set after program setup
###############################################################################
program = None
provider = None
program_id = None
game_pda = None
dapp_pda = None

CHUNK_SIZE = 3  # how many players to handle per TX
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")

###############################################################################
# 1) Load Validator Keypair
###############################################################################
def load_validator_keypair(filename="val2-keypair.json") -> Keypair:
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
    # If your DApp also has a `mint_pubkey`, print it:
    if hasattr(dapp_data, 'mint_pubkey'):
        print(f"         mint_pubkey         = {dapp_data.mint_pubkey}")

###############################################################################
# 3) On-chain fetch: build name -> { index, pda }
###############################################################################
async def fetch_player_pdas_map() -> dict:
    """
    Returns a dict:
      {
         "<player_name>": {
            "index":  <u32 index in the anchor code>,
            "pda":    <Pubkey for PlayerPda>
         },
         ...
      }

    We assume seeds=[b"player_pda", i32_as_le_bytes] for each new player.
    We'll re-derive each player's address to figure out their 'index'.
    """
    all_records = await program.account["PlayerPda"].all()
    print(f"[DEBUG] Found {len(all_records)} PlayerPda records on-chain.")

    # Check how many players exist from your DApp
    dapp_data = await program.account["DApp"].fetch(dapp_pda)
    total_count = dapp_data.global_player_count

    # Build pubkey->index by re-deriving addresses up to total_count
    pda_to_index = {}
    for i in range(total_count):
        seed_index_bytes = i.to_bytes(4, "little")
        (pda, _) = Pubkey.find_program_address([b"player_pda", seed_index_bytes], program.program_id)
        pda_to_index[str(pda)] = i

    name_map = {}
    for rec in all_records:
        pkey_str = str(rec.public_key)
        if pkey_str in pda_to_index:
            real_idx = pda_to_index[pkey_str]
            player_name = rec.account.name  # The "name" field on your PlayerPda
            name_map[player_name] = {
                "index": real_idx,
                "pda": rec.public_key
            }
        else:
            # Possibly leftover from older code that doesn't match current seeds
            pass

    return name_map

###############################################################################
# 4) submit_minting_list: advanced leftover approach
###############################################################################
async def submit_minting_list_with_leftover(game_number: int, matched_names: list[str], name_map: dict):
    """
    Break matched names into CHUNK_SIZE groups, re-derive ATA stubs,
    and call your on-chain instruction `submit_minting_list`.
    """
    validator_kp = load_validator_keypair()
    validator_pubkey = validator_kp.pubkey()

    # 1) Derive validator_pda
    seeds_val = [b"validator", game_number.to_bytes(4, "little"), bytes(validator_pubkey)]
    (validator_pda, _) = Pubkey.find_program_address(seeds_val, program.program_id)

    # 2) Possibly fetch DApp's mint_pubkey
    dapp_data = await program.account["DApp"].fetch(dapp_pda)
    fancy_mint_pk = dapp_data.mint_pubkey if hasattr(dapp_data, 'mint_pubkey') else None

    # 3) Derive mint_authority
    (mint_auth_pda, _) = Pubkey.find_program_address([b"mint_authority"], program_id)

    # 4) We also pass in SysvarRent for instructions that may require it
    rent_sysvar_pubkey = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

    # If your instruction also references `system_program` or `associated_token_program`,
    # you'd pass them similarly. For example:
    #   system_program: SYS_PROGRAM_ID
    #   associated_token_program: <some AT program ID e.g. "ATokenGPv...">

    for start_idx in range(0, len(matched_names), CHUNK_SIZE):
        chunk = matched_names[start_idx : start_idx + CHUNK_SIZE]
        leftover_accounts = []
        numeric_ids = []

        for name in chunk:
            entry = name_map.get(name)
            if entry is None:
                print(f"[WARN] Name={name} not found in name_map. Skipping.")
                continue

            pid = entry["index"]
            player_pda_pubkey = entry["pda"]

            # Build a "dummy" ATA for each player, using seeds
            dummy_seed = f"dummyATA_{pid}".encode("utf-8")
            (dummy_ata_pubkey, _) = Pubkey.find_program_address([dummy_seed], program.program_id)

            # leftover => [PlayerPda, ATA]
            leftover_accounts.append(
                AccountMeta(pubkey=player_pda_pubkey, is_signer=False, is_writable=True)
            )
            leftover_accounts.append(
                AccountMeta(pubkey=dummy_ata_pubkey, is_signer=False, is_writable=True)
            )
            numeric_ids.append(pid)

        if not numeric_ids:
            print("[DEBUG] This chunk is empty, skipping.")
            continue

        print(f"[DEBUG] Submitting chunk => {numeric_ids}")

        # Anchorpy Context
        ctx = Context(
            accounts={
                "game":           game_pda,
                "validator_pda":  validator_pda,
                "validator":      validator_pubkey,
                "fancy_mint":     fancy_mint_pk,
                "dapp":           dapp_pda,
                "mint_authority": mint_auth_pda,
                "token_program":  Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
                # Add 'rent' if your instruction requires it:
                "rent": rent_sysvar_pubkey,
                # If your on-chain code also references system_program, associated_token_program,
                # you must pass them as well. Example:
                "system_program": SYSTEM_PROGRAM_ID,
                "associated_token_program": Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"),
            },
            signers=[validator_kp],
            remaining_accounts=leftover_accounts
        )

        # 5) Call your on-chain `submit_minting_list` instruction
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
    from anchorpy import Program, Provider, Wallet, Idl
    global provider, program, program_id, dapp_pda, game_pda

    try:
        # 1) Set up anchor environment
        print("[INFO] Setting up anchor environment.")
        client = AsyncClient("http://localhost:8899", commitment=Confirmed)
        wallet = Wallet.local()
        provider = Provider(client, wallet)

        # Load IDL
        idl_path = Path("../target/idl/fancoin.json")
        if not idl_path.exists():
            print(f"[ERROR] IDL not found at {idl_path.resolve()}")
            return

        with idl_path.open() as f:
            idl_json = f.read()

        from anchorpy import Idl
        idl = Idl.from_json(idl_json)

        # Program ID
        program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")

        # Create Program object
        program = Program(idl, program_id, provider)
        print("[INFO] Program loaded successfully.")

        # 2) Derive PDAs
        game_number = 1
        (game_pda, _) = Pubkey.find_program_address([b"game", game_number.to_bytes(4, "little")], program_id)
        (dapp_pda, _) = Pubkey.find_program_address([b"dapp"], program_id)
        print(f"[DEBUG] game_pda => {game_pda}")
        print(f"[DEBUG] dapp_pda => {dapp_pda}")

        # Debug the DApp
        await debug_check_dapp_pda()

        # 3) Query TFC servers => local server names
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

        # 4) Fetch on-chain name->(index, pda)
        print("[INFO] Fetching on-chain name->(index, pda).")
        name_map = await fetch_player_pdas_map()

        # 5) Intersection: local server players vs. on-chain
        matched_names = list(local_server_names.intersection(name_map.keys()))
        print(f"[INFO] matched_names => {matched_names}")
        if not matched_names:
            print("[WARN] No matched players found. Exiting.")
            return

        # 6) Summon leftover approach
        print("[INFO] Submitting leftover approach for matched players...")
        await submit_minting_list_with_leftover(game_number, matched_names, name_map)

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

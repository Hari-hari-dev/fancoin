import asyncio
import socket
import struct
import a2s
import re
import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from anchorpy import Program, Provider, Wallet, Idl, Context

# Globals that need to be set after setup:
program = None
provider = None
dapp_pda = None
program_id = None
dapp_pda = None  # We'll store the DApp PDA here

def load_validator_keypair(filename='val1-keypair.json'):
    """Load the validator keypair from a JSON file containing secret_key hex."""
    with open(filename, 'r') as f:
        data = json.load(f)
    secret_key_hex = data.get("secret_key", "")
    if not secret_key_hex:
        raise ValueError("No secret_key found in val1-keypair.json")
    secret_key = bytes.fromhex(secret_key_hex)
    kp = Keypair.from_bytes(secret_key)
    return kp

async def debug_check_dapp_pda():
    """Fetch and print the on-chain DApp account data."""
    global program, dapp_pda
    if dapp_pda is None:
        print("[ERROR] dapp_pda is None. Cannot fetch DApp.")
        return

    try:
        dapp_data = await program.account["DApp"].fetch(dapp_pda)
        print("[DEBUG] DApp Account Data:")
        print(f"         owner                = {dapp_data.owner}")
        print(f"         global_player_count = {dapp_data.global_player_count}")
    except Exception as exc:
        print(f"[ERROR] Could not fetch DApp account at {dapp_pda}: {exc}")

def get_player_list_for_dapp(matched_players):
    return [matched_players[i : i + 16] for i in range(0, len(matched_players), 16)]

def submit_minting_list_for_dapp(dapp_number, chunked_player_list):
    """Stub function that *simulates* minting. Real on-chain minting would happen in a separate call."""
    validator_kp = load_validator_keypair()
    print(f"Submitting minting list for dapp_number={dapp_number} with validator={validator_kp.pubkey()}")
    for idx, player_group in enumerate(chunked_player_list):
        print(f"Submitting group {idx} of size {len(player_group)}: {player_group}")
    print("Minting list submission simulation complete.")

async def submit_minting_list_for_dapp_async(dapp_number, chunked_player_list, executor):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, submit_minting_list_for_dapp, dapp_number, chunked_player_list)

async def get_player_list_page(start_index: int, end_index: int):
    """
    Calls the on-chain `get_player_list_pda_page` instruction, which expects exactly two arguments:
    `start_index` and `end_index`. Also uses 'dapp' in the accounts dictionary.
    """
    global program, provider, dapp_pda
    print(f"[DEBUG] Calling get_player_list_pda_page with start_index={start_index}, end_index={end_index}")

    try:
        tx_sig = await program.rpc["get_player_list_pda_page"](
            start_index,
            end_index,
            ctx=Context(
                accounts={
                    "dapp": dapp_pda  # The Rust code expects 'dapp' as the account name
                }
            )
        )
        print(f"[DEBUG] get_player_list_pda_page transaction signature: {tx_sig}")
    except RPCException as e:
        print(f"[ERROR] RPCException calling get_player_list_pda_page: {e}")
        print("[DEBUG] Returning empty list of players.")
        return []

    # Fetch transaction logs
    print("[DEBUG] Fetching transaction logs for get_player_list_pda_page call...")
    confirmed_tx = await provider.connection.get_transaction(tx_sig, encoding='json')
    if confirmed_tx.value is None:
        print("[DEBUG] No transaction found or no logs available.")
        return []

    tx_meta = confirmed_tx.value.transaction.meta
    if tx_meta is None or tx_meta.log_messages is None:
        print("[DEBUG] No transaction meta or log messages found.")
        return []

    logs = tx_meta.log_messages
    print("[DEBUG] Raw logs from get_player_list_pda_page transaction:")
    for log_line in logs:
        print(f"[DEBUG LOG] {log_line}")

    # Attempt to parse lines that say "PlayerPda #X => name: Y"
    players = []
    player_line_regex = re.compile(r'PlayerPda #(\d+) => name: (\w+)')
    for line in logs:
        if "PlayerPda #" in line:
            line = line.replace("Program log: ", "")  # remove prefix if present
            match = player_line_regex.search(line)
            if match:
                pkey_str = match.group(2).strip()
                players.append(pkey_str)

    if players:
        print(f"[DEBUG] Extracted {len(players)} players: {players}")
    else:
        print("[DEBUG] No players found in logs for this page.")

    return players

async def get_all_onchain_players(dapp_number: int, page_size=5):
    """
    Fetch all players by calling get_player_list_pda_page repeatedly.
    We don't pass `dapp_number` to get_player_list_page because 
    that instruction only expects (start_index, end_index).
    """
    print(f"[DEBUG] Starting to fetch all on-chain players with page_size={page_size}.")
    all_players = []
    start_index = 0

    while True:
        end_index = start_index + page_size
        print(f"[DEBUG] Fetching players from {start_index} to {end_index}")
        players = await get_player_list_page(start_index, end_index)
        if not players:
            print("[DEBUG] No players returned for this page, stopping.")
            break
        all_players.extend(players)

        # If fewer than page_size returned, we assume we've reached the end
        if len(players) < page_size:
            print(f"[DEBUG] Fewer than {page_size} players returned, assuming end of player list.")
            break

        start_index += page_size

    print(f"[DEBUG] Total DApp players fetched: {len(all_players)}")
    return all_players

def query_master_server(region, app_id):
    master_server = ("hl1master.steampowered.com", 27011)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    request = b"\x31\xFF0.0.0.0:0\x00\\dappdir\\tfc\x00"
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

def parse_response(data):
    servers = []
    for i in range(6, len(data), 6):
        ip = ".".join(map(str, data[i : i + 4]))
        port = struct.unpack(">H", data[i + 4 : i + 6])[0]
        if ip == "0.0.0.0" and port == 0:
            break
        servers.append((ip, port))
    return servers

def format_server(server):
    return f'{server[0]}:{server[1]}'.encode()

def send_udp_request(ip, port, message, timeout=5):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.sendto(message, (ip, port))
            response, _ = sock.recvfrom(4096)
            return response
        except socket.timeout:
            print(f"Request to {ip}:{port} timed out")
            return None

def clean_brackets_and_contents(name):
    name = re.sub(r'\^\d', '', name)
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\{.*?\}', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'<.*?>', '', name)
    name = re.sub(r'[\[\]\{\}\(\)<>]', '', name)
    name = re.sub(r'[^a-zA-Z0-9_-]', '', name)
    return name.strip()

def extract_player_names_from_response(response, dapp):
    if not response:
        return []
    decoded_response = response.decode('utf-8', errors='ignore')
    if dapp == "QW":
        player_regex = re.compile(r'\d+\s+\d+\s+\d+\s+\d+\s+"([^"]+)"')
        player_names = player_regex.findall(decoded_response)
        return [clean_brackets_and_contents(name) for name in player_names]
    elif dapp == "Q2":
        player_regex = re.compile(r'\d+\s+\d+\s+"([^"]+)"')
        player_names = player_regex.findall(decoded_response)
        return [clean_brackets_and_contents(name) for name in player_names]
    elif dapp in ["Q3", "QL"]:
        player_regex = re.compile(r'"\^?[0-9A-Za-z\^]*[^\"]+"')
        player_names = player_regex.findall(decoded_response)
        return [clean_brackets_and_contents(name.strip('"')) for name in player_names]
    return []

def get_player_list_quakeworld(ip, port):
    player_request = b'\xFF\xFF\xFF\xFFstatus\x00'
    return send_udp_request(ip, port, player_request)

def get_player_list_quake2(ip, port):
    player_request = b'\xFF\xFF\xFF\xFFstatus\x00'
    return send_udp_request(ip, port, player_request)

def get_player_list_quake3(ip, port):
    player_request = b'\xFF\xFF\xFF\xFFgetstatus\x00'
    return send_udp_request(ip, port, player_request)

def get_player_list_a2s(ip, port):
    try:
        address = (ip, port)
        players = a2s.players(address)
        return players
    except Exception as e:
        print(f"Failed to query server at {ip}:{port}: {e}")
        return []

def generate_account():
    kp = Keypair()
    kp_bytes = bytes(kp)
    private_key = kp_bytes[:32]
    private_key_hex = private_key.hex()
    public_key_str = str(kp.pubkey())
    return private_key_hex, public_key_str

def decode_and_collect_players(players):
    player_data = {}
    if players:
        for player in players:
            sanitized_name = clean_brackets_and_contents(player.name)
            if sanitized_name:
                private_key, address = generate_account()
                player_data[sanitized_name] = {
                    "private_key": private_key,
                    "address": address
                }
    return player_data

def save_as_json(data, filename='player_wallets.json'):
    with open(filename, 'w') as json_file:
        json.dump(data, json_file, indent=4)

def decode_and_print_raw(response, ip, port, title, dapp):
    if response:
        player_names = extract_player_names_from_response(response, dapp)
        if player_names:
            print(f"Players on {ip}:{port} - {title}:")
            for name in player_names:
                print(f"{name}")
        else:
            print(f"No players found on {ip}:{port} - {title}")
    else:
        print(f"No response from {ip}:{port} - {title}")

async def main():
    try:
        print("Setting up provider and loading program...")
        client = AsyncClient("http://localhost:8899", commitment=Confirmed)
        wallet = Wallet.local()
        global provider
        provider = Provider(client, wallet)

        # 1) Load IDL from JSON
        idl_path = Path("../target/idl/fancoin.json")
        if not idl_path.exists():
            print(f"IDL file not found at {idl_path.resolve()}")
            return

        with idl_path.open() as f:
            idl_json = f.read()

        idl = Idl.from_json(idl_json)

        # 2) Create Program
        global program_id, program, dapp_pda, dapp_pda
        program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
        program = Program(idl, program_id, provider)
        print("Program loaded successfully.")

        # 3) Derive PDAs
        dapp_number = 1
        (dapp_pda, _) = Pubkey.find_program_address(
            [b"dapp", dapp_number.to_bytes(4, "little")],
            program_id
        )
        print(f"[DEBUG] Found dapp_pda: {dapp_pda}")

        (dapp_pda, dapp_bump) = Pubkey.find_program_address([b"dapp"], program.program_id)
        print(f"[DEBUG] Found dapp_pda: {dapp_pda}, bump={dapp_bump}")

        # 4) Debug check the DApp
        await debug_check_dapp_pda()

        # 5) Now do any logic, e.g. read on-chain players, query servers, etc.
        region = 0xFF
        app_id = 20
        print("Querying master server for TFC servers...")
        tfc_servers = list(query_master_server(region, app_id))
        unique_ips = {}
        for ip, port in tfc_servers:
            if ip not in unique_ips:
                unique_ips[ip] = (ip, port)

        deduped_servers = list(unique_ips.values())
        print(f"Number of unique TFC servers found: {len(deduped_servers)}")

        all_player_data = {}
        for ip, port in deduped_servers:
            print(f"Querying server: {ip}:{port}")
            players = get_player_list_a2s(ip, port)
            player_data = decode_and_collect_players(players)
            all_player_data.update(player_data)

        save_as_json(all_player_data)

        # 6) Fetch on-chain players
        dapp_registered_players = await get_all_onchain_players(dapp_number, page_size=4)

        server_players = list(all_player_data.keys())
        matched_players = list(set(server_players).intersection(set(dapp_registered_players)))

        if matched_players:
            print(f"Matched {len(matched_players)} players with the DApp registry.")
            chunked = get_player_list_for_dapp(matched_players)
            executor = ThreadPoolExecutor(max_workers=10)
            await submit_minting_list_for_dapp_async(dapp_number, chunked, executor)
            executor.shutdown(wait=True)
        else:
            print("No matched players found between server and DApp registered lists.")

    except Exception as e:
        print(f"An unexpected error occurred:\n{e}")
        traceback.print_exc()
    finally:
        if provider and provider.connection:
            await provider.connection.close()
        print("Closed Solana RPC client.")

if __name__ == "__main__":
    asyncio.run(main())

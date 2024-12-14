import socket
import struct
import a2s
import re
import json
from solders.keypair import Keypair
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import asyncio
from anchorpy import Program, Provider, Wallet, Idl, Context
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID

def query_master_server(region, app_id):
    master_server = ("208.64.200.117", 27011)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    request = b'\x31' + bytes([region]) + b'\\appid\\' + str(app_id).encode() + b'\\'
    last_ip = b'0.0.0.0:0'
    while True:
        sock.sendto(request + last_ip, master_server)
        try:
            response_data, _ = sock.recvfrom(4096)
        except socket.timeout:
            print("Request timed out")
            break
        
        servers = parse_response(response_data)
        if not servers:
            break
        
        last_ip = format_server(servers[-1])
        for srv in servers:
            yield srv

def parse_response(data):
    servers = []
    for i in range(6, len(data), 6):
        ip = ".".join(map(str, data[i:i+4]))
        port = struct.unpack(">H", data[i+4:i+6])[0]
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

def extract_player_names_from_response(response, game):
    if not response:
        return []
    decoded_response = response.decode('utf-8', errors='ignore')
    if game == "QW":
        player_regex = re.compile(r'\d+\s+\d+\s+\d+\s+\d+\s+"([^"]+)"')
        player_names = player_regex.findall(decoded_response)
        return [clean_brackets_and_contents(name) for name in player_names]
    elif game == "Q2":
        player_regex = re.compile(r'\d+\s+\d+\s+"([^"]+)"')
        player_names = player_regex.findall(decoded_response)
        return [clean_brackets_and_contents(name) for name in player_names]
    elif game in ["Q3", "QL"]:
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

# Instead of generating accounts or saving to file, we just return a list of player names.
def decode_and_collect_players(players):
    player_names = []
    if players:
        for player in players:
            sanitized_name = clean_brackets_and_contents(player.name)
            # Truncate to 16 chars as requested
            sanitized_name = sanitized_name[:16]
            if sanitized_name:
                player_names.append(sanitized_name)
    return player_names

def decode_and_print_raw(response, ip, port, title, game):
    if response:
        player_names = extract_player_names_from_response(response, game)
        if player_names:
            print(f"Players on {ip}:{port} - {title}:")
            for name in player_names:
                print(f"{name}")
        else:
            print(f"No players found on {ip}:{port} - {title}")
    else:
        print(f"No response from {ip}:{port} - {title}")

def query_server_for_players(ip, port):
    # This function encapsulates the logic for querying a server.
    print(f"Querying server: {ip}:{port}")
    players = get_player_list_a2s(ip, port)
    return decode_and_collect_players(players)

async def get_player_list(program: Program, game_pda: Pubkey, game_number: int):
    # Example call to get_player_list from on-chain.
    start_index = 0
    batch_size = 10

    chain_players = []
    # NOTE: In reality, you'd parse logs or have return_data. 
    # Here we just simulate calling until error.
    while True:
        end_index = start_index + batch_size
        try:
            # This call will fail or succeed based on your program's logic
            tx = await program.rpc["get_player_list"](
                game_number,
                start_index,
                end_index,
                ctx=Context(
                    accounts={
                        "game": game_pda,
                    },
                    pre_instructions=[],
                    post_instructions=[],
                    signers=[],
                )
            )
            # Without actual parsing of logs, we can't fill chain_players.
            # If you had a way to parse logs or return_data, you'd do it here.
            # We'll just pretend no data is returned.
            start_index = end_index
        except RPCException as e:
            if "InvalidRange" in str(e):
                break
            else:
                raise

    return chain_players

async def run_comparison(program: Program, provider: Provider, game_pda: Pubkey, game_number: int, all_players):
    chain_players = await get_player_list(program, game_pda, game_number)

    server_set = set(all_players)
    chain_set = set(chain_players)  # empty here
    missing_on_chain = server_set - chain_set
    print("Players on servers but not on chain:", missing_on_chain)

async def main_async(all_players):
    # Set up provider and program
    client = AsyncClient("http://localhost:8899", commitment=Confirmed)
    wallet = Wallet.local()
    provider = Provider(client, wallet)

    idl_path = Path("../target/idl/fancoin.json")
    with idl_path.open() as f:
        idl_json = f.read()

    idl = Idl.from_json(idl_json)

    program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
    program = Program(idl, program_id, provider)

    # Assume game_pda known:
    game_number = 1
    game_pda, _ = Pubkey.find_program_address(
        [b"game", game_number.to_bytes(4, "little")],
        program_id
    )

    # Don't close client here; let script end handle it.
    return program, provider, game_pda, game_number

def main():
    region = 0xFF  # All regions
    app_id = 20  # TFC's Steam App ID

    print("Querying master server for TFC servers...")
    tfc_servers = list(query_master_server(region, app_id))
    unique_ips = {}
    for ip, port in tfc_servers:
        if ip not in unique_ips:
            unique_ips[ip] = (ip, port)

    deduped_servers = list(unique_ips.values())
    print(f"Number of unique TFC servers found: {len(deduped_servers)}")

    all_players = []

    max_workers = 10
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(query_server_for_players, ip, port): (ip, port) for ip, port in deduped_servers}
        for future in as_completed(futures):
            ip, port = futures[future]
            try:
                player_names = future.result()  # This returns a list of player names
                all_players.extend(player_names)
            except Exception as e:
                print(f"Error querying {ip}:{port} - {e}")

    print("All players collected in memory:", all_players)

    # Now run async steps
    program, provider, game_pda, game_number = asyncio.run(main_async(all_players))
    asyncio.run(run_comparison(program, provider, game_pda, game_number, all_players))

if __name__ == "__main__":
    main()

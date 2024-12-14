import socket
import struct
import a2s
import re
import json
from solders.keypair import Keypair
from concurrent.futures import ThreadPoolExecutor, as_completed

def query_master_server(region, app_id):
    master_server = ("hl1master.steampowered.com", 27011)
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

def generate_account():
    kp = Keypair()
    kp_bytes = bytes(kp)  # 64 bytes: first 32 are secret key, next 32 are public key
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

    all_player_data = {}

    # Use ThreadPoolExecutor for concurrent queries
    max_workers = 10  # can be more than core count for IO-bound tasks
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(query_server_for_players, ip, port): (ip, port) for ip, port in deduped_servers}
        for future in as_completed(futures):
            ip, port = futures[future]
            try:
                player_data = future.result()
                all_player_data.update(player_data)
            except Exception as e:
                print(f"Error querying {ip}:{port} - {e}")

    save_as_json(all_player_data)
    print("Player data saved to player_wallets.json")

if __name__ == "__main__":
    main()

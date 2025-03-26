import socket
import struct
import a2s
import re
import json
from solders.keypair import Keypair
from concurrent.futures import ThreadPoolExecutor, as_completed

def query_master_server(region, app_id):
    master_server = ("hl1master.steampowered.com", 27011)
    # This is the known working request that returns TFC servers
    request = b"\x31\xFF0.0.0.0:0\x00\\gamedir\\tfc\x00"

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)

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
        ip = ".".join(map(str, data[i:i+4]))
        port = struct.unpack(">H", data[i+4:i+6])[0]
        if ip == "0.0.0.0" and port == 0:
            break
        servers.append((ip, port))
    return servers

def clean_brackets_and_contents(name):
    # Example of removing color codes, brackets, and special characters
    name = re.sub(r'\^\d', '', name)
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\{.*?\}', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'<.*?>', '', name)
    name = re.sub(r'[\[\]\{\}\(\)<>]', '', name)
    name = re.sub(r'[^a-zA-Z0-9_-]', '', name)
    return name.strip()

def generate_two_accounts():
    """Generate two Keypairs:
       1) player_authority
       2) player_info_acc
    and return them as hex + Pubkey strings.
    """
    def _make_keypair():
        kp = Keypair()
        kp_bytes = bytes(kp)  # 64 bytes: [first 32=secret, next 32=public]
        private_key_hex = kp_bytes[:32].hex()
        address_str = str(kp.pubkey())
        return private_key_hex, address_str

    auth_priv, auth_addr = _make_keypair()
    info_priv, info_addr = _make_keypair()

    return {
        "player_authority_private_key": auth_priv,
        "player_authority_address": auth_addr,
        "player_info_acc_private_key": info_priv,
        "player_info_acc_address": info_addr
    }

def decode_and_collect_players(players):
    """Given a2s.Player objects from a2s.players, sanitize names and generate two keypairs each."""
    player_data = {}
    if players:
        for p in players:
            sanitized_name = clean_brackets_and_contents(p.name)
            if sanitized_name:
                two_accts = generate_two_accounts()
                player_data[sanitized_name] = two_accts
    return player_data

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

def get_player_list_a2s(ip, port):
    """Use the a2s library to fetch the player list from a server."""
    try:
        address = (ip, port)
        players = a2s.players(address)
        return players
    except Exception as e:
        print(f"Failed to query server at {ip}:{port}: {e}")
        return []

def query_server_for_players(ip, port):
    """Encapsulates the logic for querying one server with a2s, then building the dict."""
    print(f"Querying server: {ip}:{port}")
    players = get_player_list_a2s(ip, port)
    return decode_and_collect_players(players)

def save_as_json(data, filename='player_wallets.json'):
    with open(filename, 'w') as json_file:
        json.dump(data, json_file, indent=4)

def main():
    region = 0xFF  # All regions
    app_id = 20    # TFC's Steam App ID

    print("Querying master server for TFC servers...")
    tfc_servers = list(query_master_server(region, app_id))

    # Deduplicate by IP
    unique_ips = {}
    for ip, port in tfc_servers:
        if ip not in unique_ips:
            unique_ips[ip] = (ip, port)

    deduped_servers = list(unique_ips.values())
    print(f"Number of unique TFC servers found: {len(deduped_servers)}")

    all_player_data = {}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    max_workers = 10
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(query_server_for_players, ip, port): (ip, port)
            for ip, port in deduped_servers
        }
        for future in as_completed(futures):
            ip, port = futures[future]
            try:
                partial_data = future.result()
                all_player_data.update(partial_data)
            except Exception as e:
                print(f"Error querying {ip}:{port} - {e}")

    save_as_json(all_player_data, 'player_wallets.json')
    print("\nPlayer data saved to player_wallets.json")

if __name__ == "__main__":
    main()

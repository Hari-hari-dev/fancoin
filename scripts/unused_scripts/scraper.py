import socket
import struct
import re
import json
import concurrent.futures
import a2s
from solders.keypair import Keypair

# -------------------------------------
# Master Server Query Integration
# -------------------------------------

def query_master_server(region, app_id):
    # Master server address and port
    master_server = ("hl1master.steampowered.com", 27011)
    
    # Create a UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)

    # Request format for the master server
    # '\x31' is the header, followed by region and app_id filter
    request = b'\x31' + bytes([region]) + b'\\appid\\' + str(app_id).encode() + b'\\'
    response_data = b''
    
    # Initial IP range: 0.0.0.0:0
    last_ip = b'0.0.0.0:0'

    # This function will yield servers as it finds them
    while True:
        # Send query
        sock.sendto(request + last_ip, master_server)
        
        try:
            # Receive response
            response_data, _ = sock.recvfrom(4096)
        except socket.timeout:
            print("Request timed out")
            break
        
        # Parse server entries from response
        servers = parse_response(response_data)
        
        # Break if no more servers
        if not servers:
            break
        
        # Update last_ip to the last server in this batch
        last_ip = format_server(servers[-1])
        for srv in servers:
            yield srv

def parse_response(data):
    # Split response into chunks of 6 bytes (4 bytes for IP, 2 bytes for port)
    servers = []
    # Response starts with b'\xFF\xFF\xFF\xFF\x66\x0A', so we start from 6
    for i in range(6, len(data), 6):
        ip = ".".join(map(str, data[i:i+4]))
        port = struct.unpack(">H", data[i+4:i+6])[0]
        # Check for terminator
        if ip == "0.0.0.0" and port == 0:
            break
        servers.append((ip, port))
    return servers

def format_server(server):
    # Format server IP and port for the next query
    return f'{server[0]}:{server[1]}'.encode()

# -------------------------------------
# Helper Functions
# -------------------------------------

def clean_brackets_and_contents(name):
    """Remove formatting from names."""
    # Remove color codes
    name = re.sub(r'\^\d', '', name)
    # Remove bracketed contents
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\{.*?\}', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'<.*?>', '', name)
    # Remove any stray brackets
    name = re.sub(r'[\[\]\{\}\(\)<>]', '', name)
    # Remove non-alphanumeric except underscore and hyphen
    name = re.sub(r'[^a-zA-Z0-9_-]', '', name)
    return name.strip()

def generate_account():
    """Generate a Solana account (keypair) using solders."""
    kp = Keypair()
    private_key_hex = kp.secret_key.hex()
    public_key_str = str(kp.pubkey())
    return private_key_hex, public_key_str

def decode_and_collect_players(players):
    """Convert A2S player list into a dict {player_name: {private_key, public_key}}."""
    player_data = {}
    for player in players:
        sanitized_name = clean_brackets_and_contents(player.name)
        if sanitized_name:
            private_key, public_key = generate_account()
            player_data[sanitized_name] = {
                "private_key": private_key,
                "public_key": public_key
            }
    return player_data

def save_as_json(data, filename='player_wallets.json'):
    with open(filename, 'w') as json_file:
        json.dump(data, json_file, indent=4)

# -------------------------------------
# Querying Each Server
# -------------------------------------

def get_server_info_and_players(ip, port):
    """
    Query server for info and players using A2S.
    Returns tuple: (ip, port, title, players_dict)
    """
    address = (ip, port)
    try:
        info = a2s.info(address)
        title = info.server_name if info.server_name else "Unknown Server"
    except Exception as e:
        print(f"Failed to get info from {ip}:{port} - {e}")
        title = "Unknown Server"

    try:
        players = a2s.players(address)
    except Exception as e:
        print(f"Failed to query players from {ip}:{port} - {e}")
        players = []

    player_data = decode_and_collect_players(players)
    return (ip, port, title, player_data)


def main():
    region = 0xFF  # All regions
    app_id = 20  # TFC's Steam App ID
    
    print("Querying master server for TFC servers...")
    tfc_servers = list(query_master_server(region, app_id))

    # Deduplicate by IP (keep first occurrence)
    unique_ips = {}
    for ip, port in tfc_servers:
        if ip not in unique_ips:
            unique_ips[ip] = (ip, port)

    deduped_servers = list(unique_ips.values())
    print(f"Number of unique TFC servers found: {len(deduped_servers)}")

    all_player_data = {}

    # Multi-threaded querying for each server
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(get_server_info_and_players, ip, port) for ip, port in deduped_servers]
        for future in concurrent.futures.as_completed(futures):
            ip, port, title, player_data = future.result()
            if player_data:
                print(f"Found {len(player_data)} players on {title} ({ip}:{port})")
            all_player_data.update(player_data)

    # Save player data to JSON
    save_as_json(all_player_data)
    print("Player data saved to player_wallets.json")

if __name__ == "__main__":
    main()

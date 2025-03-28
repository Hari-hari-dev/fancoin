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
from anchorpy.program.namespace.instruction import AccountMeta

# Globals that need to be set after setup:
program = None
provider = None
dapp_pda = None
program_id = None
dapp_pda = None  # We'll store the DApp PDA here

def load_validator_keypair(filename='val1-keypair.json'):
    """Load the validator keypair from a JSON file containing secret_key hex."""
    def load_keypair(path: str) -> Keypair:
        with Path(path).open() as f:
            secret = json.load(f)
        return Keypair.from_bytes(bytes(secret[0:64]))

    kp = load_keypair("./val1-keypair.json")
    return kp

async def get_all_onchain_players_alt() -> list[str]:
    """
    Uses program.account["PlayerPda"].all() to retrieve all PlayerPda accounts.
    Returns a list of player names found on-chain.
    """
    print("[DEBUG] Retrieving all PlayerPda accounts via anchorpy...")
    all_records = await program.account["PlayerPda"].all()
    print(f"[DEBUG] Found {len(all_records)} PlayerPda records on-chain.")

    # Extract the 'name' field from each player's account data
    player_names = []
    for record in all_records:
        account_data = record.account
        player_names.append(account_data.name)
    print(f"[DEBUG] Extracted {len(player_names)} player names from chain.")
    return player_names

async def debug_check_dapp_pda():
    # Fetch the on-chain data for the DApp account
    dapp_data = await program.account["DApp"].fetch(dapp_pda)
    
    # Print key fields
    print("[DEBUG] DApp Account Data:")
    print(f"         owner                = {dapp_data.owner}")
    print(f"         global_player_count = {dapp_data.global_player_count}")

def get_player_list_for_dapp(matched_players):
    """Groups matched players in chunks of 16 for batch minting."""
    return [matched_players[i : i + 16] for i in range(0, len(matched_players), 16)]

def submit_minting_list_for_dapp(dapp_number, chunked_player_list):
    """
    Stub function that *simulates* minting. 
    Real on-chain minting would happen in a separate call.
    """
    validator_kp = load_validator_keypair()
    print(f"Submitting minting list for dapp_number={dapp_number} with validator={validator_kp.pubkey()}")
    for idx, player_group in enumerate(chunked_player_list):
        print(f"Submitting group {idx} of size {len(player_group)}: {player_group}")
    print("Minting list submission simulation complete.")

async def submit_minting_list_for_dapp_async(dapp_number, chunked_player_list, executor):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, submit_minting_list_for_dapp, dapp_number, chunked_player_list)

# -----------------------------------------------------------------------------
# NEW FUNCTION: Actually call on-chain "submit_minting_list" and fetch logs
# -----------------------------------------------------------------------------
async def debug_submit_minting_list_onchain(dapp_number: int, player_names: list[str]):
    """
    Calls the on-chain 'submit_minting_list' instruction for real,
    automatically deriving the validator PDA from (dapp_number, validator pubkey),
    fetches logs to see minted amounts,
    then re-fetches each player's PDA to see updated last_minted (if your code sets it).
    """
    global program, dapp_pda

    # 1) We'll load the validator keypair as the signer
    validator_kp = load_validator_keypair()

    # 2) Derive the validator PDA by seeds=[b"validator", dapp_number, validator.key()]
    #    matching the on-chain approach in your "SubmitMintingList" context
    (validator_pda, _) = Pubkey.find_program_address(
        [b"validator", dapp_number.to_bytes(4, "little"), bytes(validator_kp.pubkey())],
        program.program_id
    )

    # 3) Build the context 
    ctx = Context(
        accounts={
            "dapp": dapp_pda,
            "validatorPda": validator_pda,
            "validator": validator_kp.pubkey(),
        },
        signers=[validator_kp]
    )

    print(f"[DEBUG] On-chain 'submit_minting_list' for dapp_number={dapp_number}, players={player_names}")
    try:
        tx_sig = await program.rpc["submit_minting_list"](
            dapp_number,
            player_names,
            ctx=ctx
        )
        print(f"[INFO] submit_minting_list transaction signature: {tx_sig}")
    except RPCException as exc:
        print(f"[ERROR] RPCException calling submit_minting_list: {exc}")
        return

    # 4) Fetch logs to see "SPL minted XXXXX microtokens => player='...'" or "No tokens => outside 7..34 window"
    provider = program.provider
    confirmed_tx = await provider.connection.get_transaction(tx_sig, encoding="json")
    if confirmed_tx.value is None:
        print("[DEBUG] No transaction found or logs missing.")
        return

    tx_meta = confirmed_tx.value.transaction.meta
    if tx_meta is None or tx_meta.log_messages is None:
        print("[DEBUG] No logs in transaction meta.")
        return

    logs = tx_meta.log_messages
    print("[DEBUG] Raw logs from submit_minting_list transaction:")
    for line in logs:
        print(f"   {line}")

    # 5) Optionally re-fetch each player's PDA to see last_minted or total minted
    all_players = await program.account["PlayerPda"].all()
    for pname in player_names:
        rec = next((r for r in all_players if r.account.name == pname), None)
        if rec:
            print(f"[DEBUG] Player '{pname}' => last_minted={rec.account.last_minted}")
        else:
            print(f"[DEBUG] No on-chain PlayerPda found for name={pname}")

# -----------------------------------------------------------------------------
# Quakeworld/A2S logic (unchanged)
# -----------------------------------------------------------------------------
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

async def main():
    try:
        print("Setting up provider and loading program...")
        client = AsyncClient("http://localhost:8899", commitment=Confirmed)
        wallet = Wallet.local()

        global provider, program, dapp_pda, program_id, dapp_pda
        provider = Provider(client, wallet)

        # Load IDL
        idl_path = Path("../target/idl/fancoin.json")
        if not idl_path.exists():
            print(f"IDL file not found at {idl_path.resolve()}")
            return

        with idl_path.open() as f:
            idl_json = f.read()

        idl = Idl.from_json(idl_json)
        program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
        program = Program(idl, program_id, provider)
        print("Program loaded successfully.")

        # We assume dapp_number=1 is already initialized.
        dapp_number = 1
        (dapp_pda, _) = Pubkey.find_program_address(
            [b"dapp", dapp_number.to_bytes(4, "little")],
            program_id
        )
        print(f"[DEBUG] Found dapp_pda: {dapp_pda}")

        (dapp_pda, dapp_bump) = Pubkey.find_program_address([b"dapp"], program.program_id)
        print(f"[DEBUG] Found dapp_pda: {dapp_pda}, bump={dapp_bump}")

        # ------------- 
        # EARLY DEBUG BITS: Check the "Dapp" on-chain data for dapp_number=1
        # -------------
        try:
            dapp_data = await program.account["Dapp"].fetch(dapp_pda)
            print(f"[DEBUG] On-chain Dapp Data =>")
            print(f"         dapp_number       = {dapp_data.dapp_number}")
            print(f"         validator_count   = {dapp_data.validator_count}")
            print(f"         status            = {dapp_data.status}")
            print(f"         description       = {dapp_data.description}")
            print(f"         last_seed         = {dapp_data.last_seed}")
            print(f"         last_punch_in_time= {dapp_data.last_punch_in_time}")
        except:
            print("[DEBUG] Unable to fetch Dapp data. Possibly not initialized or other issue.")

        # -------------
        # EARLY DEBUG: See which validator PDAs exist
        # -------------
        val_records = await program.account["ValidatorPda"].all()
        if not val_records:
            print("[DEBUG] No ValidatorPda accounts found on-chain.")
        else:
            print(f"[DEBUG] Found {len(val_records)} ValidatorPda records on-chain:")
            for idx, rec in enumerate(val_records):
                print(f"[DEBUG]  ValidatorPda #{idx}: pubkey={rec.public_key}, address={rec.account.address}, last_activity={rec.account.last_activity}")

        await debug_check_dapp_pda()

        # -----------
        # Query TFC servers
        region = 0xFF  # All regions
        app_id = 20    # TFC's Steam App ID
        print("Querying master server for TFC servers...")
        tfc_servers = list(query_master_server(region, app_id))
        unique_ips = {}
        for ip, port in tfc_servers:
            if ip not in unique_ips:
                unique_ips[ip] = (ip, port)

        deduped_servers = list(unique_ips.values())
        print(f"Number of unique TFC servers found: {len(deduped_servers)}")

        # Collect local server players
        all_player_data = {}
        for ip, port in deduped_servers:
            print(f"Querying server: {ip}:{port}")
            players = get_player_list_a2s(ip, port)
            player_data = decode_and_collect_players(players)
            all_player_data.update(player_data)

        save_as_json(all_player_data)

        # -----------
        # Compare with on-chain
        print("[DEBUG] Fetching on-chain players with the anchorpy .all() approach.")
        all_onchain_players = await get_all_onchain_players_alt()

        server_players = list(all_player_data.keys())
        matched_players = list(set(server_players).intersection(set(all_onchain_players)))

        if matched_players:
            print(f"Matched {len(matched_players)} players with the DApp registry.")
            chunked = get_player_list_for_dapp(matched_players)

            # 1) Local simulation
            executor = ThreadPoolExecutor(max_workers=10)
            await submit_minting_list_for_dapp_async(dapp_number, chunked, executor)
            executor.shutdown(wait=True)

            # 2) Optionally call on-chain instruction for real
            flattened_players = [p for group in chunked for p in group]
            if flattened_players:
                print("[DEBUG] Actually calling on-chain 'submit_minting_list' with these matched players.")
                await debug_submit_minting_list_onchain(dapp_number, flattened_players)
                print("[INFO] Done with on-chain submit_minting_list call.")
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

import asyncio
import json
import traceback
from pathlib import Path
from enum import IntEnum  # Ensure IntEnum is imported

import re  # **Added:** Importing the 're' module
import struct

# Anchor / Solana
from solders.rpc.responses import SendTransactionResp
from anchorpy import Program, Provider, Wallet, Idl, Context
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from solders.system_program import transfer, TransferParams
from solana.rpc.types import TxOpts
from solana.transaction import Transaction, Signature

# SPL Token constants
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
RENT_SYSVAR_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

LAMPORTS_TO_SEND = 10_000_000  # 0.01 SOL

###############################################################################
# Helper Functions
###############################################################################

def derive_ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """Derive the associated token account (ATA) address for (owner, mint)."""
    (ata_pubkey, _) = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
        ASSOCIATED_TOKEN_PROGRAM_ID,
    )
    return ata_pubkey

def load_keypair(path: str) -> Keypair:
    """Load a Keypair from a JSON file containing 'player_authority_private_key' in hex."""
    with Path(path).open() as f:
        secret = json.load(f)
    
    authority_hex = secret.get("player_authority_private_key")
    if not authority_hex:
        raise ValueError(f"Missing 'player_authority_private_key' in {path}")
    
    authority_bytes = bytes.fromhex(authority_hex)
    if len(authority_bytes) == 32:
        return Keypair.from_seed(authority_bytes)
    elif len(authority_bytes) == 64:
        return Keypair.from_bytes(authority_bytes)
    else:
        raise ValueError(f"Invalid authority key length: {len(authority_bytes)} bytes")

async def send_lamports(
    payer_wallet: Wallet,
    recipient_pubkey: Pubkey,
    lamports: int,
    connection: AsyncClient
) -> str:
    """
    Send lamports from the payer to the recipient, returning the tx signature.
    """
    try:
        ix = transfer(TransferParams(
            from_pubkey=payer_wallet.public_key,
            to_pubkey=recipient_pubkey,
            lamports=lamports
        ))
        tx = Transaction()
        tx.add(ix)
        latest_blockhash_resp = await connection.get_latest_blockhash()
        if latest_blockhash_resp.value is None:
            raise Exception("Failed to get a recent blockhash")

        blockhash = latest_blockhash_resp.value.blockhash
        tx.recent_blockhash = blockhash
        tx.fee_payer = payer_wallet.public_key
        signed_tx = payer_wallet.sign_transaction(tx)

        resp = await connection.send_raw_transaction(
            signed_tx.serialize(),
            opts=TxOpts(preflight_commitment=Confirmed)
        )
        print(f"Sent {lamports} lamports to {recipient_pubkey}. Transaction Signature: {resp}")
        print(f"Type of resp: {type(resp)}")
        print(f"Contents of resp: {resp}")

        # Extract signature
        if isinstance(resp, SendTransactionResp):
            sig_str = str(resp.value)
            sig_obj = Signature.from_string(sig_str)
        elif isinstance(resp, str):
            sig_obj = Signature.from_string(resp)
        else:
            raise Exception("Unexpected response type from send_raw_transaction")

        confirm_resp = await connection.confirm_transaction(sig_obj, Confirmed)
        if not confirm_resp.value:
            raise Exception(f"Transaction {sig_obj} not confirmed.")

        tx_details = await connection.get_transaction(sig_obj, encoding='json')
        if tx_details.value and tx_details.value.transaction.meta:
            logs = tx_details.value.transaction.meta.log_messages
            if logs:
                # Example: Extract compute units consumed
                cu_regex = re.compile(r'Program \S+ consumed (\d+) of (\d+) compute units')
                consumed_cu = None
                max_cu = None
                for line in logs:
                    match = cu_regex.search(line)
                    if match:
                        consumed_cu = int(match.group(1))
                        max_cu = int(match.group(2))
                        break
                if consumed_cu is not None:
                    print(f"[DEBUG] Compute units => {consumed_cu}/{max_cu}")
                else:
                    print("[DEBUG] No compute units info found in logs.")
            else:
                print("[DEBUG] No log messages returned for transaction.")
        else:
            print("[DEBUG] No transaction meta/logs found.")

        print(f"Confirmed airdrop transaction {sig_obj} for {recipient_pubkey}")
        return str(sig_obj)

    except RPCException as e:
        print(f"[ERROR] Error transferring lamports to {recipient_pubkey}: {e}")
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"[ERROR] Unexpected error transferring lamports to {recipient_pubkey}: {e}")
        traceback.print_exc()
        raise

async def send_lamports_with_retry(
    payer_wallet: Wallet,
    recipient_pubkey: Pubkey,
    lamports: int,
    connection: AsyncClient,
    retries: int = 3,
    delay: int = 3
) -> str:
    """Wrapper that retries sending lamports if preflight fails."""
    for attempt in range(1, retries + 1):
        try:
            return await send_lamports(payer_wallet, recipient_pubkey, lamports, connection)
        except Exception as e:
            print(f"[WARNING] Attempt {attempt} failed: {e}")
            if attempt < retries:
                backoff_time = delay * (2 ** (attempt - 1))  # Exponential backoff
                print(f"[INFO] Retrying in {backoff_time} seconds...")
                await asyncio.sleep(backoff_time)
            else:
                print(f"[ERROR] All {retries} attempts failed for {recipient_pubkey}")
                return ""

###############################################################################
# Utility Enums, etc.
###############################################################################
class GameStatus(IntEnum):
    Probationary = 0
    Whitelisted = 1
    Blacklisted = 2

###############################################################################
# The register_player_pda function
###############################################################################
async def register_player_pda(
    program: Program,
    dapp_pda: Pubkey,
    fancy_mint: Pubkey,
    player_name: str,
    player_keypair: Keypair,    # Player's Keypair used as `user`
    reward_pubkey: Pubkey,
    max_retries: int = 5
):
    """
    Registers a player by initializing their PlayerPda and PlayerNamePda.
    Implements a retry mechanism for handling concurrent registration conflicts.
    """

    for attempt in range(1, max_retries + 1):
        try:
            # 1) Fetch typed DApp account object
            dapp_data = await program.account["DApp"].fetch(dapp_pda)
            current_count = dapp_data.global_player_count
            print(f"[DEBUG] current_count from on-chain DApp = {current_count}")

            # 2) Derive the new player_pda
            dapp_global_count_bytes = current_count.to_bytes(4, 'little')  # Corrected
            (player_pda_pubkey, _) = Pubkey.find_program_address(
                [b"player_pda", dapp_global_count_bytes],
                program.program_id
            )
            print(f"[DEBUG] Derived player_pda => {player_pda_pubkey}")

            # 3) Derive the player's ATA manually
            player_pubkey = player_keypair.pubkey()
            user_ata_pubkey = derive_ata(player_pubkey, fancy_mint)
            print(f"[DEBUG] user_ata => {user_ata_pubkey} for player {player_name}")

            # 4) Derive the player_name_pda based on the name
            player_name_pda_seeds = [b"player_name", player_name.encode('utf-8')]
            player_name_pda, name_bump = Pubkey.find_program_address(player_name_pda_seeds, program.program_id)
            print(f"[DEBUG] Derived player_name_pda => {player_name_pda}")

            # 5) Prepare accounts
            accounts = {
                "dapp": dapp_pda,
                "fancy_mint": fancy_mint,
                "player_pda": player_pda_pubkey,
                "player_name_pda": player_name_pda,
                "user": player_pubkey,  # Player's Pubkey as 'user'
                "user_ata": user_ata_pubkey,
                "token_program": TOKEN_PROGRAM_ID,
                "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                "system_program": SYS_PROGRAM_ID,
                "rent": RENT_SYSVAR_ID,
            }

            # 6) Call the register_player_pda instruction
            tx_sig = await program.rpc["register_player_pda"](
                player_name,  # Passed as positional argument
                ctx=Context(
                    accounts=accounts,
                    signers=[player_keypair]
                )
            )
            print(f"Player '{player_name}' => PlayerPda registered. Tx Sig: {tx_sig}")

            # 7) Optionally fetch transaction logs
            confirmed_tx = await program.provider.connection.get_transaction(
                tx_sig, encoding='json'
            )
            if confirmed_tx.value and confirmed_tx.value.transaction.meta:
                logs = confirmed_tx.value.transaction.meta.log_messages
                if logs:
                    # Example: Extract compute units consumed
                    cu_regex = re.compile(r'Program \S+ consumed (\d+) of (\d+) compute units')
                    consumed_cu = None
                    max_cu = None
                    for line in logs:
                        match = cu_regex.search(line)
                        if match:
                            consumed_cu = int(match.group(1))
                            max_cu = int(match.group(2))
                            break
                    if consumed_cu is not None:
                        print(f"[DEBUG] Compute units => {consumed_cu}/{max_cu}")
                    else:
                        print("[DEBUG] No compute units info found in logs.")
                else:
                    print("[DEBUG] No log messages returned for transaction.")
            else:
                print("[DEBUG] No transaction meta/logs found.")

            # 8) Verify ATA Ownership
            # Fetch ATA account info using Solana RPC
            ata_account_info_resp = await program.provider.connection.get_account_info(
                reward_pubkey, commitment=Confirmed
            )
            if ata_account_info_resp.value is None:
                print(f"[ERROR] ATA {reward_pubkey} does not exist for player '{player_name}'.")
            else:
                # The on-chain owner should be the TOKEN_PROGRAM_ID
                ata_onchain_owner = ata_account_info_resp.value.owner
                print(f"[DEBUG] On-chain owner of ATA = {ata_onchain_owner}")
                if ata_onchain_owner != TOKEN_PROGRAM_ID:
                    print(f"[WARNING] ATA {reward_pubkey} is owned by {ata_onchain_owner}, "
                            f"expected {TOKEN_PROGRAM_ID}.")
                else:
                    print(f"[INFO] ATA {reward_pubkey} is correctly owned by the Token Program.")

                    # Additionally, verify the 'authority' field within the ATA
                    ata_data_bytes = ata_account_info_resp.value.data
                    if len(ata_data_bytes) < 64:
                        print(f"[ERROR] ATA data length is too small to read authority. Got {len(ata_data_bytes)} bytes.")
                    else:
                        # Extract the 32 bytes of 'owner' (authority) at offset 32
                        authority_bytes = ata_data_bytes[32:64]
                        ata_authority = Pubkey(authority_bytes)
                        if ata_authority != player_pubkey:
                            print(f"[ERROR] ATA {reward_pubkey} authority is {ata_authority}, "
                                    f"expected {player_pubkey}. Potential mismatch!")
                        else:
                            print(f"[INFO] ATA {reward_pubkey} authority field matches the player's wallet: {ata_authority}")

                    # Optional: Check rent exemption
                    ata_length = len(ata_data_bytes)
                    min_rent_resp = await program.provider.connection.get_minimum_balance_for_rent_exemption(ata_length)
                    if min_rent_resp.value is not None:
                        required_lamports = min_rent_resp.value
                        current_lamports = ata_account_info_resp.value.lamports
                        if current_lamports < required_lamports:
                            deficit = required_lamports - current_lamports
                            print(f"[WARNING] ATA {reward_pubkey} is not rent-exempt. Needs additional {deficit} lamports.")
                            # Optionally, send lamports to ATA
                            # Uncomment the following lines if you wish to send lamports to the ATA
                            # Note: This is generally unnecessary as the ATA should be rent-exempt upon creation
                            # tx_sig2 = await send_lamports_with_retry(
                            #     payer_wallet=provider.wallet,
                            #     recipient_pubkey=reward_pubkey,
                            #     lamports=deficit,
                            #     connection=program.provider.connection
                            # )
                            # print(f"[INFO] Sent {deficit} lamports to ATA {reward_pubkey}. Tx Sig: {tx_sig2}")
                    else:
                        print(f"[ERROR] Failed to fetch minimum balance for rent exemption for ATA {reward_pubkey}.")

            # 9) All done for this attempt
            print(f"[INFO] Player '{player_name}' registration and ATA verification completed.")
            break  # Exit the retry loop since registration succeeded

        except RPCException as e:
            if "AccountAlreadyInitialized" in str(e):
                print(f"[ERROR] The name '{player_name}' is already taken or PDA conflict occurred.")
                if attempt < max_retries:
                    backoff_time = 1 * (2 ** (attempt - 1))  # Exponential backoff: 1, 2, 4, 8, 16 seconds
                    print(f"[INFO] Retrying registration for '{player_name}' in {backoff_time} seconds (Attempt {attempt}/{max_retries})...")
                    await asyncio.sleep(backoff_time)
                    continue  # Retry the registration
                else:
                    print(f"[ERROR] Max retries reached for '{player_name}'. Skipping registration.")
                    return
            else:
                print(f"[ERROR] Registering player '{player_name}' => RPCException: {e}")
                traceback.print_exc()
                return

    ###############################################################################
    # Main
    ###############################################################################
async def main():
    client = AsyncClient("http://localhost:8899", commitment=Confirmed)
    wallet = Wallet.local()
    provider = Provider(client, wallet)

    # 1) Check local wallet balance
    payer_balance_resp = await client.get_balance(wallet.public_key)
    if payer_balance_resp.value is not None:
        print(f"Payer wallet balance: {payer_balance_resp.value} lamports")
        if payer_balance_resp.value < LAMPORTS_TO_SEND * 10:
            print("[WARNING] Payer wallet may have low balance.")
    else:
        print("[ERROR] Could not fetch payer wallet balance.")
        return

    # 2) Load IDL
    idl_path = Path("../target/idl/fancoin.json")
    if not idl_path.exists():
        print(f"[ERROR] IDL not found at {idl_path.resolve()}")
        return
    with idl_path.open() as f:
        idl = Idl.from_json(f.read())

    # 3) Program + DApp PDAs
    program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
    program = Program(idl, program_id, provider)
    print("Program loaded successfully.")

    (dapp_pda, _) = Pubkey.find_program_address([b"dapp"], program_id)
    print(f"[DEBUG] Using dapp_pda={dapp_pda}")

    # 4) The Mint the DApp uses
    fancy_mint = Pubkey.from_string("DVkPNrxdgGxF5fqvnKgXj7DWcRSdimLChXKwAKYk7fiJ")

    # 5) Grab JSON keys
    keys_folder = Path("player_keys")
    if not keys_folder.exists() or not keys_folder.is_dir():
        print(f"[ERROR] Folder '{keys_folder}' does not exist or is not a directory.")
        return
    json_files = list(keys_folder.glob("*.json"))
    if not json_files:
        print(f"[INFO] No .json files found in '{keys_folder}'. Exiting.")
        return

    # 6) Define a semaphore to limit concurrency to 5 workers (adjusted)
    semaphore = asyncio.Semaphore(1)

    # 7) Define an async function to handle player registration with semaphore
    async def register_player_with_semaphore(json_file):
        async with semaphore:
            player_name = json_file.stem
            try:
                with json_file.open() as f:
                    data = json.load(f)

                # 7a) Load the player's keypair (only player_authority_private_key)
                authority_hex = data.get("player_authority_private_key")
                if not authority_hex:
                    print(f"[ERROR] 'player_authority_private_key' not found in {json_file}")
                    return
                try:
                    authority_bytes = bytes.fromhex(authority_hex)
                except ValueError:
                    print(f"[ERROR] 'player_authority_private_key' is not valid hex in {json_file}")
                    return

                # Ensure the secret key is exactly 32 or 64 bytes
                if len(authority_bytes) == 32:
                    # Seed-based Keypair
                    player_keypair = Keypair.from_seed(authority_bytes)
                elif len(authority_bytes) == 64:
                    # Full secret key
                    player_keypair = Keypair.from_bytes(authority_bytes)
                else:
                    print(f"[ERROR] Invalid 'player_authority_private_key' length in {json_file}. "
                            f"Expected 32 or 64 bytes, got {len(authority_bytes)} bytes.")
                    return

                player_pubkey = player_keypair.pubkey()
                print(f"\n[INFO] Registering player => {player_name} with pubkey {player_pubkey}")

                # 7b) Always use the derived ATA as the reward_pubkey for consistency
                reward_pubkey = derive_ata(player_pubkey, fancy_mint)
                print(f"[DEBUG] Derived reward_pubkey (ATA) => {reward_pubkey} for player {player_name}")

                # 7c) Check if the player already has sufficient lamports
                balance_resp = await client.get_balance(player_pubkey)
                if balance_resp.value is not None and balance_resp.value >= LAMPORTS_TO_SEND:
                    print(f"[INFO] Player {player_pubkey} already has sufficient lamports "
                            f"({balance_resp.value} lamports). Skipping airdrop.")
                else:
                    # 7c) Airdrop lamports to the player's main account
                    print(f"[INFO] Airdropping {LAMPORTS_TO_SEND} lamports to {player_pubkey}")
                    try:
                        tx_sig = await send_lamports_with_retry(
                            payer_wallet=wallet,
                            recipient_pubkey=player_pubkey,
                            lamports=LAMPORTS_TO_SEND,
                            connection=client
                        )
                        if tx_sig:
                            print(f"[SUCCESS] Airdropped {LAMPORTS_TO_SEND} lamports to {player_pubkey}. "
                                    f"Tx Sig: {tx_sig}")
                        else:
                            print(f"[ERROR] Airdrop failed for {player_pubkey}.")
                    except Exception as e:
                        print(f"[ERROR] Failed to airdrop lamports to {player_pubkey}: {e}")
                        return

                # 7d) Verify player's balance after airdrop
                balance_resp = await client.get_balance(player_pubkey)
                if balance_resp.value is not None:
                    print(f"[DEBUG] Player {player_pubkey} balance: {balance_resp.value} lamports")
                    if balance_resp.value < 4_085_520:
                        print(f"[ERROR] Player {player_pubkey} has insufficient lamports after airdrop: "
                                f"{balance_resp.value} < 4,085,520")
                        return
                else:
                    print(f"[ERROR] Failed to fetch balance for {player_pubkey}. Skipping player registration.")
                    return

                # 7e) Register the player on-chain with retries
                await register_player_pda(
                    program=program,
                    dapp_pda=dapp_pda,
                    fancy_mint=fancy_mint,
                    player_name=player_name,
                    player_keypair=player_keypair,   # Player's Keypair as 'user'
                    reward_pubkey=reward_pubkey,
                )

                # Optional: Add a short delay to ensure the transaction is processed
                await asyncio.sleep(0.5)

            except Exception as e:
                print(f"[ERROR] Unexpected error for {json_file}: {e}")
                traceback.print_exc()

    # 8) Create a list of tasks for all players
    tasks = [asyncio.create_task(register_player_with_semaphore(json_file)) for json_file in json_files]

    # 9) Wait for all tasks to complete
    await asyncio.gather(*tasks)

    print("\nAll players from 'player_keys/' folder have been registered and funded.")

if __name__ == "__main__":
    asyncio.run(main())

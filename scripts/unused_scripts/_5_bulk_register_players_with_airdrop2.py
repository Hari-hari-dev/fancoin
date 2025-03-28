import asyncio
import json
import traceback
from pathlib import Path
from enum import IntEnum  # Ensure IntEnum is imported

import re

from solders.rpc.responses import SendTransactionResp
from anchorpy import Program, Provider, Wallet, Idl, Context
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from spl.token.async_client import AsyncToken
from spl.token.constants import TOKEN_PROGRAM_ID as SPL_TOKEN_PROGRAM_ID
#from spl.token.instructions import CloseAccount
from spl.token.async_client import AsyncToken
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from solana.transaction import Transaction, Signature
from solana.rpc.types import TxOpts
from solders.system_program import transfer, TransferParams

# The known program IDs
TOKEN_PROGRAM_ID = SPL_TOKEN_PROGRAM_ID
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
RENT_SYSVAR_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

# Define the amount of lamports to send to each player
LAMPORTS_TO_SEND = 10_000_000  # 0.01 SOL

###############################################################################
# Helper Functions
###############################################################################

def derive_ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """
    Manually derive the associated token account address for (owner, mint).
    Equivalent to `spl_associated_token_account::get_associated_token_address`.
    """
    (ata_pubkey, _) = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
        ASSOCIATED_TOKEN_PROGRAM_ID,
    )
    return ata_pubkey

def load_keypair(path: str) -> Keypair:
    """
    Load a Keypair from a JSON file.
    The JSON file should contain:
    - "player_authority_private_key": 64 hex characters representing 32 bytes (seed-based) or 128 hex characters representing 64 bytes (full secret key).
    """
    with Path(path).open() as f:
        secret = json.load(f)
    
    authority_hex = secret.get("player_authority_private_key")
    if not authority_hex:
        raise ValueError("Missing 'player_authority_private_key' in JSON")
    
    try:
        authority_bytes = bytes.fromhex(authority_hex)
    except ValueError:
        raise ValueError("'player_authority_private_key' is not valid hex")
    
    if len(authority_bytes) == 32:
        # Seed-based Keypair
        return Keypair.from_seed(authority_bytes)
    elif len(authority_bytes) == 64:
        # Full secret key
        return Keypair.from_bytes(authority_bytes)
    else:
        raise ValueError(f"Invalid 'player_authority_private_key' length: {len(authority_bytes)} bytes")

async def send_lamports(
    client: AsyncClient,
    payer: Wallet,
    recipient_pubkey: Pubkey,
    lamports: int
) -> str:
    """
    Send lamports from the payer to the recipient.
    Returns the transaction signature as a string.
    """
    try:
        # Create the transfer instruction
        ix = transfer(
            TransferParams(
                from_pubkey=payer.public_key,
                to_pubkey=recipient_pubkey,
                lamports=lamports
            )
        )
        
        # Create a new transaction and add the instruction
        tx = Transaction()
        tx.add(ix)
        
        # Fetch a recent blockhash
        latest_blockhash_resp = await client.get_latest_blockhash()
        if latest_blockhash_resp.value is None:
            raise Exception("Failed to get a recent blockhash")
        
        blockhash = latest_blockhash_resp.value.blockhash
        
        # Set the recent blockhash and fee payer
        tx.recent_blockhash = blockhash
        tx.fee_payer = payer.public_key
        
        # Sign the transaction with the payer's wallet
        signed_tx = payer.sign_transaction(tx)
        
        # Send the transaction with confirmation
        resp = await client.send_raw_transaction(
            signed_tx.serialize(),
            opts=TxOpts(preflight_commitment=Confirmed)
        )
        
        print(f"Sent {lamports} lamports to {recipient_pubkey}. Transaction Signature: {resp}")
        print(f"Type of resp: {type(resp)}")
        print(f"Contents of resp: {resp}")
        
        # Extract signature correctly
        if isinstance(resp, SendTransactionResp):
            # Convert the Signature object to a base58 string
            signature_str = str(resp.value)
            signature_obj = Signature.from_string(signature_str)
        elif isinstance(resp, str):
            signature_obj = Signature.from_string(resp)
        else:
            raise Exception("Unexpected response type from send_raw_transaction")
        
        # Confirm the transaction
        confirm_resp = await client.confirm_transaction(signature_obj, Confirmed)
        if not confirm_resp.value:
            raise Exception(f"Transaction {signature_obj} not confirmed.")
        
        # Fetch the transaction details to check for errors
        tx_details = await client.get_transaction(signature_obj, encoding='json')
        if tx_details.value and tx_details.value.transaction.meta:
            logs = tx_details.value.transaction.meta.log_messages or []
            print("[DEBUG] Transaction Logs:")
            for line in logs:
                print("   ", line)
        else:
            print("[DEBUG] No logs found or missing transaction meta.")
        
        print(f"Confirmed airdrop transaction {signature_obj} for {recipient_pubkey}")
        return signature_str

    except RPCException as e:
        print(f"[ERROR] Error transferring lamports to {recipient_pubkey}: {e}")
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"[ERROR] Unexpected error transferring lamports to {recipient_pubkey}: {e}")
        traceback.print_exc()
        raise

async def send_lamports_with_retry(
    client: AsyncClient,
    payer: Wallet,
    recipient_pubkey: Pubkey,
    lamports: int,
    retries: int = 3,
    delay: int = 3
) -> str:
    """
    Send lamports with retry mechanism.
    """
    for attempt in range(1, retries + 1):
        try:
            return await send_lamports(client, payer, recipient_pubkey, lamports)
        except Exception as e:
            print(f"[WARNING] Attempt {attempt} failed: {e}")
            if attempt < retries:
                print(f"[INFO] Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                print(f"[ERROR] All {retries} attempts failed for {recipient_pubkey}")
                return ""

###############################################################################
# Utility Enums, etc.
###############################################################################
class DappStatus(IntEnum):
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
    reward_pubkey: Pubkey
):
    """
    Registers a player by initializing their PlayerPda and associated token account.
    """
    try:
        # 1) Fetch typed DApp account object
        dapp_data = await program.account["DApp"].fetch(dapp_pda)
        current_count = dapp_data.global_player_count
        print(f"[DEBUG] current_count from on-chain DApp = {current_count}")

        # 2) Derive the new player_pda
        dapp_global_count_bytes = current_count.to_bytes(4, "little")
        (player_pda_pubkey, _) = Pubkey.find_program_address(
            [b"player_pda", dapp_global_count_bytes],
            program.program_id
        )
        print(f"[DEBUG] Derived player_pda => {player_pda_pubkey}")

        # 3) Derive the player's ATA manually
        player_pubkey = player_keypair.pubkey()
        user_ata_pubkey = derive_ata(player_pubkey, fancy_mint)
        print(f"[DEBUG] user_ata => {user_ata_pubkey} for player {player_name}")

        # 4) Call register_player_pda, passing in all required accounts:
        tx_sig = await program.rpc["register_player_pda"](
            player_name,
            ctx=Context(
                accounts={
                    "dapp": dapp_pda,
                    "fancy_mint": fancy_mint,
                    "player_pda": player_pda_pubkey,
                    "user": player_pubkey,  # Player's Pubkey as 'user'
                    "user_ata": user_ata_pubkey,
                    "token_program": TOKEN_PROGRAM_ID,
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                    "rent": RENT_SYSVAR_ID,
                },
                # The player's Keypair must sign to authorize the transaction
                signers=[player_keypair],
            )
        )
        print(f"Player '{player_name}' => PlayerPda registered. Tx Sig: {tx_sig}")

        # Optionally fetch transaction logs
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

    except RPCException as e:
        print(f"[ERROR] Registering player '{player_name}' => RPCException: {e}")
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"[ERROR] Registering player '{player_name}': {e}")
        traceback.print_exc()
        raise

###############################################################################
# Verification and Correction Functions
###############################################################################

async def verify_ata_owner(
    client: AsyncClient,
    ata_pubkey: Pubkey,
    expected_owner: Pubkey
) -> bool:
    """
    Verify if the ATA is owned by the expected owner.
    """
    try:
        ata_info = await client.get_account_info(ata_pubkey, commitment=Confirmed)
        if ata_info.value is None:
            print(f"[ERROR] ATA {ata_pubkey} does not exist.")
            return False
        actual_owner = Pubkey(ata_info.value.owner)
        if actual_owner == expected_owner:
            print(f"[INFO] ATA {ata_pubkey} is correctly owned by {expected_owner}.")
            return True
        else:
            print(f"[WARNING] ATA {ata_pubkey} is owned by {actual_owner}, expected {expected_owner}.")
            return False
    except RPCException as e:
        print(f"[ERROR] RPCException while verifying ATA ownership for {ata_pubkey}: {e}")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"[ERROR] Unexpected error while verifying ATA ownership for {ata_pubkey}: {e}")
        traceback.print_exc()
        return False

# async def close_incorrect_ata(
#     client: AsyncClient,
#     owner_keypair: Keypair,
#     ata_pubkey: Pubkey,
#     destination_pubkey: Pubkey
# ) -> bool:
#     """
#     Close the ATA and transfer any remaining tokens to the destination_pubkey.
#     """
#     try:
#         # Create CloseAccount instruction
#         close_ix = CloseAccount(
#             account=ata_pubkey,
#             destination=destination_pubkey,
#             owner=owner_keypair.public_key
#         )
        
#         # Build transaction
#         tx = Transaction().add(close_ix)
        
#         # Fetch recent blockhash
#         recent_blockhash_resp = await client.get_latest_blockhash()
#         if recent_blockhash_resp.value is None:
#             print("[ERROR] Failed to fetch recent blockhash for closing ATA.")
#             return False
#         tx.recent_blockhash = recent_blockhash_resp.value.blockhash
#         tx.fee_payer = owner_keypair.public_key
        
#         # Sign transaction with owner's keypair
#         signed_tx = owner_keypair.sign_transaction(tx)
        
#         # Send transaction
#         tx_signature = await client.send_raw_transaction(
#             signed_tx.serialize(),
#             opts=TxOpts(preflight_commitment=Confirmed)
#         )
#         print(f"[INFO] Sent transaction to close ATA {ata_pubkey}. Tx Sig: {tx_signature}")
        
#         # Confirm transaction
#         confirm_resp = await client.confirm_transaction(tx_signature, commitment=Confirmed)
#         if confirm_resp.value:
#             print(f"[SUCCESS] ATA {ata_pubkey} closed successfully.")
#             return True
#         else:
#             print(f"[ERROR] ATA {ata_pubkey} closure not confirmed.")
#             return False
#     except RPCException as e:
#         print(f"[ERROR] RPCException while closing ATA {ata_pubkey}: {e}")
#         traceback.print_exc()
#         return False
#     except Exception as e:
#         print(f"[ERROR] Unexpected error while closing ATA {ata_pubkey}: {e}")
#         traceback.print_exc()
#         return False

async def re_register_player(
    program: Program,
    dapp_pda: Pubkey,
    fancy_mint: Pubkey,
    player_name: str,
    player_keypair: Keypair,
    reward_pubkey: Pubkey
):
    """
    Re-register the player to initialize the ATA correctly.
    """
    try:
        await register_player_pda(
            program=program,
            dapp_pda=dapp_pda,
            fancy_mint=fancy_mint,
            player_name=player_name,
            player_keypair=player_keypair,
            reward_pubkey=reward_pubkey,
        )
        print(f"[INFO] Re-registered player '{player_name}' successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to re-register player '{player_name}': {e}")
        traceback.print_exc()

###############################################################################
# Main
###############################################################################
async def main():
    client = AsyncClient("http://localhost:8899", commitment=Confirmed)
    # 1) Setup Solana + Anchor env
    wallet = Wallet.local()
    provider = Provider(client, wallet)

    # 2) Check payer wallet balance
    payer_balance_resp = await client.get_balance(provider.wallet.public_key)
    if payer_balance_resp.value is not None:
        print(f"Payer wallet balance: {payer_balance_resp.value} lamports")
        if payer_balance_resp.value < LAMPORTS_TO_SEND * 10:  # Example threshold
            print(f"[WARNING] Payer wallet has low balance: {payer_balance_resp.value} lamports")
    else:
        print("[ERROR] Failed to fetch payer wallet balance.")
        return

    # 3) Load IDL
    idl_path = Path("../target/idl/fancoin.json")
    if not idl_path.exists():
        print(f"[ERROR] IDL file not found at {idl_path.resolve()}")
        return
    with idl_path.open() as f:
        idl = Idl.from_json(f.read())

    # 4) Create Program object
    program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
    program = Program(idl, program_id, provider)
    print("Program loaded successfully.")

    # 5) Derive the DApp PDA
    (dapp_pda, _) = Pubkey.find_program_address([b"dapp"], program_id)
    print(f"[DEBUG] dapp_pda => {dapp_pda}")

    # 6) The Mint that the DApp uses
    fancy_mint = Pubkey.from_string("DVkPNrxdgGxF5fqvnKgXj7DWcRSdimLChXKwAKYk7fiJ")  # Update if different

    # 7) Grab all .json keys in "player_keys"
    keys_folder = Path("player_keys")
    if not keys_folder.exists() or not keys_folder.is_dir():
        print(f"[ERROR] Folder {keys_folder} does not exist or is not a directory.")
        return

    json_files = list(keys_folder.glob("*.json"))
    if not json_files:
        print(f"No .json files found in {keys_folder}/. Exiting.")
        return

    for json_file in json_files:
        player_name = json_file.stem
        try:
            with json_file.open() as f:
                data = json.load(f)

            # 7a) Load the player's keypair (only player_authority_private_key)
            authority_hex = data.get("player_authority_private_key")
            if not authority_hex:
                print(f"[ERROR] 'player_authority_private_key' not found in {json_file}")
                continue
            try:
                authority_bytes = bytes.fromhex(authority_hex)
            except ValueError:
                print(f"[ERROR] 'player_authority_private_key' is not valid hex in {json_file}")
                continue

            # Ensure the secret key is exactly 32 or 64 bytes
            if len(authority_bytes) == 32:
                # Seed-based Keypair
                player_keypair = Keypair.from_seed(authority_bytes)
            elif len(authority_bytes) == 64:
                # Full secret key
                player_keypair = Keypair.from_bytes(authority_bytes)
            else:
                print(f"[ERROR] Invalid 'player_authority_private_key' length in {json_file}. Expected 32 or 64 bytes, got {len(authority_bytes)} bytes.")
                continue

            player_pubkey = player_keypair.pubkey()
            print(f"\n[INFO] Registering player => {player_name} with pubkey {player_pubkey}")

            # 7b) Determine the reward_pubkey
            reward_pubkey_str = data.get("player_info_acc_address")
            if reward_pubkey_str:
                try:
                    reward_pubkey = Pubkey.from_string(reward_pubkey_str)
                except ValueError:
                    print(f"[ERROR] Invalid 'player_info_acc_address' in {json_file}. Using derived ATA as fallback.")
                    reward_pubkey = derive_ata(player_pubkey, fancy_mint)
            else:
                reward_pubkey = derive_ata(player_pubkey, fancy_mint)  # Fallback to derived ATA

            # 7c) Check if the player already has sufficient lamports
            balance_resp = await client.get_balance(player_pubkey)
            if balance_resp.value is not None and balance_resp.value >= LAMPORTS_TO_SEND:
                print(f"[INFO] Player {player_pubkey} already has sufficient lamports ({balance_resp.value} lamports). Skipping airdrop.")
            else:
                # 7c) Airdrop lamports to the player's main account
                print(f"[INFO] Airdropping {LAMPORTS_TO_SEND} lamports to {player_pubkey}")
                try:
                    tx_sig = await send_lamports_with_retry(
                        client=client,
                        payer=provider.wallet,
                        recipient_pubkey=player_pubkey,
                        lamports=LAMPORTS_TO_SEND
                    )
                    if tx_sig:
                        print(f"[SUCCESS] Airdropped {LAMPORTS_TO_SEND} lamports to {player_pubkey}. Tx Sig: {tx_sig}")
                    else:
                        print(f"[ERROR] Airdrop failed for {player_pubkey}.")
                except Exception as e:
                    print(f"[ERROR] Failed to airdrop lamports to {player_pubkey}: {e}")
                    continue

            # 7d) Verify player's balance after airdrop
            balance_resp = await client.get_balance(player_pubkey)
            if balance_resp.value is not None:
                print(f"[DEBUG] Player {player_pubkey} balance: {balance_resp.value} lamports")
                if balance_resp.value < 4_085_520:
                    print(f"[ERROR] Player {player_pubkey} has insufficient lamports after airdrop: {balance_resp.value} < 4,085,520")
                    continue
            else:
                print(f"[ERROR] Failed to fetch balance for {player_pubkey}. Skipping player registration.")
                continue

            # 7e) Register the player on-chain
            await register_player_pda(
                program=program,
                dapp_pda=dapp_pda,
                fancy_mint=fancy_mint,
                player_name=player_name,
                player_keypair=player_keypair,   # Player's Keypair as 'user'
                reward_pubkey=reward_pubkey,
            )

            # 7f) Verify ATA Ownership
            is_correct_owner = await verify_ata_owner(
                client=client,
                ata_pubkey=reward_pubkey,
                expected_owner=player_pubkey
            )

            # if not is_correct_owner:
            #     print(f"[INFO] Attempting to correct ATA ownership for player '{player_name}'.")

            #     # Close the incorrect ATA
            #     success = await close_incorrect_ata(
            #         client=client,
            #         owner_keypair=player_keypair,
            #         ata_pubkey=reward_pubkey,
            #         destination_pubkey=player_pubkey
            #     )

            #     if success:
            #         print(f"[INFO] ATA {reward_pubkey} closed successfully for player '{player_name}'. Re-registering to initialize ATA correctly.")
            #         # Re-register the player to initialize ATA correctly
            #         await re_register_player(
            #             program=program,
            #             dapp_pda=dapp_pda,
            #             fancy_mint=fancy_mint,
            #             player_name=player_name,
            #             player_keypair=player_keypair,
            #             reward_pubkey=reward_pubkey,
            #         )
            #         # Optionally, verify again
            #         await asyncio.sleep(1)  # Short delay to ensure transaction processing
            #         is_correct_owner_after = await verify_ata_owner(
            #             client=client,
            #             ata_pubkey=reward_pubkey,
            #             expected_owner=player_pubkey
            #         )
            #         if not is_correct_owner_after:
            #             print(f"[ERROR] Failed to correct ATA ownership for player '{player_name}'.")
            #     else:
            #         print(f"[ERROR] Failed to close incorrect ATA for player '{player_name}'. Manual intervention required.")

            # Optional: Add a short delay to ensure the transaction is processed
            await asyncio.sleep(0.5)

        except FileNotFoundError:
            print(f"[ERROR] Keypair file {json_file} not found. Skipping...")
        except json.JSONDecodeError:
            print(f"[ERROR] Invalid JSON format in {json_file}. Skipping...")
        except Exception as e:
            print(f"[ERROR] Unexpected error for {json_file}: {e}")
            traceback.print_exc()

    print("\nAll players from 'player_keys/' folder have been registered and funded.")

if __name__ == "__main__":
    asyncio.run(main())

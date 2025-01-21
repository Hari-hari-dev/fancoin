import asyncio
import json
import re
import traceback
import os
from pathlib import Path
from enum import IntEnum

from anchorpy import Program, Provider, Wallet, Idl, Context
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException

###############################################################################
# Utility class or placeholders
###############################################################################
class GameStatus(IntEnum):
    Probationary = 0
    Whitelisted = 1
    Blacklisted = 2

###############################################################################
# The actual register function
###############################################################################
async def register_player_pda(
    program: Program,
    dapp_pda: Pubkey,
    user_pubkey: Pubkey,
    player_name: str,
    authority_pubkey: Pubkey,
    reward_pubkey: Pubkey
):
    """
    1) Fetch DApp => dapp_data.global_player_count
    2) Derive [b"player_pda", global_player_count]
    3) Call the on-chain register_player_pda
    """
    try:
        # 1) Fetch typed DApp account object
        dapp_data = await program.account["DApp"].fetch(dapp_pda)

        # 2) Access the global_player_count
        current_count = dapp_data.global_player_count
        print(f"[DEBUG] current_count from on-chain DApp = {current_count}")

        # Convert to bytes
        dapp_global_count_bytes = current_count.to_bytes(4, "little")

        # 3) Derive the new player_pda
        (player_pda_pubkey, _player_pda_bump) = Pubkey.find_program_address(
            [b"player_pda", dapp_global_count_bytes],
            program.program_id
        )
        print(f"[DEBUG] Derived player_pda: {player_pda_pubkey}")

        # 4) Call register_player_pda
        tx_sig = await program.rpc["register_player_pda"](
            player_name,
            #authority_pubkey,
            #reward_pubkey,
            ctx=Context(
                accounts={
                    "dapp": dapp_pda,
                    "player_pda": player_pda_pubkey,
                    "user": user_pubkey,             # The "admin" or whomever is paying
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[program.provider.wallet.payer],
            )
        )
        print(f"Player '{player_name}' => PlayerPda registered. Tx Sig: {tx_sig}")

        # Optionally fetch the transaction logs
        confirmed_tx = await program.provider.connection.get_transaction(
            tx_sig, encoding='json'
        )
        if confirmed_tx.value and confirmed_tx.value.transaction.meta:
            logs = confirmed_tx.value.transaction.meta.log_messages
            if logs:
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
        print(f"[ERROR] registering player '{player_name}' => RPCException: {e}")
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"[ERROR] registering player '{player_name}': {e}")
        traceback.print_exc()
        raise


###############################################################################
# Main
###############################################################################
async def main():
    try:
        # 1) Setup Solana + Anchor env
        client = AsyncClient("http://localhost:8899", commitment=Confirmed)
        wallet = Wallet.local()
        provider = Provider(client, wallet)

        # 2) Load IDL
        idl_path = Path("../target/idl/fancoin.json")
        if not idl_path.exists():
            print(f"[ERROR] IDL file not found at {idl_path.resolve()}")
            return

        with idl_path.open() as f:
            idl = Idl.from_json(f.read())

        # 3) Create Program object
        program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
        program = Program(idl, program_id, provider)
        print("Program loaded successfully.")

        # 4) Derive the DApp PDA
        (dapp_pda, _) = Pubkey.find_program_address([b"dapp"], program_id)
        print(f"[DEBUG] dapp_pda => {dapp_pda}")

        # 5) Admin is the local wallet that pays for the transaction
        admin_pubkey = program.provider.wallet.public_key
        print(f"[DEBUG] admin_pubkey => {admin_pubkey}")

        # 6) We assume you have a folder called "player_keys" with multiple JSON files:
        keys_folder = Path("player_keys")
        if not keys_folder.exists() or not keys_folder.is_dir():
            print(f"[ERROR] Folder {keys_folder} does not exist or is not a directory.")
            return

        # 7) Iterate over each <player_name>.json in that folder
        json_files = list(keys_folder.glob("*.json"))
        if not json_files:
            print(f"No .json files found in {keys_folder}/. Exiting.")
            return

        for json_file in json_files:
            # The player name is the file stem (i.e. <player_name>.json => <player_name>)
            player_name = json_file.stem

            # 7a) Load the data
            with json_file.open() as f:
                data = json.load(f)

            # 7b) Extract the authority private key + parse
            authority_hex = data["player_authority_private_key"]
            authority_bytes = bytes.fromhex(authority_hex)
            # anchor's Keypair can accept 32 bytes as the seed for the private half
            authority_kp = Keypair.from_seed(authority_bytes[:32])
            authority_pubkey = authority_kp.pubkey()

            # 7c) For the reward_address, you can use a separate field, or reuse authority
            #     If you have "player_info_acc_address" or "player_ata_address" in JSON, do:
            # reward_str = data["some_field"]
            # reward_pubkey = Pubkey.from_string(reward_str)

            # For demonstration, let's reuse "authority" as reward, or default:
            if "player_info_acc_address" in data:
                reward_pubkey = Pubkey.from_string(data["player_info_acc_address"])
            else:
                reward_pubkey = authority_pubkey

            # 7d) Call register_player_pda
            print(f"\n[INFO] Registering player => {player_name}")
            await register_player_pda(
                program=program,
                dapp_pda=dapp_pda,
                user_pubkey=admin_pubkey,
                player_name=player_name,
                authority_pubkey=authority_pubkey,
                reward_pubkey=reward_pubkey
            )

        print("\nAll players from 'player_keys/' folder have been registered.")

    except Exception as e:
        print(f"[ERROR] Unexpected error => {e}")
        traceback.print_exc()
    finally:
        await client.close()
        print("[INFO] Closed Solana RPC client.")


if __name__ == "__main__":
    asyncio.run(main())

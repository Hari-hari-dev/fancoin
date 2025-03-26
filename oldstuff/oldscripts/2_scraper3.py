import asyncio
import json
import re
import traceback
import os
from pathlib import Path
from enum import IntEnum

from anchorpy import Program, Provider, Wallet, Idl, Context, get_associated_token_address
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException

# The known program IDs
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
RENT_SYSVAR_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

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
    user_pubkey: Pubkey,
    fancy_mint: Pubkey,
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
        current_count = dapp_data.global_player_count
        print(f"[DEBUG] current_count from on-chain DApp = {current_count}")

        # 2) Derive the new player_pda
        dapp_global_count_bytes = current_count.to_bytes(4, "little")
        (player_pda_pubkey, _) = Pubkey.find_program_address(
            [b"player_pda", dapp_global_count_bytes],
            program.program_id
        )
        print(f"[DEBUG] Derived player_pda => {player_pda_pubkey}")

        # 3) Derive the user_ata (the associated token address) 
        #    for (user_pubkey, fancy_mint).
        user_ata_pubkey = await get_associated_token_address(
            user_pubkey, fancy_mint
        )
        print(f"[DEBUG] user_ata => {user_ata_pubkey}")

        # 4) Call register_player_pda, passing in all required accounts:
        tx_sig = await program.rpc["register_player_pda"](
            player_name,
            ctx=Context(
                accounts={
                    "dapp": dapp_pda,
                    "fancy_mint": fancy_mint,
                    "player_pda": player_pda_pubkey,
                    "user": user_pubkey,  # the signer paying for creation
                    "user_ata": user_ata_pubkey,
                    "token_program": TOKEN_PROGRAM_ID,
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                    "rent": RENT_SYSVAR_ID,
                },
                signers=[program.provider.wallet.payer],
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
                # parse logs if you need
                pass

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

        # 5) The Mint that the DApp uses (from your logs, you have):
        fancy_mint = Pubkey.from_string("DVkPNrxdgGxF5fqvnKgXj7DWcRSdimLChXKwAKYk7fiJ")

        # 6) Admin is the local wallet paying for the transaction
        admin_pubkey = program.provider.wallet.public_key
        print(f"[DEBUG] admin_pubkey => {admin_pubkey}")

        # 7) Grab all the .json keys in "player_keys"
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
            with json_file.open() as f:
                data = json.load(f)

            # You have your player's private key, etc.
            authority_hex = data["player_authority_private_key"]
            authority_bytes = bytes.fromhex(authority_hex)
            authority_kp = Keypair.from_seed(authority_bytes[:32])
            authority_pubkey = authority_kp.pubkey()

            if "player_info_acc_address" in data:
                reward_pubkey = Pubkey.from_string(data["player_info_acc_address"])
            else:
                reward_pubkey = authority_pubkey  # fallback

            print(f"\n[INFO] Registering player => {player_name}")
            await register_player_pda(
                program=program,
                dapp_pda=dapp_pda,
                user_pubkey=admin_pubkey,  # or the player's Keypair if you prefer
                fancy_mint=fancy_mint,
                player_name=player_name,
                authority_pubkey=authority_pubkey,
                reward_pubkey=reward_pubkey,
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

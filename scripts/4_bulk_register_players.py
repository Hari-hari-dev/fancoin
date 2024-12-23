import asyncio
import json
import re
import traceback
from pathlib import Path
from enum import IntEnum

from anchorpy import Program, Provider, Wallet, Idl, Context
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException


class GameStatus(IntEnum):
    Probationary = 0
    Whitelisted = 1
    Blacklisted = 2

async def register_player_pda(
    program: Program,
    dapp_pda: Pubkey,
    user_pubkey: Pubkey,
    player_name: str,
    authority_pubkey: Pubkey,
    reward_pubkey: Pubkey,
):
    """
    1) Fetch DApp
    2) Read .global_player_count (dot notation)
    3) Derive [b"player_pda", global_player_count] seeds
    4) Call the on-chain register_player_pda
    """
    try:
        # 1) Fetch typed DApp account object
        dapp_data = await program.account["DApp"].fetch(dapp_pda)

        # 2) Access the field via dot notation
        current_count = dapp_data.global_player_count
        print(f"[DEBUG] current_count from on-chain DApp = {current_count}")

        # Convert to bytes
        dapp_global_count_bytes = current_count.to_bytes(4, "little")

        # Derive the new player_pda
        (player_pda_pubkey, _player_pda_bump) = Pubkey.find_program_address(
            [b"player_pda", dapp_global_count_bytes],
            program.program_id
        )

        # 4) Call our instruction
        tx_sig = await program.rpc["register_player_pda"](
            player_name,
            authority_pubkey,
            reward_pubkey,
            ctx=Context(
                accounts={
                    "dapp": dapp_pda,
                    "player_pda": player_pda_pubkey,
                    "user": user_pubkey,
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[program.provider.wallet.payer],
            )
        )
        print(f"Player PDA '{player_name}' registered. Tx Sig: {tx_sig}")
        confirmed_tx = await program.provider.connection.get_transaction(tx_sig, encoding='json')
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
                    print(f"[DEBUG] Compute units for '{player_name}': {consumed_cu}/{max_cu}")
                else:
                    print(f"[DEBUG] No compute units info found in logs for '{player_name}'.")
            else:
                print(f"[DEBUG] No log messages returned for transaction of '{player_name}'.")
        else:
            print(f"[DEBUG] No transaction meta/logs found for '{player_name}'.")
    except RPCException as e:
        print(f"Error registering player '{player_name}': {e}")
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"Error: {e}")
        raise
    except RPCException as e:
        print(f"Error registering player '{player_name}': {e}")
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"Error: {e}")
        raise


async def main():
    try:
        # 1) Setup
        client = AsyncClient("http://localhost:8899", commitment=Confirmed)
        wallet = Wallet.local()
        provider = Provider(client, wallet)

        idl_path = Path("../target/idl/fancoin.json")
        with idl_path.open() as f:
            idl = Idl.from_json(f.read())

        program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
        program = Program(idl, program_id, provider)
        print("Program loaded successfully.")

        # Derive the DApp PDA
        (dapp_pda, _) = Pubkey.find_program_address([b"dapp"], program_id)
        print(f"[DEBUG] dapp_pda = {dapp_pda}")

        # 2) Load your JSON
        with open("player_wallets.json") as f:
            player_data = json.load(f)

        admin_pubkey = program.provider.wallet.public_key

        # 3) For each player in JSON
        for player_name, info in player_data.items():
            authority_hex = info["player_authority_private_key"]
            stable_bytes  = bytes.fromhex(authority_hex)
            stable_kp     = Keypair.from_seed(stable_bytes)
            stable_pubkey = stable_kp.pubkey()

            reward_str = info.get("reward_address")
            if reward_str:
                reward_pubkey = Pubkey.from_string(reward_str)
            else:
                reward_pubkey = stable_pubkey

            await register_player_pda(
                program=program,
                dapp_pda=dapp_pda,
                user_pubkey=admin_pubkey,
                player_name=player_name,
                authority_pubkey=stable_pubkey,
                reward_pubkey=reward_pubkey
            )

        print("\nAll players registered successfully.")

    except Exception as e:
        print(f"An unexpected error occurred:\n{e}")
        traceback.print_exc()
    finally:
        await client.close()
        print("Closed Solana RPC client.")


if __name__ == "__main__":
    asyncio.run(main())

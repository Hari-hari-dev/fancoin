import asyncio
from pathlib import Path
from enum import IntEnum
import traceback
import json

from anchorpy import Program, Provider, Wallet, Idl, Context
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException

# Game status enum if needed
class GameStatus(IntEnum):
    Probationary = 0
    Whitelisted = 1
    Blacklisted = 2

async def register_player_debug(program: Program, game_pda: Pubkey, user_pubkey: Pubkey, game_number: int, player_name: str, reward_address: Pubkey):
    # Create a new keypair for the player account
    player_keypair = Keypair()  
    try:
        tx = await program.rpc["register_player_debug"](
            game_number,
            player_name,
            reward_address,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "player": player_keypair.pubkey(),
                    "user": user_pubkey,
                    "system_program": SYS_PROGRAM_ID,
                },
                pre_instructions=[],
                post_instructions=[],
                signers=[program.provider.wallet.payer, player_keypair], # payer and player_keypair sign
            )
        )
        print(f"Registered player '{player_name}' successfully. Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error registering player '{player_name}': {e}")
        traceback.print_exc()
        raise

async def main():
    try:
        print("Setting up provider and loading program...")
        client = AsyncClient("http://localhost:8899", commitment=Confirmed)
        wallet = Wallet.local()
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

        # Assume game is already initialized and we have game_pda
        # For demo, find the same game_pda used before:
        game_number = 1
        (game_pda, _) = Pubkey.find_program_address(
            [b"game", game_number.to_bytes(4, "little")],
            program_id
        )

        # Load player_wallets.json
        player_wallets_path = Path("player_wallets.json")
        if not player_wallets_path.exists():
            print("player_wallets.json not found.")
            return

        with player_wallets_path.open() as f:
            player_data = json.load(f)

        # The signer is the admin (the current provider's wallet)
        admin_pubkey = program.provider.wallet.public_key

        # Iterate over each player and register them
        for player_name, info in player_data.items():
            reward_addr_str = info["address"]
            reward_pubkey = Pubkey.from_string(reward_addr_str)
            # Use the player_name from the key as their name in the contract
            await register_player_debug(
                program,
                game_pda,
                admin_pubkey,
                game_number,
                player_name,
                reward_pubkey
            )

        print("\nAll players registered successfully.")

    except Exception as e:
        print(f"An unexpected error occurred.\n{e}")
        traceback.print_exc()
    finally:
        await client.close()
        print("Closed Solana RPC client.")

if __name__ == "__main__":
    asyncio.run(main())

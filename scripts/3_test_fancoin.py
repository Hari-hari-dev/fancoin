import asyncio
from pathlib import Path
from enum import IntEnum
import traceback  # Import traceback for detailed error information
import json

from anchorpy import Program, Provider, Wallet, Idl, Context
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException

# Define GameStatus Enum matching your Rust enum
class GameStatus(IntEnum):
    Probationary = 0
    Whitelisted = 1
    Blacklisted = 2

async def initialize_dapp(program: Program, client: AsyncClient) -> Pubkey:
    print("Initializing DApp account...")
    dapp_pda, dapp_bump = Pubkey.find_program_address([b"dapp"], program.program_id)
    print(f"DApp PDA: {dapp_pda}, Bump: {dapp_bump}")

    # Check if DApp account already exists
    dapp_account = await client.get_account_info(dapp_pda, commitment=Confirmed)
    if dapp_account.value is None:
        try:
            tx = await program.rpc["initialize_dapp"](
                ctx=Context(
                    accounts={
                        "dapp": dapp_pda,
                        "user": program.provider.wallet.public_key,
                        "system_program": SYS_PROGRAM_ID,
                    },
                    pre_instructions=[],
                    post_instructions=[],
                    signers=[program.provider.wallet.payer],
                )
            )
            print(f"DApp initialized successfully. Transaction Signature: {tx}")
        except RPCException as e:
            print(f"Error initializing DApp: {e}")
            traceback.print_exc()
            raise
    else:
        print("DApp account already exists. Skipping initialization.")

    return dapp_pda

async def initialize_game(program: Program, client: AsyncClient, game_number: int, description: str, dapp_pda: Pubkey) -> Pubkey:
    print("\nInitializing Game account...")
    game_pda, game_bump = Pubkey.find_program_address(
        [b"game", game_number.to_bytes(4, "little")], program.program_id
    )
    print(f"Game PDA: {game_pda}, Bump: {game_bump}")

    game_account = await client.get_account_info(game_pda, commitment=Confirmed)
    if game_account.value is None:
        try:
            tx = await program.rpc["initialize_game"](
                game_number,
                description,
                ctx=Context(
                    accounts={
                        "game": game_pda,
                        "dapp": dapp_pda,
                        "user": program.provider.wallet.public_key,
                        "system_program": SYS_PROGRAM_ID,
                    },
                    pre_instructions=[],
                    post_instructions=[],
                    signers=[program.provider.wallet.payer],
                )
            )
            print(f"Game initialized successfully. Transaction Signature: {tx}")
        except RPCException as e:
            print(f"Error initializing Game: {e}")
            traceback.print_exc()
            raise
    else:
        print("Game account already exists. Skipping initialization.")

    return game_pda

async def punch_in(program: Program, game_pda: Pubkey, game_number: int, player_keypair: Keypair):
    print("\nPunching In as Validator...")
    try:
        tx = await program.rpc["punch_in"](
            game_number,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "validator": player_keypair.pubkey(),
                    "system_program": SYS_PROGRAM_ID,
                },
                pre_instructions=[],
                post_instructions=[],
                signers=[player_keypair],
            )
        )
        print(f"Punched in successfully. Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error punching in: {e}")
        traceback.print_exc()
        raise

async def register_player(program: Program, game_pda: Pubkey, player_keypair: Keypair, game_number: int, player_name: str, reward_address: Pubkey):
    print("\nRegistering a Player...")

    # 1. Fetch the Game account first
    game_account = await program.account["Game"].fetch(game_pda)
    current_player_count = game_account.player_count

    # Convert game_number and current_player_count to bytes
    game_number_bytes = game_number.to_bytes(4, "little")
    player_count_bytes = current_player_count.to_bytes(4, "little")

    # 2. Derive the player_info_acc PDA
    player_info_pda, player_info_bump = Pubkey.find_program_address(
        [b"player_info", game_number_bytes, player_count_bytes],
        program.program_id
    )

    try:
        tx = await program.rpc["register_player"](
            game_number,
            player_name,
            reward_address,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "player": player_keypair.pubkey(),
                    "player_info_acc": player_info_pda,
                    "user": program.provider.wallet.public_key,
                    "system_program": SYS_PROGRAM_ID,
                },
                # Only player_keypair and the wallet payer are needed as signers
                signers=[player_keypair, program.provider.wallet.payer],
            )
        )
        print(f"Player registered successfully. Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error registering Player: {e}")
        traceback.print_exc()
        raise

async def submit_minting_list(program: Program, game_pda: Pubkey, game_number: int, player_names: list, player_keypair: Keypair):
    print("\nSubmitting Minting List...")
    try:
        tx = await program.rpc["submit_minting_list"](
            game_number,
            player_names,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "validator": player_keypair.pubkey()
                },
                pre_instructions=[],
                post_instructions=[],
                signers=[player_keypair],
            )
        )
        print(f"Minting list submitted successfully. Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error submitting Minting List: {e}")
        traceback.print_exc()
        raise

async def main():
    try:
        # 1. Set Up Provider and Program
        print("Setting up provider and loading program...")
        client = AsyncClient("http://localhost:8899", commitment=Confirmed)
        wallet = Wallet.local()
        provider = Provider(client, wallet)

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

        # 2. Initialize DApp
        dapp_pda = await initialize_dapp(program, client)

        # 3. Initialize Game
        game_number = 1
        description = "Test Game"
        game_pda = await initialize_game(program, client, game_number, description, dapp_pda)

        def load_keypair(path: str) -> Keypair:
            with Path(path).open() as f:
                secret = json.load(f)
            return Keypair.from_bytes(bytes(secret[0:64]))

        player_keypair = load_keypair("./player-keypair.json")

        # 5. Punch In as Validator
        await punch_in(program, game_pda, game_number, player_keypair)

        # 6. Register a Player
        player_name = "Player1"
        reward_address = player_keypair.pubkey()

        # Create a new keypair for player_info_acc
        player_info_keypair = Keypair()

        # Now call register_player with the newly created player_info_keypair
        await register_player(program, game_pda, player_keypair, game_number, player_name, reward_address)

        # 7. Submit Minting List
        player_names = [player_name]
        await submit_minting_list(program, game_pda, game_number, player_names, player_keypair)

        print("\nAll tests completed successfully.")

    except Exception as e:
        print(f"An unexpected error occurred during testing.\n{e}")
        traceback.print_exc()
    finally:
        await client.close()
        print("Closed Solana RPC client.")

if __name__ == "__main__":
    asyncio.run(main())

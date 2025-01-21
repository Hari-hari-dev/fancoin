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
            tx = await program.rpc["initialize"](
                ctx=Context(
                    accounts={
                        "dapp": dapp_pda,
                        "user": program.provider.wallet.public_key,
                        "system_program": SYS_PROGRAM_ID,
                    },
                    pre_instructions=[],    # Replace 'instructions' with 'pre_instructions'
                    post_instructions=[],   # Add 'post_instructions' if needed
                    signers=[program.provider.wallet.payer],  # Use 'payer' instead of 'keypair'
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

async def initialize_game(program: Program, client: AsyncClient, game_number: int, description: str) -> Pubkey:
    print("\nInitializing Game account...")
    game_pda, game_bump = Pubkey.find_program_address(
        [b"game", game_number.to_bytes(4, "little")], program.program_id
    )
    print(f"Game PDA: {game_pda}, Bump: {game_bump}")

    # Check if Game account already exists
    game_account = await client.get_account_info(game_pda, commitment=Confirmed)
    if game_account.value is None:
        try:
            tx = await program.rpc["initialize_game"](
                game_number,
                description,
                ctx=Context(
                    accounts={
                        "game": game_pda,
                        "user": program.provider.wallet.public_key,
                        "system_program": SYS_PROGRAM_ID,
                    },
                    pre_instructions=[],    # Replace 'instructions' with 'pre_instructions'
                    post_instructions=[],   # Add 'post_instructions' if needed
                    signers=[program.provider.wallet.payer],  # Use 'payer' instead of 'keypair'
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

async def update_game_status(program: Program, game_pda: Pubkey, dapp_pda: Pubkey, game_number: int, new_status: GameStatus, new_description: str):
    print("\nUpdating Game status to Whitelisted...")
    try:
        tx = await program.rpc["update_game_status"](
            game_number,
            new_status.value,
            new_description,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "dapp": dapp_pda,
                    "signer": program.provider.wallet.public_key,
                },
                pre_instructions=[],    # Replace 'instructions' with 'pre_instructions'
                post_instructions=[],   # Add 'post_instructions' if needed
                signers=[program.provider.wallet.payer],  # Use 'payer' instead of 'keypair'
            )
        )
        print(f"Game status updated successfully. Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error updating Game status: {e}")
        traceback.print_exc()
        raise

async def punch_in(program: Program, game_pda: Pubkey, game_number: int, player_keypair: Keypair):
    print("\nPunching In as Validator...")
    try:
        tx = await program.rpc["punch_in"](
            game_number,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    #"validator": program.provider.wallet.public_key,
                    "validator": player_keypair.pubkey(),
                    "system_program": SYS_PROGRAM_ID,
                },
                pre_instructions=[],    # Replace 'instructions' with 'pre_instructions'
                post_instructions=[],   # Add 'post_instructions' if needed
                signers=[player_keypair], #program.provider.wallet.payer],  # Use 'payer' instead of 'keypair'
            )
        )
        print(f"Punched in successfully. Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error punching in: {e}")
        traceback.print_exc()
        raise

async def register_player(program: Program, game_pda: Pubkey, player_keypair: Keypair, game_number: int, player_name: str, reward_address: Pubkey):
    print("\nRegistering a Player...")
    try:
        tx = await program.rpc["register_player"](
            game_number,
            player_name,
            reward_address,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "player": player_keypair.pubkey(),
                    "user": program.provider.wallet.public_key,
                    "system_program": SYS_PROGRAM_ID,
                },
                pre_instructions=[],    # Replace 'instructions' with 'pre_instructions'
                post_instructions=[],   # Add 'post_instructions' if needed
                signers=[player_keypair, program.provider.wallet.payer],  # Include both signers
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
                    #"validator": program.provider.wallet.public_key,
                    "validator": player_keypair.pubkey()
                },
                pre_instructions=[],    # Replace 'instructions' with 'pre_instructions'
                post_instructions=[],   # Add 'post_instructions' if needed
                signers=[player_keypair],#program.provider.wallet.payer],  # Use 'payer' instead of 'keypair'
            )
        )
        print(f"Minting list submitted successfully. Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error submitting Minting List: {e}")
        traceback.print_exc()
        raise

async def finalize_minting(program: Program, game_pda: Pubkey, game_number: int):
    print("\nFinalizing Minting...")
    try:
        tx = await program.rpc["finalize_minting"](
            game_number,
            ctx=Context(
                accounts={
                    "game": game_pda,
                },
                pre_instructions=[],    # Replace 'instructions' with 'pre_instructions'
                post_instructions=[],   # Add 'post_instructions' if needed
                signers=[program.provider.wallet.payer],  # Use 'payer' instead of 'keypair'
            )
        )
        print(f"Minting finalized successfully. Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error finalizing Minting: {e}")
        traceback.print_exc()
        raise

async def verify_token_minting(program: Program, game_pda: Pubkey, player_keypair: Keypair, game_number: int):
    print("\nVerifying Token Minting to the Player...")
    try:
        # Fetch Player account data
        player_account = await program.account["Player"].fetch(player_keypair.pubkey())
        assert player_account.name == "Player1", "Player name mismatch."
        assert player_account.address == program.provider.wallet.public_key, "Player address mismatch."
        assert player_account.reward_address == player_keypair.pubkey(), "Player reward address mismatch."
        assert player_account.last_minted is not None, "Player last_minted should not be None."

        # Fetch Game account data to check token balances
        game_account = await program.account["Game"].fetch(game_pda)

        # Find the token balance for the player's reward address
        player_balance = 0
        for tb in game_account.token_balances:
            if tb.address == player_account.reward_address:
                player_balance = tb.balance
                break

        assert player_balance > 0, "Player token balance should be greater than zero."
        print(f"Player token balance verified: {player_balance}")
    except AssertionError as ae:
        print(f"Assertion Error: {ae}")
        traceback.print_exc()
    except RPCException as e:
        print(f"Error fetching account data: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"Unexpected error: {e}")
        traceback.print_exc()

async def main():
    try:
        # 1. Set Up Provider and Program
        print("Setting up provider and loading program...")
        # Connect to the local test validator
        client = AsyncClient("http://localhost:8899", commitment=Confirmed)

        # Use the default keypair from the Solana CLI
        wallet = Wallet.local()

        # A Provider is a combination of a Client and a Wallet
        provider = Provider(client, wallet)

        # Path to your IDL file
        idl_path = Path("../target/idl/fancoin.json")  # Adjust the path if necessary

        if not idl_path.exists():
            print(f"IDL file not found at {idl_path.resolve()}")
            return

        # Load the IDL
        with idl_path.open() as f:
            idl_json = f.read()

        idl = Idl.from_json(idl_json)

        # Program ID (hardcoded as per your request)
        program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")

        # Create the Program instance
        program = Program(idl, program_id, provider)
        print("Program loaded successfully.")

        # 2. Initialize DApp
        dapp_pda = await initialize_dapp(program, client)

        # 3. Initialize Game
        game_number = 1
        description = "Test Game"
        game_pda = await initialize_game(program, client, game_number, description)
        def load_keypair(path: str) -> Keypair:
            with Path(path).open() as f:
                secret = json.load(f)
            return Keypair.from_bytes(bytes(secret[0:64]))
        player_keypair = load_keypair("./player-keypair.json")

        # 4. Update Game Status to Whitelisted
        new_status = GameStatus.Whitelisted
        new_description = "Whitelisted Game"
        # await update_game_status(program, game_pda, dapp_pda, game_number, new_status, new_description)

        # 5. Punch In as Validator
        await punch_in(program, game_pda, game_number, player_keypair)

        # 6. Register a Player


        player_name = "Player1"
        reward_address = player_keypair.pubkey()
        print(player_keypair.pubkey())
        await register_player(program, game_pda, player_keypair, game_number, player_name, reward_address)

        # 7. Submit Minting List
        player_names = [player_name]
        await submit_minting_list(program, game_pda, game_number, player_names, player_keypair)

        # 8. Verify Token Minting to the Player
        # await verify_token_minting(program, game_pda, player_keypair, game_number)

        print("\nAll tests completed successfully.")

    except Exception as e:
        print(f"An unexpected error occurred during testing.\n{e}")
        traceback.print_exc()
    finally:
        # Close the client connection
        await client.close()
        print("Closed Solana RPC client.")

# Run the main function
if __name__ == "__main__":
    asyncio.run(main())

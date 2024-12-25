import asyncio
from pathlib import Path
from enum import IntEnum
import traceback
import json

# For specifying extra read-only/writable accounts
from anchorpy.program.namespace.instruction import AccountMeta
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


async def initialize_dapp(program: Program, client: AsyncClient) -> Pubkey:
    """Initialize the DApp, returning the DApp PDA."""
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


async def initialize_game(
    program: Program, client: AsyncClient, game_number: int, description: str, dapp_pda: Pubkey
) -> Pubkey:
    """Initialize the Game, returning the Game PDA."""
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


async def register_validator_pda(
    program: Program,
    client: AsyncClient,
    game_pda: Pubkey,
    game_number: int,
    validator_kp: Keypair
) -> Pubkey:
    """
    Registers a new validator for the given Game by creating validator_pda from:
    seeds = [b"validator", game_number, game.validator_count].
    Then calls the on-chain instruction `register_validator_pda`.
    Returns the derived validator_pda so we can use it later.
    """

    print("\nRegistering a new Validator PDA...")

    # 1) Fetch the Game account to get the 'validator_count'
    game_data = await program.account["Game"].fetch(game_pda)
    validator_count = game_data.validator_count
    print(f"[DEBUG] game.validator_count = {validator_count}")

    # 2) Derive the new validator_pda from [b"validator", game_number_bytes, validator_count_bytes]
    game_number_bytes = game_number.to_bytes(4, "little")
    val_count_bytes   = validator_count.to_bytes(4, "little")
    seeds = [b"validator", game_number_bytes, val_count_bytes]
    (validator_pda, validator_pda_bump) = Pubkey.find_program_address(seeds, program.program_id)
    print(f"[DEBUG] Derived validator_pda = {validator_pda}, Bump = {validator_pda_bump}")

    # 3) Invoke `register_validator_pda`
    try:
        tx_sig = await program.rpc["register_validator_pda"](
            game_number,
            ctx=Context(
                accounts={
                    "game":          game_pda,
                    "validator_pda": validator_pda,
                    "user":          validator_kp.pubkey(),   # The 'user' is the validator
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[validator_kp],
            )
        )
        print(f"ValidatorPda registered. Tx Sig: {tx_sig}")
    except RPCException as e:
        print(f"Error registering Validator PDA: {e}")
        traceback.print_exc()
        raise

    return validator_pda  # <-- Return the derived validator PDA


async def punch_in(program: Program, game_pda: Pubkey, game_number: int, validator_kp: Keypair):
    """Punch in as validator for the given game."""
    print("\nPunching In as Validator...")
    try:
        tx = await program.rpc["punch_in"](
            game_number,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "validator": validator_kp.pubkey(),
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[validator_kp],
            )
        )
        print(f"Punched in successfully. Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error punching in: {e}")
        traceback.print_exc()
        raise


async def register_player_pda(
    program: Program,
    client: AsyncClient,
    dapp_pda: Pubkey,
    name: str,
    authority_kp: Keypair,
    reward_address: Pubkey,
):
    """
    Register a brand-new PlayerPda using seeds = [b"player_pda", dapp.global_player_count].
    """
    print("\nRegistering a new Player PDA...")

    # 1) Fetch the DApp to get global_player_count
    dapp_data = await program.account["DApp"].fetch(dapp_pda)
    current_count = dapp_data.global_player_count  # an integer
    print(f"[DEBUG] dapp.global_player_count = {current_count}")

    # 2) Derive the player_pda using seeds = [b"player_pda", current_count.to_le_bytes()]
    count_bytes = current_count.to_bytes(4, "little")
    seeds = [b"player_pda", count_bytes]
    (player_pda, player_pda_bump) = Pubkey.find_program_address(seeds, program.program_id)
    print(f"[DEBUG] Derived player_pda = {player_pda}, Bump = {player_pda_bump}")

    # 3) Call register_player_pda
    try:
        tx_sig = await program.rpc["register_player_pda"](
            name,
            authority_kp.pubkey(),
            reward_address,
            ctx=Context(
                accounts={
                    "dapp": dapp_pda,
                    "player_pda": player_pda,
                    "user": program.provider.wallet.public_key,
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[program.provider.wallet.payer],
            )
        )
        print(f"PlayerPda '{name}' created. Tx Sig: {tx_sig}")

    except RPCException as e:
        print(f"Error registering PlayerPda '{name}': {e}")
        traceback.print_exc()
        raise


async def submit_minting_list(
    program: Program,
    game_pda: Pubkey,
    game_number: int,
    player_names: list[str],
    validator_kp: Keypair,
    validator_pda: Pubkey,
):
    """Submit a minting list, calling your 'submit_minting_list' instruction."""
    print("\nSubmitting Minting List...")

    # We already know the correct validator_pda, so we can pass it in `remaining_accounts`.
    # The smart contract will see if val_pda.address == validator_signer.key().
    try:
        tx_sig = await program.rpc["submit_minting_list_new_approach"](
            game_number,
            player_names,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "validator": validator_kp.pubkey(),
                },
                signers=[validator_kp],
                remaining_accounts=[
                    # We pass this as read-only since the program expects to load it
                    AccountMeta(
                        pubkey=validator_pda,
                        is_signer=False,
                        is_writable=False,
                    ),
                ],
            ),
        )
        print(f"Minting list submitted successfully. Transaction Signature: {tx_sig}")
    except RPCException as e:
        print(f"Error submitting Minting List: {e}")
        traceback.print_exc()
        raise


async def main():
    try:
        # 1) Setup the provider + load IDL
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

        program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
        idl = Idl.from_json(idl_json)
        program = Program(idl, program_id, provider)
        print("Program loaded successfully.")

        # 2) Initialize the DApp
        dapp_pda = await initialize_dapp(program, client)

        # 3) Initialize a Game
        game_number = 1
        description = "Minimal Game Example"
        game_pda = await initialize_game(program, client, game_number, description, dapp_pda)

        # Load a local keypair to be the 'validator'.
        def load_keypair(path: str) -> Keypair:
            with Path(path).open() as f:
                secret = json.load(f)
            return Keypair.from_bytes(bytes(secret[0:64]))

        # 4) Register the validator => get the `validator_pda`
        validator_kp = load_keypair("./val1-keypair.json")
        validator_pda = await register_validator_pda(program, client, game_pda, game_number, validator_kp)

        # 5) Punch in as validator
        await punch_in(program, game_pda, game_number, validator_kp)

        # 6) Register a new Player (by creating a PlayerPda).
        player_kp = load_keypair("./player-keypair.json")  # This is the player's "authority"
        reward_address = player_kp.pubkey()
        await register_player_pda(
            program,
            client,
            dapp_pda,
            name="Alice",
            authority_kp=player_kp,
            reward_address=reward_address
        )

        # 7) Optionally, submit a Minting List. We'll pass the validator's keypair + validator_pda
        player_names = ["Alice"]
        await submit_minting_list(program, game_pda, game_number, player_names, validator_kp, validator_pda)

        print("\nAll tests completed successfully.")

    except Exception as e:
        print(f"An unexpected error occurred during testing.\n{e}")
        traceback.print_exc()
    finally:
        await client.close()
        print("Closed Solana RPC client.")


if __name__ == "__main__":
    asyncio.run(main())

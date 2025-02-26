import asyncio
import json
import traceback
from pathlib import Path

# anchorpy
from anchorpy import Program, Provider, Wallet, Idl, Context
from anchorpy.program.namespace.instruction import AccountMeta

# solders / solana
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException

# Same as before
#SPL_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SPL_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")

RENT_SYSVAR_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

def find_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """Derive the Associated Token Account (ATA) for a given owner and mint."""
    seeds = [bytes(owner), bytes(SPL_TOKEN_PROGRAM_ID), bytes(mint)]
    (ata, _) = Pubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
    return ata


async def initialize_game_and_mint(program: Program, client: AsyncClient, description: str):
    """
    Create a new Game + Mint in a single transaction using `initialize_game_and_mint`.
    Returns (game_pda, mint_authority_pda, mint_for_game_pda).
    """
    print("Initializing Game + Mint...")

    user_pubkey = program.provider.wallet.public_key

    # (1) Derive the new mint address with seed [b"my_spl_mint", user, description]
    (mint_for_game_pda, mint_bump) = Pubkey.find_program_address(
        [
            b"my_spl_mint",
            bytes(user_pubkey),
            description.encode("utf-8")
        ],
        program.program_id
    )

    # (2) Derive the MintAuthority => [b"mint_authority", mint_for_game_pda]
    (mint_authority_pda, ma_bump) = Pubkey.find_program_address(
        [b"mint_authority", bytes(mint_for_game_pda)],
        program.program_id
    )

    # (3) Derive the Game => [b"game", mint_for_game_pda]
    (game_pda, game_bump) = Pubkey.find_program_address(
        [b"game", bytes(mint_for_game_pda)],
        program.program_id
    )

    # Check if Game already exists (to avoid re-initializing)
    acct_info = await client.get_account_info(game_pda, commitment=Confirmed)
    if acct_info.value is not None:
        print(f"Game PDA {game_pda} already initialized. Skipping.")
        return (game_pda, mint_authority_pda, mint_for_game_pda)

    try:
        tx_sig = await program.rpc["initialize_game_and_mint"](
            description,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "mint_authority": mint_authority_pda,
                    "mint_for_game": mint_for_game_pda,
                    "user": user_pubkey,
                    "token_program": SPL_TOKEN_PROGRAM_ID,
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                    "rent": RENT_SYSVAR_ID,
                },
                signers=[program.provider.wallet.payer],
            )
        )
        print(f"Success! initialize_game_and_mint => Tx: {tx_sig}")
    except RPCException as e:
        print(f"Error: {e}")
        traceback.print_exc()
        raise

    return (game_pda, mint_authority_pda, mint_for_game_pda)


async def register_validator_pda(
    program: Program,
    client: AsyncClient,
    game_pda: Pubkey,
    mint_pubkey: Pubkey,
    validator_kp: Keypair,
    #game_number: int = 0
):
    """
    Calls the `register_validator_pda(game_number, mint_pubkey)` instruction.
    The code seeds the validator PDA at [b"validator", game.key(), user.key()].
    """
    print("\nRegistering a new ValidatorPDA...")

    # Derive the validator_pda from seeds: [b"validator", game.key(), user.key()]
    # We'll do a fetch on the game just to confirm it exists:
    game_acct = await client.get_account_info(game_pda, commitment=Confirmed)
    if game_acct.value is None:
        raise Exception(f"Game account not found: {game_pda}")

    (validator_pda, val_bump) = Pubkey.find_program_address(
        [
            b"validator",
            bytes(mint_pubkey),
            bytes(validator_kp.pubkey())
        ],
        program.program_id
    )

    # Derive the validator's ATA
    validator_ata = find_associated_token_address(validator_kp.pubkey(), mint_pubkey)

    try:
        tx = await program.rpc["register_validator_pda"](
            #game_number,
            mint_pubkey,  # <— matches #[instruction(game_number, mint_pubkey)]
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "fancy_mint": mint_pubkey,
                    "validator_pda": validator_pda,
                    "user": validator_kp.pubkey(),
                    "validator_ata": validator_ata,
                    "token_program": SPL_TOKEN_PROGRAM_ID,
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                    "rent": RENT_SYSVAR_ID,
                },
                signers=[validator_kp],
            )
        )
        print(f"Validator PDA created => {validator_pda}. Tx: {tx}")
    except RPCException as e:
        print(f"Error registering validator: {e}")
        traceback.print_exc()
        raise

    return validator_pda


async def punch_in(
    program: Program,
    game_pda: Pubkey,
    mint_pubkey: Pubkey,
    validator_kp: Keypair,
    validator_pda: Pubkey,
    #game_number: int = 0
):
    """
    Calls `punch_in(game_number, mint_pubkey)`.
    """
    print("\nPunching in...")

    try:
        tx_sig = await program.rpc["punch_in"](
            #game_number,
            mint_pubkey,  # again from #[instruction]
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "validator_pda": validator_pda,
                    "validator": validator_kp.pubkey(),
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[validator_kp],
            )
        )
        print(f"Punched in => Tx: {tx_sig}")
    except RPCException as e:
        print(f"Error punching in: {e}")
        traceback.print_exc()
        raise

async def create_player_ata(
    program: Program,
    client: AsyncClient,
    game_pda: Pubkey,
    mint_pubkey: Pubkey,
    user_kp: Keypair,
):
    """
    Calls `create_user_ata_if_needed(mint_pubkey)` to create the ATA if it doesn't exist.
.   returns user_ata
    """

    # ------------------------------------------------------------
    # 1) CREATE USER ATA IF NEEDED
    # ------------------------------------------------------------
    user_pubkey = user_kp.pubkey()
    user_ata = find_associated_token_address(user_pubkey, mint_pubkey)

    print(f"\nCreating ATA (if needed) for user={user_pubkey}, mint={mint_pubkey}")
    try:
        tx_sig = await program.rpc["create_user_ata_if_needed"](
            mint_pubkey,
            ctx=Context(
                accounts={
                    "user": user_pubkey,
                    "fancy_mint": mint_pubkey,
                    "game": game_pda,
                    "user_ata": user_ata,  # Anchor derives the address via init_if_needed
                    "token_program": SPL_TOKEN_PROGRAM_ID,  # or Token2022 if that's your ID
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                    "rent": RENT_SYSVAR_ID,
                },
                signers=[user_kp],
            ),
        )
        print(f"create_user_ata_if_needed => success. Tx: {tx_sig}")
    except RPCException as e:
        print(f"Error creating ATA: {e}")
        traceback.print_exc()
        raise
    return user_ata

async def register_player_pda(
    program: Program,
    client: AsyncClient,
    game_pda: Pubkey,
    mint_pubkey: Pubkey,
    name: str
):
    """
    Calls `register_player_pda(name, mint_pubkey)` => seeds:
        player_pda at [b"player_pda", game.key(), game.player_count]
        player_name_pda at [b"player_name", game.key(), name.as_bytes()]
    and increments game.player_count on-chain.
    """
    user_pubkey = program.provider.wallet.public_key

    # 1) Fetch Game to get the current `player_count`
    game_data = await program.account["Game"].fetch(game_pda)
    player_count = game_data.player_count
    print(f"Current game.player_count = {player_count}")

    # 2) Derive PDAs
    (player_pda, _) = Pubkey.find_program_address(
        [
            b"player_pda",
            bytes(game_pda),
            player_count.to_bytes(4, "little")
        ],
        program.program_id
    )
    (player_name_pda, _) = Pubkey.find_program_address(
        [
            b"player_name",
            bytes(game_pda),
            name.encode("utf-8")
        ],
        program.program_id
    )

    # 3) Derive the user’s ATA
    user_ata = find_associated_token_address(user_pubkey, mint_pubkey)
    leftover_accounts = []
    leftover_accounts.append(AccountMeta(pubkey=user_ata, is_signer=False, is_writable=True))

    try:
        tx = await program.rpc["register_player_pda"](
            name,
            mint_pubkey,  # from #[instruction(name, mint_pubkey)]
            ctx=Context(
                accounts={
                    "fancy_mint": mint_pubkey,
                    "game": game_pda,
                    "player_pda": player_pda,
                    "player_name_pda": player_name_pda,
                    "user": user_pubkey,
                    "token_program": SPL_TOKEN_PROGRAM_ID,
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                    "rent": RENT_SYSVAR_ID,
                },
                signers=[program.provider.wallet.payer],
                remaining_accounts=leftover_accounts,

            )
        )
        print(f"Registered player '{name}' => PlayerPDA={player_pda}. Tx: {tx}")
    except RPCException as e:
        print(f"Error registering player {name}: {e}")
        traceback.print_exc()
        raise

    return (player_pda, player_name_pda)


async def submit_minting_list(
    program: Program,
    game_pda: Pubkey,
    mint_pubkey: Pubkey,
    validator_kp: Keypair,
    validator_pda: Pubkey,
    mint_authority_pda: Pubkey,
    player_pda: Pubkey,
    player_ata: Pubkey,
):
    """
    Calls `submit_minting_list(game_number, mint_pubkey, player_ids, ...)`
    passing leftover=[(player_pda, ATA), (player_pda, ATA), ...].
    The on-chain code expects 2 leftover accounts per player: PlayerPda + ATA.
    """
    print("\nSubmitting minting list...")

    # For demonstration, we'll just do 1 or 2 players:
    # Suppose we define player_ids as [0, 1] etc. The code on-chain uses them to index leftover accounts.
    player_ids = [1]

    # Build leftover array: [ (PDA0,writable), (ATA0,writable), (PDA1,writable), (ATA1,writable), ... ]
    # leftover_accounts = []
    # for pda, ata in zip(player_pda_list, player_ata_list):
    #     leftover_accounts.append(AccountMeta(pubkey=pda, is_signer=False, is_writable=True))
    #     leftover_accounts.append(AccountMeta(pubkey=ata, is_signer=False, is_writable=True))
    leftover_accounts = [
        # IMPORTANT: Mark the PlayerPda as is_writable=True
        AccountMeta(pubkey=player_pda, is_signer=False, is_writable=True),
        # The ATA also needs to be writable if we do a `mint_to` on it
        AccountMeta(pubkey=player_ata, is_signer=False, is_writable=True),
    ]
    # skip ahead..  Unexpected error: object of type 'solders.pubkey.Pubkey' has no len()

    try:
        tx_sig = await program.rpc["submit_minting_list"](
            mint_pubkey,
            player_ids,
            ctx=Context(
                accounts={
                    "game": game_pda,
                    "validator_pda": validator_pda,
                    "validator": validator_kp.pubkey(),
                    "fancy_mint": mint_pubkey,
                    "mint_authority": mint_authority_pda,
                    "token_program": SPL_TOKEN_PROGRAM_ID,
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[validator_kp],
                remaining_accounts=leftover_accounts,
            ),
        )
        print(f"submit_minting_list => success. Tx: {tx_sig}")
    except RPCException as e:
        print(f"Error in submit_minting_list: {e}")
        traceback.print_exc()


async def main():
    client = AsyncClient("http://localhost:8899", commitment=Confirmed)
    wallet = Wallet.local()
    provider = Provider(client, wallet)

    # Load IDL from your local JSON
    idl_path = Path("../target/idl/fancoin.json")
    if not idl_path.exists():
        print(f"IDL file not found at {idl_path}")
        return

    with idl_path.open() as f:
        idl_json = f.read()
    idl = Idl.from_json(idl_json)

    # The new Program ID
    program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
    program = Program(idl, program_id, provider)
    game_pda_str = Path("game_pda.txt").read_text().strip()
    mint_auth_pda_str = Path("mint_auth_pda.txt").read_text().strip()
    minted_mint_pda_str = Path("minted_mint_pda.txt").read_text().strip()


    game_pda = Pubkey.from_string(game_pda_str)
    mint_auth_pda = Pubkey.from_string(mint_auth_pda_str)
    minted_mint_pda = Pubkey.from_string(minted_mint_pda_str)
    try:
    #     # 1) Create the Game+Mint in one go
    #     description = "Test Game"
    #     #(game_pda, mint_auth_pda, minted_mint_pda) = await initialize_game_and_mint(program, client, description)
    #     with open("game_pda.txt", "w") as f:
    #         f.write(str(game_pda))

    #     with open("mint_auth_pda.txt", "w") as f:
    #         f.write(str(mint_auth_pda))

    #     with open("minted_mint_pda.txt", "w") as f:
    #         f.write(str(minted_mint_pda))

    #     # Continue with the rest of your code...
    #     print("PDAs written to .txt files successfully!")
        # ...

        # 2) Register a validator
        #    Let's load a local Keypair for the validator
        def load_keypair(json_path: str) -> Keypair:
            with open(json_path, "r") as f:
                data = json.load(f)
            return Keypair.from_bytes(bytes(data[:64]))

        validator_kp = load_keypair("val2-keypair.json")
        user_kp = load_keypair("id.json")

        # Here we can choose any game_number. The code suggests we pass (game_number, mint_pubkey).
        #game_number = 0
        validator_pda = await register_validator_pda(
            program, client,
            game_pda=game_pda,
            mint_pubkey=minted_mint_pda,
            validator_kp=validator_kp,
            #game_number=game_number
        )

        # 3) Punch in
        await punch_in(
            program,
            game_pda=game_pda,
            mint_pubkey=minted_mint_pda,
            validator_kp=validator_kp,
            validator_pda=validator_pda,
            #game_number=game_number
        )

        user_ata = await create_player_ata(
            program, client,
            game_pda=game_pda,
            mint_pubkey=minted_mint_pda,
            user_kp=user_kp
        )
        # 4) Register a player
        #    We'll register the payer (the same as wallet.local()) as "Alice"
        player_name = "Alice2"
        (alice_pda, alice_name_pda) = await register_player_pda(
            program, client,
            game_pda=game_pda,
            mint_pubkey=minted_mint_pda,
            name=player_name
        )

        # The player’s ATA is automatically created, but we can confirm it:
        user_ata = find_associated_token_address(user_kp.pubkey(), minted_mint_pda)
        print("user_ata=",user_ata)
        # 5) Submit a minting list with leftover accounts for 1 player

        print("program=", program, "game_pda=", game_pda, "mint_pubkey=", minted_mint_pda, "validator_kp=", validator_kp, "validator_pda=", validator_pda, "mint_auth_pda=", mint_auth_pda, "alice_pda=", alice_pda, "user_ata=", user_ata)
        await submit_minting_list(
            program,
            game_pda=game_pda,
            mint_pubkey=minted_mint_pda,
            validator_kp=validator_kp,
            validator_pda=validator_pda,
            mint_authority_pda=mint_auth_pda,
            player_pda=alice_pda,
            player_ata=user_ata,
        )

        print("\nAll done.")
    except Exception as err:
        print("Unexpected error:", err)
        traceback.print_exc()
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())

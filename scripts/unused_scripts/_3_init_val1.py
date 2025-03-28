import asyncio
from pathlib import Path
from enum import IntEnum
import traceback
import json
import os
# anchorpy
from anchorpy import Program, Provider, Wallet, Idl, Context
from anchorpy.program.namespace.instruction import AccountMeta

# solana / solders
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException

# Constants
SPL_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

class DappStatus(IntEnum):
    Probationary = 0
    Whitelisted = 1
    Blacklisted = 2

def find_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """
    Derive the Associated Token Account (ATA) for a given owner and mint.
    """
    seeds = [
        bytes(owner),                     # Convert Pubkey to bytes
        bytes(SPL_TOKEN_PROGRAM_ID),      # Convert SPL Token Program ID to bytes
        bytes(mint),                      # Convert Mint Pubkey to bytes
    ]
    ata, _ = Pubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
    return ata

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

async def initialize_mint(program: Program, client: AsyncClient, dapp_pda: Pubkey) -> (Pubkey, Pubkey):
    """
    Initialize the Mint for the DApp, returning (mint_authority_pda, mint_for_dapp_pda).
    Sets dapp.mint_pubkey on-chain.
    """
    print("\nInitializing Mint for DApp...")

    # seeds for each PDA
    mint_authority_pda, _ = Pubkey.find_program_address([b"mint_authority"], program.program_id)
    mint_for_dapp_pda, _  = Pubkey.find_program_address([b"my_spl_mint"], program.program_id)

    # Check if they might already exist
    mint_auth_acct = await client.get_account_info(mint_authority_pda, commitment=Confirmed)
    mint_acct      = await client.get_account_info(mint_for_dapp_pda, commitment=Confirmed)
    if mint_auth_acct.value is not None and mint_acct.value is not None:
        print("Mint + MintAuthority accounts already exist; skipping.")
        return (mint_authority_pda, mint_for_dapp_pda)

    try:
        token_pid = SPL_TOKEN_PROGRAM_ID

        tx = await program.rpc["initialize_mint"](
            ctx=Context(
                accounts={
                    "dapp":            dapp_pda,
                    "mint_authority":  mint_authority_pda,
                    "mint_for_dapp":   mint_for_dapp_pda,
                    "payer":           program.provider.wallet.public_key,
                    "token_program":   token_pid,
                    "system_program":  SYS_PROGRAM_ID,
                    "rent": Pubkey.from_string("SysvarRent111111111111111111111111111111111")
                },
                signers=[program.provider.wallet.payer],
            )
        )
        print(f"InitializeMint => Transaction Signature: {tx}")
    except RPCException as e:
        print(f"Error initializing the mint: {e}")
        traceback.print_exc()
        raise

    return (mint_authority_pda, mint_for_dapp_pda)

async def initialize_dapp(
    program: Program, client: AsyncClient, dapp_number: int, description: str, dapp_pda: Pubkey
) -> Pubkey:
    """Initialize the Dapp, returning the Dapp PDA."""
    print("\nInitializing Dapp account...")
    dapp_pda, dapp_bump = Pubkey.find_program_address(
        [b"dapp", dapp_number.to_bytes(4, "little")], program.program_id
    )
    print(f"Dapp PDA: {dapp_pda}, Bump: {dapp_bump}")

    dapp_account = await client.get_account_info(dapp_pda, commitment=Confirmed)
    if dapp_account.value is None:
        try:
            tx = await program.rpc["initialize_dapp"](
                dapp_number,
                description,
                ctx=Context(
                    accounts={
                        "dapp": dapp_pda,
                        "dapp": dapp_pda,
                        "user": program.provider.wallet.public_key,
                        "system_program": SYS_PROGRAM_ID,
                    },
                    signers=[program.provider.wallet.payer],
                )
            )
            print(f"Dapp initialized successfully. Transaction Signature: {tx}")
        except RPCException as e:
            print(f"Error initializing Dapp: {e}")
            traceback.print_exc()
            raise
    else:
        print("Dapp account already exists. Skipping initialization.")

    return dapp_pda

async def register_validator_pda(
    program: Program,
    client: AsyncClient,
    dapp_pda: Pubkey,
    dapp_number: int,
    validator_kp: Keypair,
    fancy_mint: Pubkey,           # Pass the mint pubkey
    dapp_pda: Pubkey,             # Pass the DApp PDA
) -> Pubkey:
    """Create a new validator + ATA for that validator on chain."""
    print("\nRegistering a new Validator PDA (user-based seeds)...")
    
    # Derive the validator_pda
    seeds_val = [b"validator", dapp_number.to_bytes(4, "little"), bytes(validator_kp.pubkey())]
    validator_pda, _ = Pubkey.find_program_address(seeds_val, program.program_id)
    print(f"[DEBUG] Derived validator_pda = {validator_pda}")

    # Derive the validator's ATA
    validator_ata_pubkey = find_associated_token_address(validator_kp.pubkey(), fancy_mint)
    print(f"[DEBUG] Derived validator ATA: {validator_ata_pubkey}")

    # Build AnchorPy Context with the derived ATA
    ctx = Context(
        accounts={
            "dapp": dapp_pda,
            "fancy_mint": fancy_mint,
            "validator_pda": validator_pda,
            "user": validator_kp.pubkey(),
            "validator_ata": validator_ata_pubkey,  # Pass the ATA pubkey
            "dapp": dapp_pda,
            "token_program": SPL_TOKEN_PROGRAM_ID,
            "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
            "system_program": SYS_PROGRAM_ID,
            "rent": Pubkey.from_string("SysvarRent111111111111111111111111111111111")
        },
        signers=[validator_kp],
    )

    # Call the instruction
    try:
        tx_sig = await program.rpc["register_validator_pda"](
            dapp_number,
            ctx=ctx
        )
        print(f"ValidatorPda registered => {validator_pda}. Tx Sig: {tx_sig}")
    except RPCException as e:
        print(f"Error registering Validator PDA: {e}")
        traceback.print_exc()
        raise

    return validator_pda

async def punch_in(program: Program, dapp_pda: Pubkey, dapp_number: int, validator_kp: Keypair, validator_pda: Pubkey):
    """Punch in as validator for the given dapp."""
    print("\nPunching In as Validator...")
    try:
        tx = await program.rpc["punch_in"](
            dapp_number,
            ctx=Context(
                accounts={
                    "dapp": dapp_pda,
                    "validator_pda": validator_pda,  # Added validator_pda
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

async def create_player_ata(
    program: Program,
    client: AsyncClient,
    dapp_pda: Pubkey,
    mint_pubkey: Pubkey,
    dapp_pda: Keypair,
):
    """
    Calls `create_user_ata_if_needed(mint_pubkey)` to create the ATA if it doesn't exist.
.   returns user_ata
    """

    # ------------------------------------------------------------
    # 1) CREATE USER ATA IF NEEDED
    # ------------------------------------------------------------

    user_kp = load_keypair("./id.json")

    user_pubkey = user_kp.pubkey()
    user_ata = find_associated_token_address(user_pubkey, mint_pubkey)

    print(f"\nCreating ATA (if needed) for user={user_pubkey}, mint={mint_pubkey}")
    try:
        tx_sig = await program.rpc["create_user_ata_if_needed"](
            ctx=Context(
                accounts={
                    "dapp": dapp_pda,
                    "user": user_pubkey,
                    "fancy_mint": mint_pubkey,
                    "dapp": dapp_pda,
                    "user_ata": user_ata,  # Anchor derives the address via init_if_needed
                    "token_program": SPL_TOKEN_PROGRAM_ID,  # or Token2022 if that's your ID
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                    "rent": Pubkey.from_string("SysvarRent111111111111111111111111111111111"),
                },
                signers=[user_kp],
            ),
        )
        print(f"create_user_ata_if_needed => success. Tx: {tx_sig}")
        tx_resp = await client.get_transaction(tx_sig, commitment=Confirmed)
        # This returns a GetTransactionResp from the RPC

        if tx_resp.value and tx_resp.value.transaction.meta:
            logs = tx_resp.value.transaction.meta.log_messages
            print("Transaction logs:")
            for line in logs:
                print(line)
    except RPCException as e:
        print(f"Error creating ATA: {e}")
        traceback.print_exc()
        raise
    return user_ata

async def register_player_pda(
    program: Program,
    client: AsyncClient,
    dapp_pda: Pubkey,
    name: str,
    fancy_mint: Pubkey,  # Add this parameter
):
    """Register a PlayerPda using the dapp.global_player_count approach."""
    print("\nRegistering a new Player PDA...")

    # 1) Fetch the DApp to get global_player_count
    dapp_data = await program.account["DApp"].fetch(dapp_pda)
    current_count = dapp_data.global_player_count
    print(f"[DEBUG] dapp.global_player_count = {current_count}")

    # 2) Derive the new player_pda
    player_pda, p_bump = Pubkey.find_program_address(
        [b"player_pda", current_count.to_bytes(4, "little")],
        program.program_id
    )
    print(f"[DEBUG] Derived player_pda = {player_pda}, Bump = {p_bump}")
    # 3) Derive the player_name_pda => [b"player_name", name.as_bytes()]
    (player_name_pda, name_bump) = Pubkey.find_program_address(
        [
            b"player_name",
            name.encode("utf-8"),  # The string "Alice" => b"Alice"
        ],
        program.program_id
    )
    print(f"[DEBUG] Derived player_name_pda = {player_name_pda}, Bump = {name_bump}")

    # 4) Derive the user's ATA using the custom function
    user_pubkey = program.provider.wallet.public_key
    # user_ata = find_associated_token_address(user_pubkey, fancy_mint)
    user_ata = find_associated_token_address(user_pubkey, fancy_mint)
    leftover_accounts = []
    leftover_accounts.append(AccountMeta(pubkey=user_ata, is_signer=False, is_writable=True))

    print(f"[DEBUG] Derived user_ata = {user_ata}")

    try:
        tx_sig = await program.rpc["register_player_pda"](
            name,
            ctx=Context(
                accounts={
                    "dapp": dapp_pda,
                    "fancy_mint": fancy_mint,               # Pass fancy_mint
                    "player_pda": player_pda,
                    "player_name_pda": player_name_pda,
                    "user": user_pubkey,
                    "user_ata": user_ata,                   # Pass user_ata
                    "token_program": SPL_TOKEN_PROGRAM_ID,
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                    "rent": Pubkey.from_string("SysvarRent111111111111111111111111111111111"),
                },
                signers=[program.provider.wallet.payer],
                remaining_accounts=leftover_accounts
            )
        )
        print(f"PlayerPda '{name}' created => {player_pda}. Tx Sig: {tx_sig}")
    except RPCException as e:
        print(f"Error registering PlayerPda '{name}': {e}")
        traceback.print_exc()
        raise

async def submit_minting_list(
    program: Program,
    dapp_pda: Pubkey,
    dapp_pda: Pubkey,
    dapp_number: int,
    validator_kp: Keypair,
    validator_pda: Pubkey,
    fancy_mint: Pubkey,
    mint_auth_pda: Pubkey,
    leftover_player_pda: Pubkey,
    leftover_player_ata: Pubkey,
):
    """
    Example usage: single leftover (PlayerPda, ATA) => one "player_id".
    The on-chain code expects leftover=2 per player => [PlayerPda, ATA].
    
    NOTE: Mark the PlayerPda leftover as `is_writable=True` so we can update it on-chain.
    """
    print("\nSubmitting Minting List => leftover [PlayerPda, ATA]...")

    # leftover => 2 per player
    leftover_accounts = [
        # IMPORTANT: Mark the PlayerPda as is_writable=True
        AccountMeta(pubkey=leftover_player_pda, is_signer=False, is_writable=True),
        # The ATA also needs to be writable if we do a `mint_to` on it
        AccountMeta(pubkey=leftover_player_ata, is_signer=False, is_writable=True),
    ]

    # We'll pass a single "player_id"
    player_ids = [0]  # example

    try:
        token_pid = SPL_TOKEN_PROGRAM_ID

        tx_sig = await program.rpc["submit_minting_list"](
            dapp_number,
            player_ids,
            ctx=Context(
                accounts={
                    "dapp":           dapp_pda,
                    "validator_pda":  validator_pda,
                    "validator":      validator_kp.pubkey(),
                    "fancy_mint":     fancy_mint,
                    "dapp":           dapp_pda,
                    "mint_authority": mint_auth_pda,
                    "token_program":  token_pid,
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[validator_kp],
                remaining_accounts=leftover_accounts,
            ),
        )
        print(f"Minting list submitted. Tx: {tx_sig}")
    except RPCException as e:
        print(f"Error in submit_minting_list: {e}")
        traceback.print_exc()

def load_keypair(path: str) -> Keypair:
    with Path(path).open() as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret[0:64]))

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

        program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
        idl = Idl.from_json(idl_json)
        program = Program(idl, program_id, provider)
        print("Program loaded successfully.")

        # 1) Initialize the Dapp
        dapp_pda = await initialize_dapp(program, client)
        file_name = "output.txt"
        # 2) Initialize the Mint
        (mint_auth_pda, mint_for_dapp_pda) = await initialize_mint(program, client, dapp_pda)
        with open(file_name, "w") as file:
            file.write(str(mint_for_dapp_pda))  # Convert the variable to a string if necessary

        print(f"The variable has been written to {file_name}")
        # 3) Initialize a Dapp
        dapp_number = 1
        description = "Minimal Dapp Example"
        dapp_pda = await initialize_dapp(program, client, dapp_number, description, dapp_pda)

        # 4) Register a validator


        validator_kp = load_keypair("./val1-keypair.json")
        validator_pda = await register_validator_pda(
            program=program,
            client=client,
            dapp_pda=dapp_pda,
            dapp_number=dapp_number,
            validator_kp=validator_kp,
            fancy_mint=mint_for_dapp_pda,
            dapp_pda=dapp_pda
        )

        # 5) Punch in as validator
        await punch_in(program, dapp_pda, dapp_number, validator_kp, validator_pda)  # Pass validator_pda

        # 6) Register a new Player
        player_kp = load_keypair("./player-keypair.json")
        # No need to specify reward_address; it will be set to user_ata

        alice_ata = await create_player_ata(
            program, client,
            dapp_pda=dapp_pda,
            mint_pubkey=mint_for_dapp_pda,
            dapp_pda=dapp_pda
        )

        await register_player_pda(
            program, client, dapp_pda,
            name="Alice",
            fancy_mint=mint_for_dapp_pda  # Pass the mint pubkey here
        )

        # 7) Suppose we create a dummy ATA for the "Alice" player:
        #dummy_player_ata = find_associated_token_address(Pubkey.from_string("DummyPlayerPubkeyHere"), mint_for_dapp_pda)  # Replace with actual Pubkey

        # For simplicity, let's guess the new PlayerPda is index 0
        alice_pda, _ = Pubkey.find_program_address(
            [b"player_pda", (0).to_bytes(4, "little")],
            program_id
        )

        # 8) Now submit a single player's leftover => [alice_pda, dummy_player_ata]
        #   We must pass dapp_pda as well
        await submit_minting_list(
            program,
            dapp_pda=dapp_pda,          # Pass in the known DApp
            dapp_pda=dapp_pda,
            dapp_number=dapp_number,
            validator_kp=validator_kp,
            validator_pda=validator_pda,
            fancy_mint=mint_for_dapp_pda,
            mint_auth_pda=mint_auth_pda,
            leftover_player_pda=alice_pda,
            leftover_player_ata=alice_ata,
        )
        with open("dapp_pda.txt", "w") as f:
            f.write(str(dapp_pda))

        with open("mint_auth_pda.txt", "w") as f:
            f.write(str(mint_auth_pda))

        with open("minted_mint_pda.txt", "w") as f:
            f.write(str(mint_for_dapp_pda))

        # Continue with the rest of your code...
        print("PDAs written to .txt files successfully!")
        # ...
        print("\nAll tests completed successfully.")

    except Exception as e:
        print(f"An unexpected error occurred.\n{e}")
        traceback.print_exc()
    finally:
        await client.close()
        print("Closed Solana RPC client.")

if __name__ == "__main__":
    asyncio.run(main())
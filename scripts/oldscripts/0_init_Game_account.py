import asyncio
import json
import traceback
from pathlib import Path

from anchorpy import Program, Provider, Wallet, Idl, Context
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from solders.system_program import create_account, CreateAccountParams, ID as SYS_PROGRAM_ID
from solana.transaction import Transaction
from solana.rpc.core import RPCException

async def main():
    # Connect to localnet
    client = AsyncClient("http://localhost:8899", commitment=Confirmed)
    wallet = Wallet.local()
    provider = Provider(client, wallet)

    # Load the IDL
    idl_path = Path("../target/idl/fancoin.json")  # Adjust path if needed
    if not idl_path.exists():
        print("IDL file not found")
        return
    with idl_path.open() as f:
        idl_json_str = f.read()
    idl = Idl.from_json(idl_json_str)

    # Your program ID
    your_program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
    program = Program(idl, your_program_id, provider)

    user = wallet.public_key

    # Derive a PDA for "game"
    game_number = 1
    (game_pda, game_bump) = Pubkey.find_program_address(
        [b"game", game_number.to_bytes(4, "little")],
        your_program_id
    )

    # Space larger than 10k to force a large initial allocation
    space = 15000
    rent_exempt_lamports = (await client.get_minimum_balance_for_rent_exemption(space)).value

    # Check if the game account already exists
    game_account_info = await client.get_account_info(game_pda, commitment=Confirmed)
    if game_account_info.value is not None:
        print("Game account already exists. Skipping initialization.")
        await client.close()
        return

    # Instruction to create the account
    create_account_instruction = create_account(
        CreateAccountParams(
            from_pubkey=user,
            to_pubkey=game_pda,
            lamports=rent_exempt_lamports,
            space=space,
            owner=your_program_id
        )
    )

    # Arguments for initialize_game
    description = "My Large Game"

    # Build the initialize_game instruction via Anchor
    initialize_ix = program.instruction["initialize_game"](
        game_number,
        description,
        ctx=Context(
            accounts={
                "game": game_pda,
                "user": user,
                "system_program": SYS_PROGRAM_ID,
            },
            signers = [program.provider.wallet.payer]
        )
    )

    # Fetch a recent blockhash
    recent_blockhash_resp = await provider.connection.get_latest_blockhash()
    if recent_blockhash_resp.value is None:
        raise Exception("Failed to get a recent blockhash")
    blockhash = recent_blockhash_resp.value.blockhash

    # Create the transaction and add instructions
    txn = Transaction()
    # recent_blockhash=blockhash, fee_payer=user)
    txn.add(create_account_instruction)
    txn.add(initialize_ix)
    txn.recent_blockhash = blockhash
    txn.fee_payer = user

    # Sign the transaction with the provider's wallet
    # This assumes your wallet can sign and has enough funds to create the account.
    signed_tx = provider.wallet.sign_transaction(txn)

    try:
        tx_sig = await provider.connection.send_raw_transaction(signed_tx.serialize())
        print("Transaction Signature:", tx_sig)
        print("Game initialized successfully.")
    except RPCException as e:
        print("Error sending transaction:", e)
        traceback.print_exc()
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())

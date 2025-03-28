import asyncio
import json
import traceback
from pathlib import Path

from anchorpy import Program, Provider, Wallet, Idl, Context
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams

from solders.system_program import create_account, CreateAccountParams, ID as SYS_PROGRAM_ID
from solana.transaction import Transaction

async def main():
    client = AsyncClient("http://localhost:8899", commitment=Confirmed)
    wallet = Wallet.local()
    provider = Provider(client, wallet)

    # Load the IDL
    idl_path = Path("../target/idl/fancoin.json")
    if not idl_path.exists():
        print("IDL file not found")
        await client.close()
        return

    with idl_path.open() as f:
        idl_json_str = f.read()
    idl = Idl.from_json(idl_json_str)

    program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
    program = Program(idl, program_id, provider)

    user = wallet.public_key
    dapp_number = 1

    # Derive PDA and bump
    (dapp_pda, dapp_bump) = Pubkey.find_program_address(
        [b"dapp", dapp_number.to_bytes(4, "little")],
        program_id
    )
    print(f"Dapp PDA: {dapp_pda}, bump: {dapp_bump}")
    lamports_to_send = 1_000_000_000

    ix = transfer(
        TransferParams(
            from_pubkey=wallet.public_key,
            to_pubkey=dapp_pda,
            lamports=lamports_to_send
        )
    )
    tx = Transaction()
    tx.add(ix)

    latest_blockhash_resp = await provider.connection.get_latest_blockhash()
    if latest_blockhash_resp.value is None:
        raise Exception("Failed to get a recent blockhash")

    blockhash = latest_blockhash_resp.value.blockhash

    # Set the recent blockhash and fee payer
    tx.recent_blockhash = blockhash
    tx.fee_payer = wallet.public_key

    try:
        # Sign the transaction with the provider's wallet (synchronously)
        signed_tx = provider.wallet.sign_transaction(tx)
        # Also sign with the player's keypair
        #signed_tx.sign(player_keypair)

        # Now send the transaction directly via the RPC client
        resp = await provider.connection.send_raw_transaction(signed_tx.serialize())
        print(f"Transaction Signature: {resp}")
        print("Transfer completed successfully.")
    except RPCException as e:
        print(f"Error transferring lamports: {e}")


    # Allocate space > 10KB
    space = 15000
    rent_exempt_lamports = (await client.get_minimum_balance_for_rent_exemption(space)).value

    # Create a temporary normal account (staging_account) owned by system program
    # We will then call `initialize_dapp` which should use invoke_signed to assert PDA and reassign.
    staging_keypair = Keypair()
    staging_pubkey = staging_keypair.pubkey()
    print(staging_keypair.pubkey())
    # Check if staging account already exists
    staging_info = await client.get_account_info(staging_pubkey, commitment=Confirmed)
    if staging_info.value is not None:
        print("Staging account already exists. Skipping.")
        await client.close()
        return

    # Create the staging account
    create_ix = create_account(
        CreateAccountParams(
            from_pubkey=user,
            to_pubkey=staging_pubkey,
            lamports=rent_exempt_lamports,
            space=space,
            owner=SYS_PROGRAM_ID  # Start as system-owned
        )
    )

    # Fetch a recent blockhash
    latest_blockhash_resp = await provider.connection.get_latest_blockhash()
    if latest_blockhash_resp.value is None:
        raise Exception("Failed to get a recent blockhash")
    blockhash = latest_blockhash_resp.value.blockhash

    # Create and send transaction to create staging account
    tx = Transaction(recent_blockhash=blockhash, fee_payer=user)
    tx.add(create_ix)
    tx.sign(provider.wallet.payer, staging_keypair)
    # try:
    #     resp = await provider.connection.send_raw_transaction(tx.serialize())
    #     print("Staging account created successfully with signature:", resp)
    # except RPCException as e:
    #     print("Error creating staging account:", e)
    #     traceback.print_exc()
    #     await client.close()
    #     return

    # Now call initialize_dapp, passing dapp_bump and the staging account as 'dapp'
    # Your initialize_dapp must:
    #  1) Use invoke_signed to reassign 'dapp' account from system_program to your program-owned PDA address
    #  2) Validate seeds and bump
    #  3) Possibly reallocate or finalize the account as needed
    description = "My Large Dapp"
    try:
        tx_sig = await program.rpc["init_dapp_one"](
            dapp_number,
            description,
            # dapp_bump,  # Pass the bump if your Rust code requires it as an argument
            ctx=Context(
                accounts={
                    "dapp": staging_pubkey,  # The program will reassign this to the PDA internally
                    "user": user,
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[]
            )
        )
        print("Dapp initialized successfully with signature:", tx_sig)
    except RPCException as e:
        print("Error initializing dapp:", e)
        traceback.print_exc()

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())

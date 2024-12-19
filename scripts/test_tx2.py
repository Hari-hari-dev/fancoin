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
from solders.system_program import create_account, CreateAccountParams, transfer, TransferParams, ID as SYS_PROGRAM_ID
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
    game_number = 1

    # Derive PDA and bump
    (game_pda, game_bump) = Pubkey.find_program_address(
        [b"game", game_number.to_bytes(4, "little")],
        program_id
    )
    print(f"Game PDA: {game_pda}, bump: {game_bump}")

    # Allocate space > 10KB
    space = 15000
    rent_exempt_lamports = (await client.get_minimum_balance_for_rent_exemption(space)).value

    # Check if game_pda already exists
    game_info = await client.get_account_info(game_pda, commitment=Confirmed)
    if game_info.value is not None:
        print("Game PDA already exists. Skipping creation.")
    else:
        # Create the PDA account (system-owned for now)
        create_ix = create_account(
            CreateAccountParams(
                from_pubkey=user,
                to_pubkey=game_pda,
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

        # Create and send transaction to create the game PDA account
        tx = Transaction(recent_blockhash=blockhash, fee_payer=user)
        tx.add(create_ix)
        tx.sign(provider.wallet.payer)
        try:
            resp = await provider.connection.send_raw_transaction(tx.serialize())
            print("Game PDA account created successfully with signature:", resp)
        except RPCException as e:
            print("Error creating game PDA account:", e)
            traceback.print_exc()
            await client.close()
            return

    # Now fund the game_pda with 1 SOL (1_000_000_000 lamports)
    lamports_to_send = 1_000_000_000
    transfer_ix = transfer(
        TransferParams(
            from_pubkey=user,
            to_pubkey=game_pda,
            lamports=lamports_to_send
        )
    )

    # Send the transfer transaction
    latest_blockhash_resp = await provider.connection.get_latest_blockhash()
    if latest_blockhash_resp.value is None:
        raise Exception("Failed to get a recent blockhash for transfer")
    blockhash = latest_blockhash_resp.value.blockhash

    fund_tx = Transaction(recent_blockhash=blockhash, fee_payer=user)
    fund_tx.add(transfer_ix)
    signed_fund_tx = provider.wallet.sign_transaction(fund_tx)
    try:
        fund_resp = await provider.connection.send_raw_transaction(signed_fund_tx.serialize())
        print(f"Transferred 1 SOL to {game_pda}, signature: {fund_resp}")
    except RPCException as e:
        print("Error transferring lamports to game PDA:", e)
        traceback.print_exc()
        await client.close()
        return

    # Now call initialize_game using the game_pda as 'game'
    description = "My Large Game"
    try:
        tx_sig = await program.rpc["initialize_game"](
            game_number,
            description,
            ctx=Context(
                accounts={
                    "game": game_pda,  # The PDA we created and funded
                    "user": user,
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[]
            )
        )
        print("Game initialized successfully with signature:", tx_sig)
    except RPCException as e:
        print("Error initializing game:", e)
        traceback.print_exc()

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())

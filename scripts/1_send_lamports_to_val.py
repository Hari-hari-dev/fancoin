import asyncio
import json
from pathlib import Path

from anchorpy import Provider, Wallet
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solana.transaction import Transaction

def load_keypair(path: str) -> Keypair:
    with Path(path).open() as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret[0:64]))

async def main():
    # Connect to local cluster and set up provider
    client = AsyncClient("http://localhost:8899", commitment=Confirmed)
    wallet = Wallet.local()
    provider = Provider(client, wallet)

    # Load the player's keypair
    player_keypair = load_keypair("./player-keypair.json")

    # We want to send 1 SOL = 1_000_000_000 lamports
    lamports_to_send = 1_000_000_000

    # Create the transfer instruction
    ix = transfer(
        TransferParams(
            from_pubkey=wallet.public_key,
            to_pubkey=player_keypair.pubkey(),
            lamports=lamports_to_send
        )
    )

    # Create a new transaction and add the instruction
    tx = Transaction()
    tx.add(ix)

    # Fetch a recent blockhash
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

    # Close the client connection
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())

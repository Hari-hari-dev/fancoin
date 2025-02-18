import asyncio
import base58
from anchorpy import Provider, Wallet
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from solders.keypair import Keypair
from solders.system_program import transfer, TransferParams
from solana.transaction import Transaction
from solders.pubkey import Pubkey

def keypair_from_base58(base58_key: str) -> Keypair:
    secret_key_bytes = base58.b58decode(base58_key)
    return Keypair.from_bytes(secret_key_bytes)

async def main():
    # 1) Base-58 private key (86 chars, for example)
    base58_private_key = "4552gqp7RHMjkPmni6yeWWLUxYh1maEqny1BfQfLbpJJRWXJpMPd7aSNaNRUuQtCqHZR1jquTrcftqmgWKDZziyg"  # (example)

    # 2) Construct keypair
    sender_keypair = keypair_from_base58(base58_private_key)

    # 3) Connect to Solana Devnet
    client = AsyncClient("https://api.devnet.solana.com", commitment=Confirmed)

    # 4) Create an AnchorPy wallet + provider
    wallet = Wallet(sender_keypair)
    provider = Provider(client, wallet)

    # 5) Destination & amount
    destination_str = "5DWJghsJtVS3zSS18HwCKmvsgWXytsFFvYfBgtSnA652"
    destination_pubkey = Pubkey.from_string(destination_str)
    lamports_to_send = int(14.90 * 1_000_000_000)  # 0.01 SOL

    # 6) Construct the transfer instruction
    ix = transfer(
        TransferParams(
            from_pubkey=wallet.public_key,
            to_pubkey=destination_pubkey,
            lamports=lamports_to_send
        )
    )

    # 7) Create a transaction & fetch blockhash
    tx = Transaction()
    tx.add(ix)

    latest_blockhash_resp = await provider.connection.get_latest_blockhash()
    if latest_blockhash_resp.value is None:
        raise Exception("Failed to get a recent blockhash")

    blockhash = latest_blockhash_resp.value.blockhash
    tx.recent_blockhash = blockhash
    tx.fee_payer = wallet.public_key

    # 8) Sign & send
    try:
        signed_tx = wallet.sign_transaction(tx)
        tx_sig = await provider.connection.send_raw_transaction(signed_tx.serialize())
        print(f"Sent 0.01 SOL to {destination_str} on Devnet.")
        print(f"Transaction signature: {tx_sig}")
    except RPCException as e:
        print(f"RPC Error sending transaction: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

    # 9) Close client
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())

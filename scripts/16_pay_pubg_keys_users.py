import asyncio
import json
import traceback
from pathlib import Path

from anchorpy import Provider, Wallet
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.transaction import Transaction
from solana.rpc.core import RPCException

PLAYERS_FOLDER = Path("pubg_keys")
RPC_URL = "http://localhost:8899"  # or devnet/mainnet
LAMPORTS_TO_SEND = 100_000_000     # 0.1 SOL (change as desired)

async def main():
    # 1) Connect to local cluster and set up provider
    client = AsyncClient(RPC_URL, commitment=Confirmed)
    wallet = Wallet.local()        # The funder's keypair (the payer of the transfer)
    provider = Provider(client, wallet)

    # 2) Collect all JSON files from your pubg_keys folder
    if not PLAYERS_FOLDER.is_dir():
        print(f"[ERROR] The folder {PLAYERS_FOLDER} does not exist.")
        return
    json_files = list(PLAYERS_FOLDER.glob("*.json"))
    if not json_files:
        print(f"[ERROR] No .json files in {PLAYERS_FOLDER}/.")
        return

    print(f"[INFO] Funding each user in {PLAYERS_FOLDER}/ with {LAMPORTS_TO_SEND} lamports.")

    # 3) Loop over each JSON => parse "player_authority_address" => do a transfer
    for file_path in json_files:
        try:
            data = json.loads(file_path.read_text())
            user_addr_str = data.get("player_authority_address")
            if not user_addr_str:
                print(f"[WARN] {file_path} => missing 'player_authority_address'. Skipping.")
                continue

            # parse as a Pubkey
            try:
                user_pubkey = Pubkey.from_string(user_addr_str)
            except Exception as e:
                print(f"[ERROR] Invalid user address {user_addr_str} => {e}. Skipping.")
                continue

            print(f"[INFO] Sending {LAMPORTS_TO_SEND} lamports to {user_pubkey} (from {file_path.name})")

            # Build the transfer ix
            ix = transfer(
                TransferParams(
                    from_pubkey=wallet.public_key,
                    to_pubkey=user_pubkey,
                    lamports=LAMPORTS_TO_SEND
                )
            )

            # Create a transaction, add the ix
            tx = Transaction()
            tx.add(ix)

            # fetch blockhash
            latest_blockhash_resp = await provider.connection.get_latest_blockhash()
            if latest_blockhash_resp.value is None:
                raise Exception("Failed to get a recent blockhash from the cluster.")

            blockhash = latest_blockhash_resp.value.blockhash
            tx.recent_blockhash = blockhash
            tx.fee_payer = wallet.public_key

            # sign with the local wallet
            signed_tx = provider.wallet.sign_transaction(tx)
            
            # Send it
            resp = await provider.connection.send_raw_transaction(signed_tx.serialize())
            print(f"[SUCCESS] => {user_pubkey}. Tx Sig: {resp}")

        except RPCException as e:
            print(f"[ERROR] RPC issue transferring lamports to {file_path.name}: {e}")
            traceback.print_exc()
        except Exception as e:
            print(f"[ERROR] Unexpected error => {file_path.name}: {e}")
            traceback.print_exc()

    # 4) Close the client
    await client.close()
    print("\n[INFO] Done funding all players.")

if __name__ == "__main__":
    asyncio.run(main())

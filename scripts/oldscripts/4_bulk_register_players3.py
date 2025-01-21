import asyncio
import json
import traceback
from pathlib import Path
from enum import IntEnum

from anchorpy import Program, Provider, Wallet, Idl, Context
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException

# The known program IDs
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
RENT_SYSVAR_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

###############################################################################
# Helper function to derive the Associated Token Address (ATA)
###############################################################################
def derive_ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """
    Manually derive the associated token account address for (owner, mint).
    This is equivalent to `spl_associated_token_account::get_associated_token_address`.
    Seeds = [owner, TOKEN_PROGRAM_ID, mint], with program_id=ASSOCIATED_TOKEN_PROGRAM_ID.
    """
    (ata_pubkey, _) = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
        ASSOCIATED_TOKEN_PROGRAM_ID,
    )
    return ata_pubkey

###############################################################################
# Utility Enums, etc.
###############################################################################
class GameStatus(IntEnum):
    Probationary = 0
    Whitelisted = 1
    Blacklisted = 2

###############################################################################
# The register_player_pda function
###############################################################################
async def register_player_pda(
    program: Program,
    dapp_pda: Pubkey,
    fancy_mint: Pubkey,
    player_name: str,
    player_keypair: Keypair,    # Player's Keypair used as `user`
    reward_pubkey: Pubkey
):
    """
    Registers a player by initializing their PlayerPda and associated token account.
    """
    try:
        # 1) Fetch typed DApp account object
        dapp_data = await program.account["DApp"].fetch(dapp_pda)
        current_count = dapp_data.global_player_count
        print(f"[DEBUG] current_count from on-chain DApp = {current_count}")

        # 2) Derive the new player_pda
        dapp_global_count_bytes = current_count.to_bytes(4, "little")
        (player_pda_pubkey, _) = Pubkey.find_program_address(
            [b"player_pda", dapp_global_count_bytes],
            program.program_id
        )
        print(f"[DEBUG] Derived player_pda => {player_pda_pubkey}")

        # 3) Derive the player's ATA manually
        player_pubkey = player_keypair.pubkey()
        user_ata_pubkey = derive_ata(player_pubkey, fancy_mint)
        print(f"[DEBUG] user_ata => {user_ata_pubkey} for player {player_name}")

        # Optional: Airdrop SOL to the player to cover transaction fees and ATA creation
        # Uncomment the following lines if players might not have enough SOL
        # Ensure you have airdrop enabled on your Solana cluster
        # airdrop_amount = 2_000_000_000  # 2 SOL in lamports
        # airdrop_tx = await program.provider.connection.request_airdrop(player_pubkey, airdrop_amount)
        # await program.provider.connection.confirm_transaction(airdrop_tx.value)
        # print(f"[DEBUG] Airdropped {airdrop_amount} lamports to {player_pubkey}")

        # 4) Call register_player_pda, passing in all required accounts:
        tx_sig = await program.rpc["register_player_pda"](
            player_name,
            ctx=Context(
                accounts={
                    "dapp": dapp_pda,
                    "fancy_mint": fancy_mint,
                    "player_pda": player_pda_pubkey,
                    "user": player_pubkey,  # Player's Pubkey as 'user'
                    "user_ata": user_ata_pubkey,
                    "token_program": TOKEN_PROGRAM_ID,
                    "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                    "system_program": SYS_PROGRAM_ID,
                    "rent": RENT_SYSVAR_ID,
                },
                # The player's Keypair must sign to authorize the transaction
                signers=[player_keypair],
            )
        )
        print(f"Player '{player_name}' => PlayerPda registered. Tx Sig: {tx_sig}")

        # Optionally fetch transaction logs
        confirmed_tx = await program.provider.connection.get_transaction(
            tx_sig, encoding='json'
        )
        if confirmed_tx.value and confirmed_tx.value.transaction.meta:
            logs = confirmed_tx.value.transaction.meta.log_messages
            if logs:
                # Example: Extract compute units consumed
                cu_regex = re.compile(r'Program \S+ consumed (\d+) of (\d+) compute units')
                consumed_cu = None
                max_cu = None
                for line in logs:
                    match = cu_regex.search(line)
                    if match:
                        consumed_cu = int(match.group(1))
                        max_cu = int(match.group(2))
                        break
                if consumed_cu is not None:
                    print(f"[DEBUG] Compute units => {consumed_cu}/{max_cu}")
                else:
                    print("[DEBUG] No compute units info found in logs.")
            else:
                print("[DEBUG] No log messages returned for transaction.")
        else:
            print("[DEBUG] No transaction meta/logs found.")

    except RPCException as e:
        print(f"[ERROR] registering player '{player_name}' => RPCException: {e}")
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"[ERROR] registering player '{player_name}': {e}")
        traceback.print_exc()
        raise

###############################################################################
# Main
###############################################################################
async def main():
    client = AsyncClient("http://localhost:8899", commitment=Confirmed)
    try:
        # 1) Setup Solana + Anchor env
        wallet = Wallet.local()
        provider = Provider(client, wallet)

        # 2) Load IDL
        idl_path = Path("../target/idl/fancoin.json")
        if not idl_path.exists():
            print(f"[ERROR] IDL file not found at {idl_path.resolve()}")
            return
        with idl_path.open() as f:
            idl = Idl.from_json(f.read())

        # 3) Create Program object
        program_id = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")
        program = Program(idl, program_id, provider)
        print("Program loaded successfully.")

        # 4) Derive the DApp PDA
        (dapp_pda, _) = Pubkey.find_program_address([b"dapp"], program_id)
        print(f"[DEBUG] dapp_pda => {dapp_pda}")

        # 5) The Mint that the DApp uses
        fancy_mint = Pubkey.from_string("DVkPNrxdgGxF5fqvnKgXj7DWcRSdimLChXKwAKYk7fiJ")

        # 6) Admin is the local wallet, but players will pay
        admin_pubkey = program.provider.wallet.public_key
        print(f"[DEBUG] admin_pubkey => {admin_pubkey}")

        # 7) Grab all .json keys in "player_keys"
        keys_folder = Path("player_keys")
        if not keys_folder.exists() or not keys_folder.is_dir():
            print(f"[ERROR] Folder {keys_folder} does not exist or is not a directory.")
            return

        json_files = list(keys_folder.glob("*.json"))
        if not json_files:
            print(f"No .json files found in {keys_folder}/. Exiting.")
            return

        for json_file in json_files:
            player_name = json_file.stem
            with json_file.open() as f:
                data = json.load(f)

            # The player's private key (hex-encoded)
            authority_hex = data.get("player_authority_private_key")
            if not authority_hex:
                print(f"[ERROR] 'player_authority_private_key' not found in {json_file}")
                continue
            authority_bytes = bytes.fromhex(authority_hex)

            # Ensure the seed is exactly 32 bytes
            if len(authority_bytes) != 32:
                print(f"[ERROR] Invalid 'player_authority_private_key' length in {json_file}")
                continue

            # Create Keypair from seed
            try:
                authority_kp = Keypair.from_seed(authority_bytes)
            except ValueError as ve:
                print(f"[ERROR] Invalid seed for Keypair in {json_file}: {ve}")
                continue

            authority_pubkey = authority_kp.pubkey()

            # Determine the reward_pubkey
            reward_pubkey_str = data.get("player_info_acc_address")
            if reward_pubkey_str:
                try:
                    reward_pubkey = Pubkey.from_string(reward_pubkey_str)
                except ValueError:
                    print(f"[ERROR] Invalid 'player_info_acc_address' in {json_file}")
                    reward_pubkey = authority_pubkey  # Fallback
            else:
                reward_pubkey = authority_pubkey  # Fallback

            print(f"\n[INFO] Registering player => {player_name} with pubkey {authority_pubkey}")

            await register_player_pda(
                program=program,
                dapp_pda=dapp_pda,
                fancy_mint=fancy_mint,
                player_name=player_name,
                player_keypair=authority_kp,   # Player's Keypair as 'user'
                reward_pubkey=reward_pubkey,
            )

        print("\nAll players from 'player_keys/' folder have been registered.")

    except Exception as e:
        print(f"[ERROR] Unexpected error => {e}")
        traceback.print_exc()
    finally:
        await client.close()
        print("[INFO] Closed Solana RPC client.")

if __name__ == "__main__":
    asyncio.run(main())

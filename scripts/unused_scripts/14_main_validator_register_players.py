import asyncio
import json
import traceback
import re  # <-- For regex to parse "consumed X of Y compute units"
from pathlib import Path

from anchorpy import Program, Provider, Wallet, Idl, Context
from anchorpy.program.namespace.instruction import AccountMeta
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solders.rpc.responses import RPCError

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed

PROGRAM_ID_STR = "HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut"
RPC_URL = "http://localhost:8899"
IDL_PATH = Path("../target/idl/fancoin.json")
PLAYERS_FOLDER = Path("pubg_keys")

SPL_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
RENT_SYSVAR_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

# Regex to find the "Program XXX consumed NNN of MMM compute units" line.
CU_REGEX = re.compile(r"Program \S+ consumed (\d+) of (\d+) compute units")

def find_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """
    Derive the Associated Token Account (ATA) for a given owner and mint.
    """
    from solders.pubkey import Pubkey as SPubkey
    seeds = [
        bytes(owner),
        bytes(SPubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")),
        bytes(mint),
    ]
    (ata, _) = SPubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
    return ata

async def main():
    # 1) Primary client
    client = AsyncClient(RPC_URL, commitment=Confirmed)

    # 2) The gating validator => used for register_player_pda_by_validator
    validator_wallet = Wallet.local()  # gating validator's keypair
    validator_provider = Provider(client, validator_wallet)

    # 3) Load IDL + Program
    if not IDL_PATH.exists():
        print(f"[ERROR] IDL not found => {IDL_PATH}")
        return

    with IDL_PATH.open("r", encoding="utf-8") as f:
        idl_json = f.read()
    idl = Idl.from_json(idl_json)

    program_id = Pubkey.from_string(PROGRAM_ID_STR)
    validator_program = Program(idl, program_id, validator_provider)

    # 4) Read dapp + minted_mint from disk
    dapp_pda_str = Path("dapp_pda.txt").read_text().strip()
    minted_mint_str = Path("minted_mint_pda.txt").read_text().strip()
    dapp_pda = Pubkey.from_string(dapp_pda_str)
    minted_mint = Pubkey.from_string(minted_mint_str)
    print(f"[INFO] Using dapp_pda={dapp_pda}, minted_mint={minted_mint}")

    # 5) Make sure we have pubg_keys folder
    if not PLAYERS_FOLDER.is_dir():
        print(f"[ERROR] {PLAYERS_FOLDER} does not exist.")
        return

    json_files = list(PLAYERS_FOLDER.glob("*.json"))
    if not json_files:
        print(f"[ERROR] No .json files found in {PLAYERS_FOLDER}/.")
        return

    for file_path in json_files:
        try:
            data = json.loads(file_path.read_text())
            player_name = data.get("player_name")
            if not player_name:
                print(f"[WARN] => {file_path}: missing 'player_name'. Skipping.")
                continue

            privkey_hex = data.get("player_authority_private_key")
            if not privkey_hex:
                print(f"[WARN] => {file_path}: missing player_authority_private_key. Skipping.")
                continue

            authority_address_str = data.get("player_authority_address")
            if not authority_address_str:
                print(f"[WARN] => {file_path}: missing player_authority_address. Skipping.")
                continue

            # Convert hex -> bytes -> Keypair
            try:
                privkey_bytes = bytes.fromhex(privkey_hex)
                if len(privkey_bytes) != 32:
                    print(f"[ERROR] => {file_path}: private key must be 32 bytes. Found {len(privkey_bytes)}.")
                    continue
                player_authority_kp = Keypair.from_seed(privkey_bytes)
            except Exception as e:
                print(f"[ERROR] => {file_path}: cannot parse private key => {e}")
                continue

            derived_pubkey = player_authority_kp.pubkey()
            actual_str = str(derived_pubkey)
            if actual_str != authority_address_str:
                print(f"[WARN] => {file_path}: mismatch in public key:")
                print(f"         JSON says= {authority_address_str}")
                print(f"         derived=   {actual_str}")
                # We can continue anyway or skip. Let's just continue for now.

            print(f"\n[INFO] => Processing {file_path}, name='{player_name}' => authority={derived_pubkey}")

            # Step (A): create_user_ata_if_needed signed by the player's Keypair
            # We'll create a temporary provider with the player's keypair
            player_wallet = Wallet(player_authority_kp)
            player_provider = Provider(client, player_wallet)
            player_program = Program(idl, program_id, player_provider)

            # Derive ATA
            user_ata = find_associated_token_address(derived_pubkey, minted_mint)
            # Also the wallet_pda => seeds=[b"wallet_pda", minted_mint, user_authority]
            (wallet_pda, _) = Pubkey.find_program_address(
                [b"wallet_pda", bytes(minted_mint), bytes(derived_pubkey)],
                program_id
            )
            print(f"   => user_ata={user_ata}, wallet_pda={wallet_pda}")

            # Actually call create_user_ata_if_needed
            try:
                tx_sig_1 = await player_program.rpc["create_user_ata_if_needed"](
                    minted_mint,
                    ctx=Context(
                        accounts={
                            "user": derived_pubkey,  # must match the signer
                            "fancy_mint": minted_mint,
                            "dapp": dapp_pda,
                            "user_ata": user_ata,
                            "wallet_pda": wallet_pda,
                            "token_program": SPL_TOKEN_PROGRAM_ID,
                            "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ID,
                            "system_program": SYS_PROGRAM_ID,
                            "rent": RENT_SYSVAR_ID,
                        },
                        signers=[player_authority_kp],
                    )
                )
                print(f"[SUCCESS create_user_ata_if_needed] => {player_name} => {tx_sig_1}")

                # -----------------------------------------------------------------
                # Fetch transaction logs and parse compute units
                # -----------------------------------------------------------------
                tx_details_1 = await client.get_transaction(tx_sig_1, commitment=Confirmed, encoding='json')
                if tx_details_1.value and tx_details_1.value.transaction.meta:
                    logs = tx_details_1.value.transaction.meta.log_messages or []
                    print("[DEBUG] create_user_ata_if_needed LOGS:")
                    for line in logs:
                        print("   ", line)
                        m = CU_REGEX.search(line)
                        if m:
                            consumed = m.group(1)
                            limit = m.group(2)
                            print(f"   => [CU] consumed {consumed} of {limit} compute units")
                else:
                    print("[DEBUG] No transaction meta/logs found for create_user_ata_if_needed.")

            except Exception as e:
                print(f"[ERROR] => create_user_ata_if_needed => {player_name} => {e}")
                traceback.print_exc()
                continue  # skip

            # Step (B) => gating validator calls register_player_pda_by_validator
            # leftover[0] = wallet_pda
            # fetch dapp.player_count to derive seeds
            dapp_data = await validator_program.account["Dapp"].fetch(dapp_pda)
            current_player_count = dapp_data.player_count

            (derived_player_pda, _) = Pubkey.find_program_address(
                [
                    b"player_pda",
                    bytes(dapp_pda),
                    current_player_count.to_bytes(4, "little"),
                ],
                program_id
            )
            (derived_player_name_pda, _) = Pubkey.find_program_address(
                [
                    b"player_name",
                    bytes(dapp_pda),
                    player_name.encode("utf-8"),
                ],
                program_id
            )

            leftover_accounts = [
                AccountMeta(pubkey=wallet_pda, is_signer=False, is_writable=True),
                AccountMeta(pubkey=user_ata,  is_signer=False, is_writable=True),
            ]
            try:
                tx_sig_2 = await validator_program.rpc["register_player_pda_by_validator"](
                    minted_mint,           # arg #1
                    player_name,           # arg #2
                    derived_pubkey,        # arg #3 => user_authority
                    ctx=Context(
                        accounts={
                            "dapp": dapp_pda,
                            "validator": validator_wallet.public_key,
                            "player_pda": derived_player_pda,
                            "player_name_pda": derived_player_name_pda,
                            "fancy_mint": minted_mint,
                            "system_program": SYS_PROGRAM_ID,
                        },
                        signers=[validator_wallet.payer],
                        remaining_accounts=leftover_accounts,
                    )
                )
                print(f"[SUCCESS register_player_pda_by_validator] => {player_name} => {tx_sig_2} => current_player_count = {current_player_count}")

                # -----------------------------------------------------------------
                # Fetch logs & parse compute units for register_player_pda_by_validator
                # -----------------------------------------------------------------
                tx_details_2 = await client.get_transaction(tx_sig_2, commitment=Confirmed, encoding='json')
                if tx_details_2.value and tx_details_2.value.transaction.meta:
                    logs2 = tx_details_2.value.transaction.meta.log_messages or []
                    print("[DEBUG] register_player_pda_by_validator LOGS:")
                    for line in logs2:
                        print("   ", line)
                        m2 = CU_REGEX.search(line)
                        if m2:
                            consumed2 = m2.group(1)
                            limit2 = m2.group(2)
                            print(f"   => [CU] consumed {consumed2} of {limit2} compute units")
                else:
                    print("[DEBUG] No transaction meta/logs found for register_player_pda_by_validator.")

            except Exception as e:
                print(f"[ERROR] => register_player_pda_by_validator => {player_name} => {e}")
                traceback.print_exc()

        except Exception as e:
            print(f"[ERROR] => {file_path} => {e}")
            traceback.print_exc()

    print("\n[INFO] Done. Closing client.")
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())

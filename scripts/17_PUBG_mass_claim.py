import asyncio
import json
import traceback
import re
from pathlib import Path

from anchorpy import Program, Provider, Wallet, Idl, Context
from anchorpy.program.namespace.instruction import AccountMeta
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solders.rpc.responses import RPCError
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed

##############################################################################
# Config
##############################################################################
PROGRAM_ID_STR = "HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut"
RPC_URL = "http://localhost:8899"
IDL_PATH = Path("../target/idl/fancoin.json")
PLAYERS_FOLDER = Path("pubg_keys")

SPL_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
RENT_SYSVAR_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

##############################################################################
# Regex to find "Program <PID> consumed X of Y compute units"
##############################################################################
CU_REGEX = re.compile(r"Program \S+ consumed (\d+) of (\d+) compute units")

##############################################################################
# Main
##############################################################################
async def main():
    # 1) Create a client
    client = AsyncClient(RPC_URL, commitment=Confirmed)

    # 2) We'll let each player sign individually, so no "validator" wallet here
    #    We'll just load the IDL with a placeholder "local" wallet for convenience:
    local_wallet = Wallet.local()
    placeholder_provider = Provider(client, local_wallet)

    # 3) Load IDL + Program
    if not IDL_PATH.exists():
        print(f"[ERROR] IDL not found => {IDL_PATH}")
        return
    with IDL_PATH.open("r", encoding="utf-8") as f:
        idl_json = f.read()
    idl = Idl.from_json(idl_json)
    program_id = Pubkey.from_string(PROGRAM_ID_STR)

    # We'll have a placeholder Program object (just to parse IDL, etc.).
    # We'll create a new Program object for each player to sign request_claim.
    placeholder_program = Program(idl, program_id, placeholder_provider)

    # 4) Read the game + minted_mint from local .txt
    game_pda_str = Path("game_pda.txt").read_text().strip()
    minted_mint_str = Path("minted_mint_pda.txt").read_text().strip()
    game_pda = Pubkey.from_string(game_pda_str)
    minted_mint = Pubkey.from_string(minted_mint_str)
    print(f"[INFO] Using game_pda={game_pda}, minted_mint={minted_mint}")

    # 5) Check for players folder
    if not PLAYERS_FOLDER.is_dir():
        print(f"[ERROR] {PLAYERS_FOLDER} does not exist.")
        return
    json_files = list(PLAYERS_FOLDER.glob("*.json"))
    if not json_files:
        print(f"[ERROR] No .json files found in {PLAYERS_FOLDER}/.")
        return

    # 6) Iterate over each JSON => parse => request_claim
    for file_path in json_files:
        try:
            data = json.loads(file_path.read_text())

            player_name = data.get("player_name")
            if not player_name:
                print(f"[WARN] => {file_path.name}: missing 'player_name'. Skipping.")
                continue

            privkey_hex = data.get("player_authority_private_key")
            authority_addr_str = data.get("player_authority_address")
            if not privkey_hex or not authority_addr_str:
                print(f"[WARN] => {file_path.name}: missing required key(s). Skipping.")
                continue

            # Convert hex => Keypair
            try:
                privkey_bytes = bytes.fromhex(privkey_hex)
                if len(privkey_bytes) != 32:
                    print(f"[ERROR] => {file_path.name}: private key must be 32 bytes. Found {len(privkey_bytes)}.")
                    continue
                player_kp = Keypair.from_seed(privkey_bytes)
            except Exception as e:
                print(f"[ERROR] => {file_path.name}: cannot parse private key => {e}")
                continue

            # Check derived pubkey vs JSON
            derived_pubkey = player_kp.pubkey()
            derived_pubkey_str = str(derived_pubkey)
            if derived_pubkey_str != authority_addr_str:
                print(f"[WARN] => {file_path.name}: mismatch in public key => JSON={authority_addr_str}, derived={derived_pubkey_str}")

            print(f"\n[INFO] => request_claim for player_name='{player_name}' => authority={derived_pubkey}")

            # 6a) We need a new Program for each player's sign
            player_wallet = Wallet(player_kp)
            player_provider = Provider(client, player_wallet)
            player_program = Program(idl, program_id, player_provider)

            # The request_claim instruction requires:
            #   request_claim(ctx, mint_pubkey, name)
            #   ctx accounts => 
            #     game => seeds=[b"game", minted_mint]
            #     player_name_pda => seeds=[b"player_name", game.key, name.as_bytes()]
            #     player_pda => address= player_name_pda.player_pda
            #     user => Signer
            #     system_program
            #
            # We'll just pass them in "accounts" => 
            # leftover isn't needed.
            # 
            # We'll do the minimal logic to form the accounts:

            # We can derive the player_name_pda as well
            (player_name_pda, _) = Pubkey.find_program_address(
                [b"player_name", bytes(game_pda), player_name.encode("utf-8")],
                program_id
            )

            # We'll load the PlayerNamePda to get its `.player_pda`
            # But that would require a separate fetch or we can do:
            #   "address = player_name_pda.player_pda"
            # The script doesn't know that address unless we fetch on-chain or trust an existing pattern.

            # (A) Fetch on-chain to see if it's there
            try:
                # We can do a small anchorpy approach:
                #    playerNamePda = await player_program.account["PlayerNamePda"].fetch(player_name_pda)
                # Then read -> playerNamePda["player_pda"]
                name_pda_data = await player_program.account["PlayerNamePda"].fetch(player_name_pda)
                actual_player_pda = name_pda_data.player_pda
            except Exception as e:
                print(f"[ERROR] => cannot fetch PlayerNamePda => {player_name_pda}: {e}")
                continue

            # Now we have the real player_pda address
            # We'll do request_claim(minted_mint, player_name).
            try:
                tx_sig = await player_program.rpc["request_claim"](
                    minted_mint,         # arg #1
                    player_name,         # arg #2
                    ctx=Context(
                        accounts={
                            "game": game_pda,
                            "player_name_pda": player_name_pda,
                            "player_pda": actual_player_pda,
                            "user": derived_pubkey,
                            "system_program": SYS_PROGRAM_ID,
                        },
                        signers=[player_kp],
                    )
                )
                print(f"[SUCCESS] => request_claim for {player_name}, Tx={tx_sig}")

                # Fetch logs
                tx_details = await client.get_transaction(tx_sig, commitment=Confirmed, encoding='json')
                if tx_details.value and tx_details.value.transaction.meta:
                    logs = tx_details.value.transaction.meta.log_messages or []
                    print("[DEBUG] request_claim LOGS:")
                    for line in logs:
                        print("   ", line)
                        m = CU_REGEX.search(line)
                        if m:
                            consumed = m.group(1)
                            limit = m.group(2)
                            print(f"   => [CU] consumed {consumed} of {limit} compute units")
                else:
                    print("[DEBUG] No transaction meta/logs found for request_claim.")

            except Exception as e:
                print(f"[ERROR] => request_claim => {player_name}: {e}")
                traceback.print_exc()

        except Exception as e:
            print(f"[ERROR] => {file_path.name}: {e}")
            traceback.print_exc()

    print("\n[INFO] Done. Closing client.")
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())

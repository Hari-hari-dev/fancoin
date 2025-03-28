import asyncio
import json
import traceback
from pathlib import Path

# Anchor / Solana
from anchorpy import Program, Provider, Wallet, Idl, Context
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from solders.system_program import ID as SYS_PROGRAM_ID

# Constants
PROGRAM_ID_STR = "B2K4GmpB86BH5npaZrDsN5kt9TRv48ajeUBbc3tFd2V1"
DAPP_NUMBER = 1  # Adjust if you have a different dapp number
dapp_pda_str = Path("dapp_pda.txt").read_text().strip()
mint_auth_pda_str = Path("mint_auth_pda.txt").read_text().strip()
minted_mint_pda_str = Path("minted_mint_pda.txt").read_text().strip()


dapp_pda = Pubkey.from_string(dapp_pda_str)
mint_auth_pda = Pubkey.from_string(mint_auth_pda_str)
minted_mint_pda = Pubkey.from_string(minted_mint_pda_str)
def load_keypair(path: str) -> Keypair:
    """Load a Keypair from a JSON file containing a 64-byte array."""
    with Path(path).open() as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret[0:64]))

async def punch_in(
    program: Program,
    dapp_pda: Pubkey,
    dapp_number: int,
    validator_pda: Pubkey,
    validator_kp: Keypair
):
    """Punch in as validator for the given dapp."""
    print("\nPunching In as Validator...")
    try:
        tx = await program.rpc["punch_in"](
            minted_mint_pda,
            ctx=Context(
                accounts={
                    "dapp": dapp_pda,
                    "validator_pda": validator_pda,
                    "validator": validator_kp.pubkey(),
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[validator_kp],
            )
        )
        print(f"[SUCCESS] Punched in. Transaction Signature: {tx}")
    except RPCException as e:
        print(f"[ERROR] Punching in: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"[ERROR] Unexpected punch_in error: {e}")
        traceback.print_exc()

async def main():
    try:
        global dapp_pda
        # 1) Connect to local validator (or devnet, etc.)
        client = AsyncClient("https://api.devnet.solana.com", commitment=Confirmed)
        # 2) Use a local wallet as the payer (can also load from file)
        wallet = Wallet.local()
        provider = Provider(client, wallet)

        # 3) Load the IDL
        idl_path = Path("../target/idl/fancoin.json")
        if not idl_path.exists():
            print(f"IDL file not found at {idl_path.resolve()}")
            return

        with idl_path.open() as f:
            idl_json = f.read()

        program_id = Pubkey.from_string(PROGRAM_ID_STR)
        idl = Idl.from_json(idl_json)
        program = Program(idl, program_id, provider)
        print("Program loaded successfully.")

        # 4) Derive the Dapp PDA (which must already exist)
        # dapp_pda, _ = Pubkey.find_program_address(
        #     [b"dapp", DAPP_NUMBER.to_bytes(4, "little")],
        #     program_id
        # )
        print(f"Dapp PDA => {dapp_pda}")

        # 5) Load the validator's keypair

        # 6) Derive the existing ValidatorPDA (already registered)
        # validator_seeds = [
        #     b"validator",
        #     DAPP_NUMBER.to_bytes(4, "little"),
        #     bytes(validator_kp.pubkey()),
        # ]
        # validator_pda, _ = Pubkey.find_program_address(validator_seeds, program_id)
        #DAPP_NUMBER=1
        validator_kp = load_keypair("./val1-keypair.json")  # Adjust path accordingly
        validator_pubkey = validator_kp.pubkey()
        seeds_val = [b"validator", bytes(minted_mint_pda), bytes(validator_kp.pubkey())]
        validator_pda, _ = Pubkey.find_program_address(seeds_val, program.program_id)
        print(f"[DEBUG] Derived validator_pda = {validator_pda}")

        
        

        
        print(f"Validator PDA => {validator_pda}")

        # 7) Punch in
        await punch_in(
            program=program,
            dapp_pda=dapp_pda,
            dapp_number=DAPP_NUMBER,
            validator_pda=validator_pda,
            validator_kp=validator_kp,
        )

    except Exception as exc:
        print(f"[ERROR] Unexpected error in main:\n{exc}")
        traceback.print_exc()
    finally:
        # Close RPC client
        if 'client' in locals():
            await client.close()
        print("Closed Solana RPC client.")

if __name__ == "__main__":
    asyncio.run(main())

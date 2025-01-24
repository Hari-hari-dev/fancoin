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
PROGRAM_ID_STR = "HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut"
GAME_NUMBER = 1  # Adjust if you have a different game number

def load_keypair(path: str) -> Keypair:
    """Load a Keypair from a JSON file containing a 64-byte array."""
    with Path(path).open() as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret[0:64]))

async def punch_in(
    program: Program,
    game_pda: Pubkey,
    game_number: int,
    validator_pda: Pubkey,
    validator_kp: Keypair
):
    """Punch in as validator for the given game."""
    print("\nPunching In as Validator...")
    try:
        tx = await program.rpc["punch_in"](
            game_number,
            ctx=Context(
                accounts={
                    "game": game_pda,
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
        # 1) Connect to local validator (or devnet, etc.)
        client = AsyncClient("http://localhost:8899", commitment=Confirmed)
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

        # 4) Derive the Game PDA (which must already exist)
        game_pda, _ = Pubkey.find_program_address(
            [b"game", GAME_NUMBER.to_bytes(4, "little")],
            program_id
        )
        print(f"Game PDA => {game_pda}")

        # 5) Load the validator's keypair
        validator_kp = load_keypair("./val1-keypair.json")  # Adjust path accordingly

        # 6) Derive the existing ValidatorPDA (already registered)
        validator_seeds = [
            b"validator",
            GAME_NUMBER.to_bytes(4, "little"),
            bytes(validator_kp.pubkey()),
        ]
        validator_pda, _ = Pubkey.find_program_address(validator_seeds, program_id)
        print(f"Validator PDA => {validator_pda}")

        # 7) Punch in
        await punch_in(
            program=program,
            game_pda=game_pda,
            game_number=GAME_NUMBER,
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

from __future__ import annotations
import typing
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solders.instruction import Instruction, AccountMeta
from ..program_id import PROGRAM_ID


import asyncio
from pathlib import Path
import typing
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.rpc.async_client import AsyncClient
from solders.system_program import ID as SYS_PROGRAM_ID
from solders.instruction import Instruction, AccountMeta
from solders.transaction import Transaction
from solders.program_address import find_program_address
import sys

# ===========================
# Configuration and Constants
# ===========================

# Hardcoded Program ID as per your request
PROGRAM_ID = Pubkey.from_string("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut")

# ===========================
# Define InitializeAccounts
# ===========================

class InitializeAccounts(typing.TypedDict):
    dapp: Pubkey
    user: Pubkey

# ===========================
# Define the Initialize Instruction
# ===========================

def initialize(
    accounts: InitializeAccounts,
    program_id: Pubkey = PROGRAM_ID,
    remaining_accounts: typing.Optional[typing.List[AccountMeta]] = None,
) -> Instruction:
    """
    Constructs the 'initialize' instruction for the Solana program.

    Args:
        accounts (InitializeAccounts): A TypedDict containing 'dapp' and 'user' Pubkeys.
        program_id (Pubkey, optional): The Program ID. Defaults to PROGRAM_ID.
        remaining_accounts (List[AccountMeta], optional): Any additional accounts. Defaults to None.

    Returns:
        Instruction: The constructed Solana Instruction.
    """
    keys: list[AccountMeta] = [
        AccountMeta(pubkey=accounts["dapp"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["user"], is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    if remaining_accounts is not None:
        keys += remaining_accounts

    # Instruction identifier (must match the Rust program's identifier for 'initialize')
    identifier = b"\xaf\xafm\x1f\r\x98\x9b\xed"  # Replace with the correct identifier if different
    encoded_args = b""  # Add serialized arguments here if your instruction expects any
    data = identifier + encoded_args

    return Instruction(program_id, data, keys)

# ===========================
# Main Async Function
# ===========================

async def main():
    """
    Main function to execute the 'initialize' instruction.
    """
    # Initialize the RPC client (connect to local validator)
    client = AsyncClient("http://localhost:8899")

    try:
        # ===========================
        # Generate Keypairs
        # ===========================

        # Derive the DApp PDA using seeds [b"dapp"]
        seeds = [b"dapp"]
        dapp_pda, dapp_bump = find_program_address(seeds, PROGRAM_ID)
        print(f"DApp PDA: {dapp_pda}, Bump: {dapp_bump}")

        # Generate a new keypair for 'user'
        user_keypair = Keypair.generate()
        print(f"User Public Key: {user_keypair.pubkey()}")

        # ===========================
        # Airdrop SOL to the User (For Testing)
        # ===========================

        print("\nRequesting airdrop of 1 SOL to the user...")
        airdrop_resp = await client.request_airdrop(user_keypair.pubkey(), 1_000_000_000)  # 1 SOL in lamports
        await client.confirm_transaction(airdrop_resp.value)
        print("Airdrop to user successful.")

        # ===========================
        # Define Accounts for the Instruction
        # ===========================

        accounts = InitializeAccounts(
            dapp=dapp_pda,
            user=user_keypair.pubkey(),
        )

        # ===========================
        # Create the Initialize Instruction
        # ===========================

        instr = initialize(accounts)

        # ===========================
        # Construct and Send the Transaction
        # ===========================

        # Create the transaction and add the instruction
        txn = Transaction().add(instr)

        # Sign the transaction with the user's keypair (since user is a signer)
        signed_tx = txn.sign([user_keypair])

        # Send the transaction
        print("\nSending the transaction...")
        send_resp = await client.send_transaction(signed_tx)
        print(f"Transaction sent. Signature: {send_resp}")

        # ===========================
        # Confirm the Transaction
        # ===========================

        print("Confirming the transaction...")
        confirm_resp = await client.confirm_transaction(send_resp, commitment="confirmed")
        if confirm_resp.value:
            print("Transaction confirmed successfully.")
        else:
            print("Transaction confirmation failed.")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Close the RPC client connection
        await client.close()
        print("Closed Solana RPC client.")

# ===========================
# Execute the Main Function
# ===========================

if __name__ == "__main__":
    asyncio.run(main())
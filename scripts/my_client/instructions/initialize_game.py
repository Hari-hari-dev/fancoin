from __future__ import annotations
import typing
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solders.instruction import Instruction, AccountMeta
import borsh_construct as borsh
from ..program_id import PROGRAM_ID


class InitializeGameArgs(typing.TypedDict):
    game_number: int
    description: str


layout = borsh.CStruct("game_number" / borsh.U32, "description" / borsh.String)


class InitializeGameAccounts(typing.TypedDict):
    game: Pubkey
    user: Pubkey


def initialize_game(
    args: InitializeGameArgs,
    accounts: InitializeGameAccounts,
    program_id: Pubkey = PROGRAM_ID,
    remaining_accounts: typing.Optional[typing.List[AccountMeta]] = None,
) -> Instruction:
    keys: list[AccountMeta] = [
        AccountMeta(pubkey=accounts["game"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["user"], is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    if remaining_accounts is not None:
        keys += remaining_accounts
    identifier = b",>f\xf7~\xd0\x82\xd7"
    encoded_args = layout.build(
        {
            "game_number": args["game_number"],
            "description": args["description"],
        }
    )
    data = identifier + encoded_args
    return Instruction(program_id, data, keys)

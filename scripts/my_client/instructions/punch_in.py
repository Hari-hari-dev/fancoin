from __future__ import annotations
import typing
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
import borsh_construct as borsh
from ..program_id import PROGRAM_ID


class PunchInArgs(typing.TypedDict):
    game_number: int


layout = borsh.CStruct("game_number" / borsh.U32)


class PunchInAccounts(typing.TypedDict):
    game: Pubkey
    validator: Pubkey


def punch_in(
    args: PunchInArgs,
    accounts: PunchInAccounts,
    program_id: Pubkey = PROGRAM_ID,
    remaining_accounts: typing.Optional[typing.List[AccountMeta]] = None,
) -> Instruction:
    keys: list[AccountMeta] = [
        AccountMeta(pubkey=accounts["game"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["validator"], is_signer=True, is_writable=False),
    ]
    if remaining_accounts is not None:
        keys += remaining_accounts
    identifier = b"\xbd\xa4\x8d\x9c\xacn\xed\xd1"
    encoded_args = layout.build(
        {
            "game_number": args["game_number"],
        }
    )
    data = identifier + encoded_args
    return Instruction(program_id, data, keys)

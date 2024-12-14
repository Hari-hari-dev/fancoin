from __future__ import annotations
import typing
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
import borsh_construct as borsh
from .. import types
from ..program_id import PROGRAM_ID


class UpdateGameStatusArgs(typing.TypedDict):
    game_number: int
    new_status: types.game_status.GameStatusKind
    description: str


layout = borsh.CStruct(
    "game_number" / borsh.U32,
    "new_status" / types.game_status.layout,
    "description" / borsh.String,
)


class UpdateGameStatusAccounts(typing.TypedDict):
    game: Pubkey
    dapp: Pubkey
    signer: Pubkey


def update_game_status(
    args: UpdateGameStatusArgs,
    accounts: UpdateGameStatusAccounts,
    program_id: Pubkey = PROGRAM_ID,
    remaining_accounts: typing.Optional[typing.List[AccountMeta]] = None,
) -> Instruction:
    keys: list[AccountMeta] = [
        AccountMeta(pubkey=accounts["game"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["dapp"], is_signer=False, is_writable=False),
        AccountMeta(pubkey=accounts["signer"], is_signer=True, is_writable=True),
    ]
    if remaining_accounts is not None:
        keys += remaining_accounts
    identifier = b"\x1f\xaf\x7f\xf23\xf4\xac\xb9"
    encoded_args = layout.build(
        {
            "game_number": args["game_number"],
            "new_status": args["new_status"].to_encodable(),
            "description": args["description"],
        }
    )
    data = identifier + encoded_args
    return Instruction(program_id, data, keys)

from __future__ import annotations
import typing
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solders.instruction import Instruction, AccountMeta
from anchorpy.borsh_extension import BorshPubkey
import borsh_construct as borsh
from ..program_id import PROGRAM_ID


class RegisterPlayerArgs(typing.TypedDict):
    game_number: int
    name: str
    reward_address: Pubkey


layout = borsh.CStruct(
    "game_number" / borsh.U32, "name" / borsh.String, "reward_address" / BorshPubkey
)


class RegisterPlayerAccounts(typing.TypedDict):
    game: Pubkey
    player: Pubkey
    user: Pubkey


def register_player(
    args: RegisterPlayerArgs,
    accounts: RegisterPlayerAccounts,
    program_id: Pubkey = PROGRAM_ID,
    remaining_accounts: typing.Optional[typing.List[AccountMeta]] = None,
) -> Instruction:
    keys: list[AccountMeta] = [
        AccountMeta(pubkey=accounts["game"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["player"], is_signer=True, is_writable=True),
        AccountMeta(pubkey=accounts["user"], is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    if remaining_accounts is not None:
        keys += remaining_accounts
    identifier = b"\xf2\x92\xc2\xea\xea\x91\xe4*"
    encoded_args = layout.build(
        {
            "game_number": args["game_number"],
            "name": args["name"],
            "reward_address": args["reward_address"],
        }
    )
    data = identifier + encoded_args
    return Instruction(program_id, data, keys)

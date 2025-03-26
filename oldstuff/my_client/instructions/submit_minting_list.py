from __future__ import annotations
import typing
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from construct import Construct
import borsh_construct as borsh
from ..program_id import PROGRAM_ID


class SubmitMintingListArgs(typing.TypedDict):
    game_number: int
    player_names: list[str]


layout = borsh.CStruct(
    "game_number" / borsh.U32,
    "player_names" / borsh.Vec(typing.cast(Construct, borsh.String)),
)


class SubmitMintingListAccounts(typing.TypedDict):
    game: Pubkey
    validator: Pubkey


def submit_minting_list(
    args: SubmitMintingListArgs,
    accounts: SubmitMintingListAccounts,
    program_id: Pubkey = PROGRAM_ID,
    remaining_accounts: typing.Optional[typing.List[AccountMeta]] = None,
) -> Instruction:
    keys: list[AccountMeta] = [
        AccountMeta(pubkey=accounts["game"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["validator"], is_signer=True, is_writable=False),
    ]
    if remaining_accounts is not None:
        keys += remaining_accounts
    identifier = b"T[S\t\n\x81i$"
    encoded_args = layout.build(
        {
            "game_number": args["game_number"],
            "player_names": args["player_names"],
        }
    )
    data = identifier + encoded_args
    return Instruction(program_id, data, keys)

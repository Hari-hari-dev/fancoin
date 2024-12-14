import typing
from dataclasses import dataclass
from construct import Construct
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
import borsh_construct as borsh
from anchorpy.coder.accounts import ACCOUNT_DISCRIMINATOR_SIZE
from anchorpy.error import AccountInvalidDiscriminator
from anchorpy.utils.rpc import get_multiple_accounts
from ..program_id import PROGRAM_ID
from .. import types


class GameJSON(typing.TypedDict):
    game_number: int
    status: types.game_status.GameStatusJSON
    description: str
    validators: list[types.validator.ValidatorJSON]
    shards: list[types.shard.ShardJSON]
    token_balances: list[types.token_balance.TokenBalanceJSON]
    total_token_supply: int
    last_seed: typing.Optional[int]
    last_punch_in_time: typing.Optional[int]
    minting_agreements: list[types.minting_agreement.MintingAgreementJSON]


@dataclass
class Game:
    discriminator: typing.ClassVar = b"\x1bZ\xa6}Jdy\x12"
    layout: typing.ClassVar = borsh.CStruct(
        "game_number" / borsh.U32,
        "status" / types.game_status.layout,
        "description" / borsh.String,
        "validators"
        / borsh.Vec(typing.cast(Construct, types.validator.Validator.layout)),
        "shards" / borsh.Vec(typing.cast(Construct, types.shard.Shard.layout)),
        "token_balances"
        / borsh.Vec(typing.cast(Construct, types.token_balance.TokenBalance.layout)),
        "total_token_supply" / borsh.U64,
        "last_seed" / borsh.Option(borsh.U64),
        "last_punch_in_time" / borsh.Option(borsh.I64),
        "minting_agreements"
        / borsh.Vec(
            typing.cast(Construct, types.minting_agreement.MintingAgreement.layout)
        ),
    )
    game_number: int
    status: types.game_status.GameStatusKind
    description: str
    validators: list[types.validator.Validator]
    shards: list[types.shard.Shard]
    token_balances: list[types.token_balance.TokenBalance]
    total_token_supply: int
    last_seed: typing.Optional[int]
    last_punch_in_time: typing.Optional[int]
    minting_agreements: list[types.minting_agreement.MintingAgreement]

    @classmethod
    async def fetch(
        cls,
        conn: AsyncClient,
        address: Pubkey,
        commitment: typing.Optional[Commitment] = None,
        program_id: Pubkey = PROGRAM_ID,
    ) -> typing.Optional["Game"]:
        resp = await conn.get_account_info(address, commitment=commitment)
        info = resp.value
        if info is None:
            return None
        if info.owner != program_id:
            raise ValueError("Account does not belong to this program")
        bytes_data = info.data
        return cls.decode(bytes_data)

    @classmethod
    async def fetch_multiple(
        cls,
        conn: AsyncClient,
        addresses: list[Pubkey],
        commitment: typing.Optional[Commitment] = None,
        program_id: Pubkey = PROGRAM_ID,
    ) -> typing.List[typing.Optional["Game"]]:
        infos = await get_multiple_accounts(conn, addresses, commitment=commitment)
        res: typing.List[typing.Optional["Game"]] = []
        for info in infos:
            if info is None:
                res.append(None)
                continue
            if info.account.owner != program_id:
                raise ValueError("Account does not belong to this program")
            res.append(cls.decode(info.account.data))
        return res

    @classmethod
    def decode(cls, data: bytes) -> "Game":
        if data[:ACCOUNT_DISCRIMINATOR_SIZE] != cls.discriminator:
            raise AccountInvalidDiscriminator(
                "The discriminator for this account is invalid"
            )
        dec = Game.layout.parse(data[ACCOUNT_DISCRIMINATOR_SIZE:])
        return cls(
            game_number=dec.game_number,
            status=types.game_status.from_decoded(dec.status),
            description=dec.description,
            validators=list(
                map(
                    lambda item: types.validator.Validator.from_decoded(item),
                    dec.validators,
                )
            ),
            shards=list(
                map(lambda item: types.shard.Shard.from_decoded(item), dec.shards)
            ),
            token_balances=list(
                map(
                    lambda item: types.token_balance.TokenBalance.from_decoded(item),
                    dec.token_balances,
                )
            ),
            total_token_supply=dec.total_token_supply,
            last_seed=dec.last_seed,
            last_punch_in_time=dec.last_punch_in_time,
            minting_agreements=list(
                map(
                    lambda item: types.minting_agreement.MintingAgreement.from_decoded(
                        item
                    ),
                    dec.minting_agreements,
                )
            ),
        )

    def to_json(self) -> GameJSON:
        return {
            "game_number": self.game_number,
            "status": self.status.to_json(),
            "description": self.description,
            "validators": list(map(lambda item: item.to_json(), self.validators)),
            "shards": list(map(lambda item: item.to_json(), self.shards)),
            "token_balances": list(
                map(lambda item: item.to_json(), self.token_balances)
            ),
            "total_token_supply": self.total_token_supply,
            "last_seed": self.last_seed,
            "last_punch_in_time": self.last_punch_in_time,
            "minting_agreements": list(
                map(lambda item: item.to_json(), self.minting_agreements)
            ),
        }

    @classmethod
    def from_json(cls, obj: GameJSON) -> "Game":
        return cls(
            game_number=obj["game_number"],
            status=types.game_status.from_json(obj["status"]),
            description=obj["description"],
            validators=list(
                map(
                    lambda item: types.validator.Validator.from_json(item),
                    obj["validators"],
                )
            ),
            shards=list(
                map(lambda item: types.shard.Shard.from_json(item), obj["shards"])
            ),
            token_balances=list(
                map(
                    lambda item: types.token_balance.TokenBalance.from_json(item),
                    obj["token_balances"],
                )
            ),
            total_token_supply=obj["total_token_supply"],
            last_seed=obj["last_seed"],
            last_punch_in_time=obj["last_punch_in_time"],
            minting_agreements=list(
                map(
                    lambda item: types.minting_agreement.MintingAgreement.from_json(
                        item
                    ),
                    obj["minting_agreements"],
                )
            ),
        )

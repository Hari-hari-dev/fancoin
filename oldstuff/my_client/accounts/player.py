import typing
from dataclasses import dataclass
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
import borsh_construct as borsh
from anchorpy.coder.accounts import ACCOUNT_DISCRIMINATOR_SIZE
from anchorpy.error import AccountInvalidDiscriminator
from anchorpy.utils.rpc import get_multiple_accounts
from anchorpy.borsh_extension import BorshPubkey
from ..program_id import PROGRAM_ID


class PlayerJSON(typing.TypedDict):
    name: str
    address: str
    reward_address: str
    last_minted: typing.Optional[int]


@dataclass
class Player:
    discriminator: typing.ClassVar = b"\xcd\xdep\x07\xa5\x9b\xce\xda"
    layout: typing.ClassVar = borsh.CStruct(
        "name" / borsh.String,
        "address" / BorshPubkey,
        "reward_address" / BorshPubkey,
        "last_minted" / borsh.Option(borsh.I64),
    )
    name: str
    address: Pubkey
    reward_address: Pubkey
    last_minted: typing.Optional[int]

    @classmethod
    async def fetch(
        cls,
        conn: AsyncClient,
        address: Pubkey,
        commitment: typing.Optional[Commitment] = None,
        program_id: Pubkey = PROGRAM_ID,
    ) -> typing.Optional["Player"]:
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
    ) -> typing.List[typing.Optional["Player"]]:
        infos = await get_multiple_accounts(conn, addresses, commitment=commitment)
        res: typing.List[typing.Optional["Player"]] = []
        for info in infos:
            if info is None:
                res.append(None)
                continue
            if info.account.owner != program_id:
                raise ValueError("Account does not belong to this program")
            res.append(cls.decode(info.account.data))
        return res

    @classmethod
    def decode(cls, data: bytes) -> "Player":
        if data[:ACCOUNT_DISCRIMINATOR_SIZE] != cls.discriminator:
            raise AccountInvalidDiscriminator(
                "The discriminator for this account is invalid"
            )
        dec = Player.layout.parse(data[ACCOUNT_DISCRIMINATOR_SIZE:])
        return cls(
            name=dec.name,
            address=dec.address,
            reward_address=dec.reward_address,
            last_minted=dec.last_minted,
        )

    def to_json(self) -> PlayerJSON:
        return {
            "name": self.name,
            "address": str(self.address),
            "reward_address": str(self.reward_address),
            "last_minted": self.last_minted,
        }

    @classmethod
    def from_json(cls, obj: PlayerJSON) -> "Player":
        return cls(
            name=obj["name"],
            address=Pubkey.from_string(obj["address"]),
            reward_address=Pubkey.from_string(obj["reward_address"]),
            last_minted=obj["last_minted"],
        )

from __future__ import annotations
import typing
from dataclasses import dataclass
from construct import Container
from solders.pubkey import Pubkey
from anchorpy.borsh_extension import BorshPubkey
import borsh_construct as borsh


class TokenBalanceJSON(typing.TypedDict):
    address: str
    balance: int


@dataclass
class TokenBalance:
    layout: typing.ClassVar = borsh.CStruct(
        "address" / BorshPubkey, "balance" / borsh.U64
    )
    address: Pubkey
    balance: int

    @classmethod
    def from_decoded(cls, obj: Container) -> "TokenBalance":
        return cls(address=obj.address, balance=obj.balance)

    def to_encodable(self) -> dict[str, typing.Any]:
        return {"address": self.address, "balance": self.balance}

    def to_json(self) -> TokenBalanceJSON:
        return {"address": str(self.address), "balance": self.balance}

    @classmethod
    def from_json(cls, obj: TokenBalanceJSON) -> "TokenBalance":
        return cls(address=Pubkey.from_string(obj["address"]), balance=obj["balance"])

from __future__ import annotations
import typing
from dataclasses import dataclass
from construct import Container
from solders.pubkey import Pubkey
from anchorpy.borsh_extension import BorshPubkey
import borsh_construct as borsh


class ValidatorJSON(typing.TypedDict):
    address: str
    last_activity: int


@dataclass
class Validator:
    layout: typing.ClassVar = borsh.CStruct(
        "address" / BorshPubkey, "last_activity" / borsh.I64
    )
    address: Pubkey
    last_activity: int

    @classmethod
    def from_decoded(cls, obj: Container) -> "Validator":
        return cls(address=obj.address, last_activity=obj.last_activity)

    def to_encodable(self) -> dict[str, typing.Any]:
        return {"address": self.address, "last_activity": self.last_activity}

    def to_json(self) -> ValidatorJSON:
        return {"address": str(self.address), "last_activity": self.last_activity}

    @classmethod
    def from_json(cls, obj: ValidatorJSON) -> "Validator":
        return cls(
            address=Pubkey.from_string(obj["address"]),
            last_activity=obj["last_activity"],
        )

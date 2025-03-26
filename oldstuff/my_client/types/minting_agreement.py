from __future__ import annotations
import typing
from dataclasses import dataclass
from construct import Container, Construct
from solders.pubkey import Pubkey
from anchorpy.borsh_extension import BorshPubkey
import borsh_construct as borsh


class MintingAgreementJSON(typing.TypedDict):
    player_name: str
    validators: list[str]


@dataclass
class MintingAgreement:
    layout: typing.ClassVar = borsh.CStruct(
        "player_name" / borsh.String,
        "validators" / borsh.Vec(typing.cast(Construct, BorshPubkey)),
    )
    player_name: str
    validators: list[Pubkey]

    @classmethod
    def from_decoded(cls, obj: Container) -> "MintingAgreement":
        return cls(player_name=obj.player_name, validators=obj.validators)

    def to_encodable(self) -> dict[str, typing.Any]:
        return {"player_name": self.player_name, "validators": self.validators}

    def to_json(self) -> MintingAgreementJSON:
        return {
            "player_name": self.player_name,
            "validators": list(map(lambda item: str(item), self.validators)),
        }

    @classmethod
    def from_json(cls, obj: MintingAgreementJSON) -> "MintingAgreement":
        return cls(
            player_name=obj["player_name"],
            validators=list(
                map(lambda item: Pubkey.from_string(item), obj["validators"])
            ),
        )

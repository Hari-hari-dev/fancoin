from __future__ import annotations
import typing
from dataclasses import dataclass
from construct import Container, Construct
from solders.pubkey import Pubkey
from anchorpy.borsh_extension import BorshPubkey
import borsh_construct as borsh


class ShardJSON(typing.TypedDict):
    players: list[str]


@dataclass
class Shard:
    layout: typing.ClassVar = borsh.CStruct(
        "players" / borsh.Vec(typing.cast(Construct, BorshPubkey))
    )
    players: list[Pubkey]

    @classmethod
    def from_decoded(cls, obj: Container) -> "Shard":
        return cls(players=obj.players)

    def to_encodable(self) -> dict[str, typing.Any]:
        return {"players": self.players}

    def to_json(self) -> ShardJSON:
        return {"players": list(map(lambda item: str(item), self.players))}

    @classmethod
    def from_json(cls, obj: ShardJSON) -> "Shard":
        return cls(
            players=list(map(lambda item: Pubkey.from_string(item), obj["players"]))
        )

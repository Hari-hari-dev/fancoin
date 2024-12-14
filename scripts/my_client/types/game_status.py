from __future__ import annotations
import typing
from dataclasses import dataclass
from anchorpy.borsh_extension import EnumForCodegen
import borsh_construct as borsh


class ProbationaryJSON(typing.TypedDict):
    kind: typing.Literal["Probationary"]


class WhitelistedJSON(typing.TypedDict):
    kind: typing.Literal["Whitelisted"]


class BlacklistedJSON(typing.TypedDict):
    kind: typing.Literal["Blacklisted"]


@dataclass
class Probationary:
    discriminator: typing.ClassVar = 0
    kind: typing.ClassVar = "Probationary"

    @classmethod
    def to_json(cls) -> ProbationaryJSON:
        return ProbationaryJSON(
            kind="Probationary",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "Probationary": {},
        }


@dataclass
class Whitelisted:
    discriminator: typing.ClassVar = 1
    kind: typing.ClassVar = "Whitelisted"

    @classmethod
    def to_json(cls) -> WhitelistedJSON:
        return WhitelistedJSON(
            kind="Whitelisted",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "Whitelisted": {},
        }


@dataclass
class Blacklisted:
    discriminator: typing.ClassVar = 2
    kind: typing.ClassVar = "Blacklisted"

    @classmethod
    def to_json(cls) -> BlacklistedJSON:
        return BlacklistedJSON(
            kind="Blacklisted",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "Blacklisted": {},
        }


GameStatusKind = typing.Union[Probationary, Whitelisted, Blacklisted]
GameStatusJSON = typing.Union[ProbationaryJSON, WhitelistedJSON, BlacklistedJSON]


def from_decoded(obj: dict) -> GameStatusKind:
    if not isinstance(obj, dict):
        raise ValueError("Invalid enum object")
    if "Probationary" in obj:
        return Probationary()
    if "Whitelisted" in obj:
        return Whitelisted()
    if "Blacklisted" in obj:
        return Blacklisted()
    raise ValueError("Invalid enum object")


def from_json(obj: GameStatusJSON) -> GameStatusKind:
    if obj["kind"] == "Probationary":
        return Probationary()
    if obj["kind"] == "Whitelisted":
        return Whitelisted()
    if obj["kind"] == "Blacklisted":
        return Blacklisted()
    kind = obj["kind"]
    raise ValueError(f"Unrecognized enum kind: {kind}")


layout = EnumForCodegen(
    "Probationary" / borsh.CStruct(),
    "Whitelisted" / borsh.CStruct(),
    "Blacklisted" / borsh.CStruct(),
)

from __future__ import annotations
import typing
from dataclasses import dataclass
from anchorpy.borsh_extension import EnumForCodegen
import borsh_construct as borsh


class UnauthorizedJSON(typing.TypedDict):
    kind: typing.Literal["Unauthorized"]


class NotInPunchInPeriodJSON(typing.TypedDict):
    kind: typing.Literal["NotInPunchInPeriod"]


class NotInMintPeriodJSON(typing.TypedDict):
    kind: typing.Literal["NotInMintPeriod"]


class InsufficientStakeJSON(typing.TypedDict):
    kind: typing.Literal["InsufficientStake"]


class PlayerNameExistsJSON(typing.TypedDict):
    kind: typing.Literal["PlayerNameExists"]


class ValidatorNotRegisteredJSON(typing.TypedDict):
    kind: typing.Literal["ValidatorNotRegistered"]


class HashConversionErrorJSON(typing.TypedDict):
    kind: typing.Literal["HashConversionError"]


class InvalidTimestampJSON(typing.TypedDict):
    kind: typing.Literal["InvalidTimestamp"]


class GameNumberMismatchJSON(typing.TypedDict):
    kind: typing.Literal["GameNumberMismatch"]


class GameStatusAlreadySetJSON(typing.TypedDict):
    kind: typing.Literal["GameStatusAlreadySet"]


class GameIsBlacklistedJSON(typing.TypedDict):
    kind: typing.Literal["GameIsBlacklisted"]


class GameNotWhitelistedJSON(typing.TypedDict):
    kind: typing.Literal["GameNotWhitelisted"]


@dataclass
class Unauthorized:
    discriminator: typing.ClassVar = 0
    kind: typing.ClassVar = "Unauthorized"

    @classmethod
    def to_json(cls) -> UnauthorizedJSON:
        return UnauthorizedJSON(
            kind="Unauthorized",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "Unauthorized": {},
        }


@dataclass
class NotInPunchInPeriod:
    discriminator: typing.ClassVar = 1
    kind: typing.ClassVar = "NotInPunchInPeriod"

    @classmethod
    def to_json(cls) -> NotInPunchInPeriodJSON:
        return NotInPunchInPeriodJSON(
            kind="NotInPunchInPeriod",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "NotInPunchInPeriod": {},
        }


@dataclass
class NotInMintPeriod:
    discriminator: typing.ClassVar = 2
    kind: typing.ClassVar = "NotInMintPeriod"

    @classmethod
    def to_json(cls) -> NotInMintPeriodJSON:
        return NotInMintPeriodJSON(
            kind="NotInMintPeriod",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "NotInMintPeriod": {},
        }


@dataclass
class InsufficientStake:
    discriminator: typing.ClassVar = 3
    kind: typing.ClassVar = "InsufficientStake"

    @classmethod
    def to_json(cls) -> InsufficientStakeJSON:
        return InsufficientStakeJSON(
            kind="InsufficientStake",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "InsufficientStake": {},
        }


@dataclass
class PlayerNameExists:
    discriminator: typing.ClassVar = 4
    kind: typing.ClassVar = "PlayerNameExists"

    @classmethod
    def to_json(cls) -> PlayerNameExistsJSON:
        return PlayerNameExistsJSON(
            kind="PlayerNameExists",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "PlayerNameExists": {},
        }


@dataclass
class ValidatorNotRegistered:
    discriminator: typing.ClassVar = 5
    kind: typing.ClassVar = "ValidatorNotRegistered"

    @classmethod
    def to_json(cls) -> ValidatorNotRegisteredJSON:
        return ValidatorNotRegisteredJSON(
            kind="ValidatorNotRegistered",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "ValidatorNotRegistered": {},
        }


@dataclass
class HashConversionError:
    discriminator: typing.ClassVar = 6
    kind: typing.ClassVar = "HashConversionError"

    @classmethod
    def to_json(cls) -> HashConversionErrorJSON:
        return HashConversionErrorJSON(
            kind="HashConversionError",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "HashConversionError": {},
        }


@dataclass
class InvalidTimestamp:
    discriminator: typing.ClassVar = 7
    kind: typing.ClassVar = "InvalidTimestamp"

    @classmethod
    def to_json(cls) -> InvalidTimestampJSON:
        return InvalidTimestampJSON(
            kind="InvalidTimestamp",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "InvalidTimestamp": {},
        }


@dataclass
class GameNumberMismatch:
    discriminator: typing.ClassVar = 8
    kind: typing.ClassVar = "GameNumberMismatch"

    @classmethod
    def to_json(cls) -> GameNumberMismatchJSON:
        return GameNumberMismatchJSON(
            kind="GameNumberMismatch",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "GameNumberMismatch": {},
        }


@dataclass
class GameStatusAlreadySet:
    discriminator: typing.ClassVar = 9
    kind: typing.ClassVar = "GameStatusAlreadySet"

    @classmethod
    def to_json(cls) -> GameStatusAlreadySetJSON:
        return GameStatusAlreadySetJSON(
            kind="GameStatusAlreadySet",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "GameStatusAlreadySet": {},
        }


@dataclass
class GameIsBlacklisted:
    discriminator: typing.ClassVar = 10
    kind: typing.ClassVar = "GameIsBlacklisted"

    @classmethod
    def to_json(cls) -> GameIsBlacklistedJSON:
        return GameIsBlacklistedJSON(
            kind="GameIsBlacklisted",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "GameIsBlacklisted": {},
        }


@dataclass
class GameNotWhitelisted:
    discriminator: typing.ClassVar = 11
    kind: typing.ClassVar = "GameNotWhitelisted"

    @classmethod
    def to_json(cls) -> GameNotWhitelistedJSON:
        return GameNotWhitelistedJSON(
            kind="GameNotWhitelisted",
        )

    @classmethod
    def to_encodable(cls) -> dict:
        return {
            "GameNotWhitelisted": {},
        }


ErrorCodeKind = typing.Union[
    Unauthorized,
    NotInPunchInPeriod,
    NotInMintPeriod,
    InsufficientStake,
    PlayerNameExists,
    ValidatorNotRegistered,
    HashConversionError,
    InvalidTimestamp,
    GameNumberMismatch,
    GameStatusAlreadySet,
    GameIsBlacklisted,
    GameNotWhitelisted,
]
ErrorCodeJSON = typing.Union[
    UnauthorizedJSON,
    NotInPunchInPeriodJSON,
    NotInMintPeriodJSON,
    InsufficientStakeJSON,
    PlayerNameExistsJSON,
    ValidatorNotRegisteredJSON,
    HashConversionErrorJSON,
    InvalidTimestampJSON,
    GameNumberMismatchJSON,
    GameStatusAlreadySetJSON,
    GameIsBlacklistedJSON,
    GameNotWhitelistedJSON,
]


def from_decoded(obj: dict) -> ErrorCodeKind:
    if not isinstance(obj, dict):
        raise ValueError("Invalid enum object")
    if "Unauthorized" in obj:
        return Unauthorized()
    if "NotInPunchInPeriod" in obj:
        return NotInPunchInPeriod()
    if "NotInMintPeriod" in obj:
        return NotInMintPeriod()
    if "InsufficientStake" in obj:
        return InsufficientStake()
    if "PlayerNameExists" in obj:
        return PlayerNameExists()
    if "ValidatorNotRegistered" in obj:
        return ValidatorNotRegistered()
    if "HashConversionError" in obj:
        return HashConversionError()
    if "InvalidTimestamp" in obj:
        return InvalidTimestamp()
    if "GameNumberMismatch" in obj:
        return GameNumberMismatch()
    if "GameStatusAlreadySet" in obj:
        return GameStatusAlreadySet()
    if "GameIsBlacklisted" in obj:
        return GameIsBlacklisted()
    if "GameNotWhitelisted" in obj:
        return GameNotWhitelisted()
    raise ValueError("Invalid enum object")


def from_json(obj: ErrorCodeJSON) -> ErrorCodeKind:
    if obj["kind"] == "Unauthorized":
        return Unauthorized()
    if obj["kind"] == "NotInPunchInPeriod":
        return NotInPunchInPeriod()
    if obj["kind"] == "NotInMintPeriod":
        return NotInMintPeriod()
    if obj["kind"] == "InsufficientStake":
        return InsufficientStake()
    if obj["kind"] == "PlayerNameExists":
        return PlayerNameExists()
    if obj["kind"] == "ValidatorNotRegistered":
        return ValidatorNotRegistered()
    if obj["kind"] == "HashConversionError":
        return HashConversionError()
    if obj["kind"] == "InvalidTimestamp":
        return InvalidTimestamp()
    if obj["kind"] == "GameNumberMismatch":
        return GameNumberMismatch()
    if obj["kind"] == "GameStatusAlreadySet":
        return GameStatusAlreadySet()
    if obj["kind"] == "GameIsBlacklisted":
        return GameIsBlacklisted()
    if obj["kind"] == "GameNotWhitelisted":
        return GameNotWhitelisted()
    kind = obj["kind"]
    raise ValueError(f"Unrecognized enum kind: {kind}")


layout = EnumForCodegen(
    "Unauthorized" / borsh.CStruct(),
    "NotInPunchInPeriod" / borsh.CStruct(),
    "NotInMintPeriod" / borsh.CStruct(),
    "InsufficientStake" / borsh.CStruct(),
    "PlayerNameExists" / borsh.CStruct(),
    "ValidatorNotRegistered" / borsh.CStruct(),
    "HashConversionError" / borsh.CStruct(),
    "InvalidTimestamp" / borsh.CStruct(),
    "GameNumberMismatch" / borsh.CStruct(),
    "GameStatusAlreadySet" / borsh.CStruct(),
    "GameIsBlacklisted" / borsh.CStruct(),
    "GameNotWhitelisted" / borsh.CStruct(),
)

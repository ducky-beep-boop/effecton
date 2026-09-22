"""Cli: declare a command's arguments as an annotated class, then parse argv
through Schema and run the handler as an effect.

An Args subclass is a frozen keyword-only dataclass: annotations are the
decoded types and Annotated metadata (Option, Argument) describes the
command line. Each field gets a text codec, a Schema whose wire side is
str, so the arguments decode like any other struct and every problem is
reported together as one usage error. Commands nest with
with_subcommands, and run(command) is one Effect that reads argv through
E.Process, prints help and the version, and fails with a UsageError that
exits with status 2 under run_main.
"""

import dataclasses
import typing
from dataclasses import MISSING, dataclass
from datetime import date, datetime
from types import NoneType, UnionType
from typing import Any, ClassVar, TypeAliasType, dataclass_transform, final

from effecton.std import schema as S
from effecton.std.path import Path


@final
@dataclass(frozen=True)
class Option:
    """Annotated metadata for an option field: --name VALUE, or a flag for bool."""

    help: str = ""
    name: str | None = None
    short: str | None = None
    metavar: str | None = None
    schema: S.Schema[Any, str] | None = None


@final
@dataclass(frozen=True)
class Argument:
    """Annotated metadata for a positional argument field."""

    help: str = ""
    name: str | None = None
    metavar: str | None = None
    schema: S.Schema[Any, str] | None = None


@dataclass(frozen=True)
class _Param:
    """One field of an Args class as the command line sees it."""

    field: str
    key: str  # display name and wire key: "--package" or "PACKAGE"
    short: str | None
    help: str
    metavar: str | None  # None for a flag
    codec: S.Schema[Any, Any]
    positional: bool
    flag: bool
    repeated: bool
    required: bool
    default_text: str | None


@dataclass_transform(frozen_default=True, kw_only_default=True)
class Args:
    """Subclass to declare a command's arguments: annotations are the decoded types.

    Every subclass becomes a frozen, keyword-only dataclass. A field is an
    option unless its Annotated metadata is Argument; both carry help text,
    names and an optional explicit text codec (a Schema whose wire side is
    str). str, int, float, E.Path, datetime, date and Literal[str...] infer
    theirs; bool is a flag; T | None is optional; tuple[T, ...] repeats.
    """

    __cli_params__: ClassVar[tuple[_Param, ...]]
    __cli_schema__: ClassVar[S.Schema[Any, dict[str, object]]]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        dataclass(frozen=True, kw_only=True)(cls)
        cls.__cli_params__ = _plan_params(cls)
        by_field = {p.field: p for p in cls.__cli_params__}

        def resolve(
            f: dataclasses.Field[Any], hint: Any, where: str
        ) -> tuple[str, S.Schema[Any, Any]]:
            param = by_field[f.name]
            return (param.key, param.codec)

        cls.__cli_schema__ = S._struct_schema(cls, resolve)


def _plan_params(cls: type[Any]) -> tuple[_Param, ...]:
    hints = typing.get_type_hints(cls, include_extras=True)
    params: list[_Param] = []
    owner_of: dict[str, str] = {}
    for f in dataclasses.fields(cls):
        where = f"{cls.__name__}.{f.name}"
        annotation = hints[f.name]
        spec: Option | Argument = Option()
        if typing.get_origin(annotation) is typing.Annotated:
            for meta in annotation.__metadata__:
                if isinstance(meta, Option | Argument):
                    spec = meta
            annotation = typing.get_args(annotation)[0]
        while isinstance(annotation, TypeAliasType):
            annotation = annotation.__value__
        positional = isinstance(spec, Argument)
        short = None if isinstance(spec, Argument) else spec.short
        if positional:
            key = f.name.upper() if spec.name is None else spec.name
            if not key:
                raise TypeError(f"{where}: Argument name must not be empty")
        else:
            key = "--" + f.name.replace("_", "-") if spec.name is None else spec.name
            if not key.startswith("--"):
                raise TypeError(f"{where}: Option name {key!r} must start with '--'")
            if short is not None and not (
                len(short) == 2 and short[0] == "-" and short[1] != "-"
            ):
                raise TypeError(
                    f"{where}: short flag {short!r} must be '-' followed by one "
                    "character"
                )
        for name in (key, short) if short is not None else (key,):
            if name in owner_of:
                raise TypeError(
                    f"{cls.__name__}: fields {owner_of[name]!r} and {f.name!r} "
                    f"share the wire key {name!r}"
                )
            owner_of[name] = f.name

        origin, args = typing.get_origin(annotation), typing.get_args(annotation)
        flag = annotation is bool
        optional = (
            origin in (UnionType, typing.Union) and len(args) == 2 and NoneType in args
        )
        repeated = origin is tuple and len(args) == 2 and args[1] is Ellipsis
        codec: S.Schema[Any, Any]
        metavar: str | None
        if flag:
            if positional:
                raise TypeError(f"{where}: Cli.Argument cannot be a flag")
            if f.default is not False:
                raise TypeError(f"{where}: a flag's default must be False")
            codec, metavar = S.Bool, None
        else:
            if optional:
                inner = next(a for a in args if a is not NoneType)
            elif repeated:
                inner = args[0]
            else:
                inner = annotation
            if spec.schema is None:
                codec, metavar = _text_codec(inner, where)
            else:
                codec, metavar = spec.schema, "VALUE"
            if spec.metavar is not None:
                metavar = spec.metavar
            if optional:
                if f.default is not None:
                    raise TypeError(
                        f"{where}: an optional field's default must be None"
                    )
                codec = _optional(codec)
            elif repeated:
                codec = S.Array(codec)

        required = f.default is MISSING
        default_text = None
        if (
            not required
            and f.default is not None
            and f.default is not False
            and f.default != ()
        ):
            encoded: Any = codec._encode(f.default, ())
            # An invalid default is reported by the struct builder right after.
            if not isinstance(encoded, S._Issues):
                default_text = (
                    ", ".join(map(str, encoded)) if repeated else str(encoded)
                )
        params.append(
            _Param(
                field=f.name,
                key=key,
                short=short,
                help=spec.help,
                metavar=metavar,
                codec=codec,
                positional=positional,
                flag=flag,
                repeated=repeated,
                required=required,
                default_text=default_text,
            )
        )

    previous: _Param | None = None
    for p in (p for p in params if p.positional):
        if previous is not None and previous.repeated:
            raise TypeError(
                f"{cls.__name__}: argument {p.field!r} cannot follow "
                f"the variadic argument {previous.field!r}"
            )
        if previous is not None and not previous.required and p.required:
            raise TypeError(
                f"{cls.__name__}: argument {p.field!r} cannot follow "
                f"the optional argument {previous.field!r}"
            )
        previous = p
    return tuple(params)


def _text_codec(annotation: Any, where: str) -> tuple[S.Schema[Any, str], str]:
    """The Schema[T, str] and metavar inferred for a scalar annotation."""
    table: dict[Any, tuple[S.Schema[Any, str], str]] = {
        str: (S.String, "TEXT"),
        int: (S.IntFromString, "INTEGER"),
        float: (S.FloatFromString, "FLOAT"),
        Path: (S.PathFromString, "PATH"),
        datetime: (S.DateTimeFromString, "DATETIME"),
        date: (S.DateFromString, "DATE"),
    }
    if annotation in table:
        return table[annotation]
    if typing.get_origin(annotation) is typing.Literal:
        values = typing.get_args(annotation)
        if all(isinstance(v, str) for v in values):
            return S.Literal(*values), "[" + "|".join(values) + "]"
    raise TypeError(
        f"{where}: no text codec can be inferred for {annotation!r}; "
        "pass one with Cli.Option(schema=...)"
    )


def _optional(codec: S.Schema[Any, Any]) -> S.Schema[Any, Any]:
    """Decode as the codec does (the wire never carries None); encode None as None."""

    def encode(value: Any, path: S.IssuePath) -> Any:
        return None if value is None else codec._encode(value, path)

    return S.Schema(codec._decode, encode)

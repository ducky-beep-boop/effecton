import dataclasses
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

import pytest

import effecton as E

Cli = E.Cli
S = E.Schema

type Bump = Literal["major", "minor", "patch"]


class Add(Cli.Args):
    package: Annotated[str, Cli.Option(help="Package the change belongs to.")]
    bump: Annotated[Bump, Cli.Option(help="major, minor, or patch.")]
    message: Annotated[
        str,
        Cli.Option(
            help="Changelog entry for the change.",
            schema=S.String.check(
                S.filter(
                    lambda m: m.strip() != "", message="expected a non-empty message"
                )
            ),
        ),
    ]
    dry_run: Annotated[
        bool, Cli.Option(short="-n", help="Print the changeset instead of writing it.")
    ] = False


class Notes(Cli.Args):
    package: Annotated[str, Cli.Argument(help="Package to print notes for.")]


class Every(Cli.Args):
    text: str
    count: int
    ratio: float
    where: E.Path
    at: datetime
    day: date
    level: Literal["low", "high"]
    port: int | None = None
    tags: tuple[int, ...] = ()
    verbose: bool = False


def test_args_is_a_frozen_keyword_only_dataclass():
    args = Add(package="effecton", bump="patch", message="Fix it")

    with pytest.raises(dataclasses.FrozenInstanceError):
        args.package = "other"  # ty: ignore[invalid-assignment]

    assert args.dry_run is False


def test_args_decodes_the_raw_argv_dict_through_text_codecs():
    raw = {
        "--text": "a",
        "--count": "3",
        "--ratio": "0.5",
        "--where": "docs",
        "--at": "2026-09-22T10:00:00",
        "--day": "2026-09-22",
        "--level": "high",
        "--port": "80",
        "--tags": ["1", "2"],
        "--verbose": True,
    }

    result = E.run_sync(S.decode(Every.__cli_schema__)(raw))

    assert result == Every(
        text="a",
        count=3,
        ratio=0.5,
        where=E.Path("docs"),
        at=datetime(2026, 9, 22, 10),
        day=date(2026, 9, 22),
        level="high",
        port=80,
        tags=(1, 2),
        verbose=True,
    )


def test_absent_keys_take_their_defaults():
    raw = {
        "--text": "a",
        "--count": "3",
        "--ratio": "0.5",
        "--where": "docs",
        "--at": "2026-09-22T10:00:00",
        "--day": "2026-09-22",
        "--level": "high",
    }

    result = E.run_sync(S.decode(Every.__cli_schema__)(raw))

    assert (result.port, result.tags, result.verbose) == (None, (), False)


def test_params_carry_display_names_metavars_and_shapes():
    params = {p.field: p for p in Every.__cli_params__}

    assert params["text"].key == "--text"
    assert params["text"].metavar == "TEXT"
    assert params["count"].metavar == "INTEGER"
    assert params["ratio"].metavar == "FLOAT"
    assert params["where"].metavar == "PATH"
    assert params["at"].metavar == "DATETIME"
    assert params["day"].metavar == "DATE"
    assert params["level"].metavar == "[low|high]"
    assert params["port"].metavar == "INTEGER"
    assert params["tags"].repeated is True
    assert params["verbose"].flag is True
    assert params["verbose"].metavar is None
    add = {p.field: p for p in Add.__cli_params__}
    assert add["message"].metavar == "VALUE"
    assert add["dry_run"].short == "-n"
    assert add["package"].required is True
    assert add["dry_run"].required is False
    notes = Notes.__cli_params__[0]
    assert (notes.key, notes.positional) == ("PACKAGE", True)


def test_default_text_is_the_encoded_default():
    class Defaults(Cli.Args):
        out: E.Path = E.Path("docs/api.md")
        tags: tuple[int, ...] = (1, 2)
        port: int | None = None
        verbose: bool = False
        empty: tuple[str, ...] = ()

    params = {p.field: p for p in Defaults.__cli_params__}

    assert params["out"].default_text == "docs/api.md"
    assert params["tags"].default_text == "1, 2"
    assert params["port"].default_text is None
    assert params["verbose"].default_text is None
    assert params["empty"].default_text is None


def test_explicit_names_override_the_defaults():
    class Named(Cli.Args):
        package: Annotated[str, Cli.Option(name="--pkg", short="-p", metavar="NAME")]
        target: Annotated[str, Cli.Argument(name="DEST")]

    params = {p.field: p for p in Named.__cli_params__}

    assert (params["package"].key, params["package"].metavar) == ("--pkg", "NAME")
    assert params["target"].key == "DEST"


@pytest.mark.parametrize(
    ("define", "message"),
    [
        (
            lambda: type("Bad", (Cli.Args,), {"__annotations__": {"amount": Decimal}}),
            "Bad.amount: no text codec can be inferred for <class 'decimal.Decimal'>; "
            "pass one with Cli.Option(schema=...)",
        ),
        (
            lambda: type("Bad", (Cli.Args,), {"__annotations__": {"n": Literal[1, 2]}}),
            "Bad.n: no text codec can be inferred for typing.Literal[1, 2]; "
            "pass one with Cli.Option(schema=...)",
        ),
        (
            lambda: type("Bad", (Cli.Args,), {"__annotations__": {"f": bool | None}}),
            "Bad.f: no text codec can be inferred for <class 'bool'>; "
            "pass one with Cli.Option(schema=...)",
        ),
        (
            lambda: type(
                "Bad", (Cli.Args,), {"__annotations__": {"f": tuple[bool, ...]}}
            ),
            "Bad.f: no text codec can be inferred for <class 'bool'>; "
            "pass one with Cli.Option(schema=...)",
        ),
        (
            lambda: type("Bad", (Cli.Args,), {"__annotations__": {"dry_run": bool}}),
            "Bad.dry_run: a flag's default must be False",
        ),
        (
            lambda: type(
                "Bad",
                (Cli.Args,),
                {"__annotations__": {"dry_run": bool}, "dry_run": True},
            ),
            "Bad.dry_run: a flag's default must be False",
        ),
        (
            lambda: type("Bad", (Cli.Args,), {"__annotations__": {"port": int | None}}),
            "Bad.port: an optional field's default must be None",
        ),
        (
            lambda: type(
                "Bad",
                (Cli.Args,),
                {"__annotations__": {"verbose": Annotated[bool, Cli.Argument()]}},
            ),
            "Bad.verbose: Cli.Argument cannot be a flag",
        ),
        (
            lambda: type(
                "Bad",
                (Cli.Args,),
                {"__annotations__": {"bump": Annotated[str, Cli.Option(name="-b")]}},
            ),
            "Bad.bump: Option name '-b' must start with '--'",
        ),
        (
            lambda: type(
                "Bad",
                (Cli.Args,),
                {"__annotations__": {"bump": Annotated[str, Cli.Option(short="b")]}},
            ),
            "Bad.bump: short flag 'b' must be '-' followed by one character",
        ),
        (
            lambda: type(
                "Bad",
                (Cli.Args,),
                {
                    "__annotations__": {
                        "package": str,
                        "pkg": Annotated[str, Cli.Option(name="--package")],
                    }
                },
            ),
            "Bad: fields 'package' and 'pkg' share the wire key '--package'",
        ),
        (
            lambda: type(
                "Bad",
                (Cli.Args,),
                {
                    "__annotations__": {
                        "a": Annotated[str, Cli.Option(short="-x")],
                        "b": Annotated[str, Cli.Option(short="-x")],
                    }
                },
            ),
            "Bad: fields 'a' and 'b' share the wire key '-x'",
        ),
        (
            lambda: type(
                "Bad",
                (Cli.Args,),
                {
                    "__annotations__": {
                        "files": Annotated[tuple[str, ...], Cli.Argument()],
                        "rest": Annotated[str, Cli.Argument()],
                    }
                },
            ),
            "Bad: argument 'rest' cannot follow the variadic argument 'files'",
        ),
        (
            lambda: type(
                "Bad",
                (Cli.Args,),
                {
                    "__annotations__": {
                        "package": Annotated[str, Cli.Argument()],
                        "name": Annotated[str, Cli.Argument()],
                    },
                    "package": "effecton",
                },
            ),
            "Bad: argument 'name' cannot follow the optional argument 'package'",
        ),
        (
            lambda: type(
                "Bad",
                (Cli.Args,),
                {
                    "__annotations__": {
                        "message": Annotated[
                            str,
                            Cli.Option(
                                schema=S.String.check(
                                    S.filter(lambda m: m != "", message="expected text")
                                )
                            ),
                        ]
                    },
                    "message": "",
                },
            ),
            "Bad.message: the default '' does not satisfy its schema: "
            "expected text, got ''",
        ),
    ],
)
def test_definition_time_errors(define, message):
    with pytest.raises(TypeError) as info:
        define()

    assert str(info.value) == message


def test_command_exposes_its_name_and_help():
    add = Cli.command(
        "add", args=Add, handler=lambda args: E.success(None), help="Add."
    )

    assert (add.name, add.help) == ("add", "Add.")


def test_with_subcommands_rejects_a_command_with_a_handler():
    leaf = Cli.command("leaf", handler=lambda: E.success(None))

    with pytest.raises(TypeError) as info:
        leaf.with_subcommands(Cli.command("x"))

    assert str(info.value) == "leaf: a command has either a handler or subcommands"


def test_with_subcommands_can_only_be_set_once():
    app = Cli.command("app").with_subcommands(Cli.command("x"))

    with pytest.raises(TypeError) as info:
        app.with_subcommands(Cli.command("y"))

    assert str(info.value) == "app: subcommands are already set"


def test_with_subcommands_rejects_duplicate_names():
    with pytest.raises(TypeError) as info:
        Cli.command("app").with_subcommands(Cli.command("x"), Cli.command("x"))

    assert str(info.value) == "app: two subcommands are named 'x'"


def test_usage_errors_render_usage_and_a_help_hint():
    error = Cli.UnknownOption(
        "changeset add", "Usage: changeset add [OPTIONS]", "--foo"
    )

    assert str(error) == (
        "Usage: changeset add [OPTIONS]\n"
        "Try 'changeset add --help' for help.\n"
        "\n"
        "No such option '--foo'."
    )
    assert error.exit_code == 2

"""Schema: describe a shape once, then decode and encode through it.

A Schema[A, I] pairs two pure functions: decode turns untrusted input into
a typed A, encode turns an A back into its wire form I. Combinators build
bigger pairs from smaller ones, so every schema works in both directions.
decode and encode return effects that fail with one ParseError listing
every issue found, each tagged with the path where it occurred.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, final, overload

from effecton.effect import Effect, EffectonError, fail, success, sync

type IssuePath = tuple[str | int, ...]


@final
@dataclass(frozen=True)
class TypeMismatch:
    path: IssuePath
    expected: str
    actual: object

    def __str__(self) -> str:
        return _at(self.path, f"expected {self.expected}, got {self.actual!r}")


@final
@dataclass(frozen=True)
class MissingKey:
    path: IssuePath

    def __str__(self) -> str:
        return _at(self.path, "is missing")


@final
@dataclass(frozen=True)
class RefinementFailed:
    path: IssuePath
    message: str
    actual: object

    def __str__(self) -> str:
        return _at(self.path, f"{self.message}, got {self.actual!r}")


@final
@dataclass(frozen=True)
class TransformFailed:
    path: IssuePath
    message: str
    actual: object

    def __str__(self) -> str:
        return _at(self.path, f"{self.message}, got {self.actual!r}")


@final
@dataclass(frozen=True)
class NoUnionMember:
    """No member matched; issues holds what every member reported."""

    path: IssuePath
    actual: object
    issues: tuple[Issue, ...]

    def __str__(self) -> str:
        head = _at(self.path, f"no union member matched {self.actual!r}")
        nested = [
            f"  {line}" for issue in self.issues for line in str(issue).split("\n")
        ]
        return "\n".join([head, *nested])


@final
@dataclass(frozen=True)
class InvalidJson:
    path: IssuePath
    reason: str

    def __str__(self) -> str:
        return _at(self.path, f"invalid JSON: {self.reason}")


type Issue = (
    TypeMismatch
    | MissingKey
    | RefinementFailed
    | TransformFailed
    | NoUnionMember
    | InvalidJson
)


@final
@dataclass(frozen=True)
class ParseError(EffectonError):
    issues: tuple[Issue, ...]

    def __str__(self) -> str:
        return "\n".join(str(issue) for issue in self.issues)


@dataclass(frozen=True)
class _Issues:
    issues: tuple[Issue, ...]


@final
class Schema[A, I]:
    """A two-way codec: A is the decoded type, I the encoded one."""

    def __init__(
        self,
        decode: Callable[[object, IssuePath], A | _Issues],
        encode: Callable[[A, IssuePath], I | _Issues],
    ) -> None:
        self._decode = decode
        self._encode = encode

    @overload
    def pipe[B](self, f1: Callable[[Schema[A, I]], B], /) -> B: ...

    @overload
    def pipe[B, C](
        self, f1: Callable[[Schema[A, I]], B], f2: Callable[[B], C], /
    ) -> C: ...

    @overload
    def pipe[B, C, D](
        self,
        f1: Callable[[Schema[A, I]], B],
        f2: Callable[[B], C],
        f3: Callable[[C], D],
        /,
    ) -> D: ...

    @overload
    def pipe[B, C, D, F](
        self,
        f1: Callable[[Schema[A, I]], B],
        f2: Callable[[B], C],
        f3: Callable[[C], D],
        f4: Callable[[D], F],
        /,
    ) -> F: ...

    def pipe(self, *fs: Callable[[Any], Any]) -> Any:
        """Thread this schema through refinements, left to right."""
        result: Any = self
        for f in fs:
            result = f(result)
        return result


def decode[A, I](schema: Schema[A, I]) -> Callable[[object], Effect[A, ParseError]]:
    """decode(schema)(raw): turn untrusted input into a typed value."""
    resolved = _resolve(schema)

    def run(raw: object) -> Effect[Any, ParseError]:
        return sync(lambda: resolved._decode(raw, ())).flat_map(_settle)

    return run


def encode[A, I](schema: Schema[A, I]) -> Callable[[A], Effect[I, ParseError]]:
    """encode(schema)(value): turn a typed value back into its wire form."""
    resolved = _resolve(schema)

    def run(value: Any) -> Effect[Any, ParseError]:
        return sync(lambda: resolved._encode(value, ())).flat_map(_settle)

    return run


def Literal[T: str | int | bool | None](*values: T) -> Schema[T, T]:
    """One of the given values; True is not 1."""
    expected = " | ".join(repr(v) for v in values)

    def check(raw: Any, path: IssuePath) -> Any:
        if any(raw == v and type(raw) is type(v) for v in values):
            return raw
        return _Issues((TypeMismatch(path, expected, raw),))

    return Schema(check, check)


def _primitive[T](expected: str, accepts: Callable[[object], bool]) -> Schema[T, T]:
    # Defined before its callers: the primitives below are built at import time.
    def check(raw: Any, path: IssuePath) -> Any:
        if accepts(raw):
            return raw
        return _Issues((TypeMismatch(path, expected, raw),))

    return Schema(check, check)


String: Schema[str, str] = _primitive("string", lambda x: isinstance(x, str))
Int: Schema[int, int] = _primitive(
    "integer", lambda x: isinstance(x, int) and not isinstance(x, bool)
)
Float: Schema[float, float] = _primitive(
    "number", lambda x: isinstance(x, int | float) and not isinstance(x, bool)
)
Bool: Schema[bool, bool] = _primitive("boolean", lambda x: isinstance(x, bool))
Null: Schema[None, None] = _primitive("null", lambda x: x is None)
Unknown: Schema[object, object] = _primitive("anything", lambda _: True)


def _resolve(schema: Any) -> Schema[Any, Any]:
    if isinstance(schema, Schema):
        return schema
    raise TypeError(f"expected a Schema, got {schema!r}")


def _settle(result: Any) -> Effect[Any, ParseError]:
    if isinstance(result, _Issues):
        return fail(ParseError(issues=result.issues))
    return success(result)


def _at(path: IssuePath, body: str) -> str:
    location = ""
    for segment in path:
        if isinstance(segment, int):
            location += f"[{segment}]"
        else:
            location += f".{segment}" if location else segment
    return f"{location}: {body}" if location else body

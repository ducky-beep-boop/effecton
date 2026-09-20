"""Schema: describe a shape once, then decode and encode through it.

A Schema[A, I] pairs two pure functions: decode turns untrusted input into
a typed A, encode turns an A back into its wire form I. Combinators build
bigger pairs from smaller ones, so every schema works in both directions.
decode and encode return effects that fail with one ParseError listing
every issue found, each tagged with the path where it occurred.
"""

import re
from collections.abc import Callable, Iterable, Mapping, Sized
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, final, overload

from effecton.effect import Effect, EffectonError, fail, success, sync
from effecton.std.path import Path

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


def Array[A, I](item: Schema[A, I]) -> Schema[tuple[A, ...], list[I]]:
    """A list or tuple on the wire, a tuple once decoded."""
    inner = _resolve(item)

    def decode_array(raw: object, path: IssuePath) -> Any:
        if not isinstance(raw, list | tuple):
            return _Issues((TypeMismatch(path, "array", raw),))
        return _collect(
            tuple, (inner._decode(x, (*path, i)) for i, x in enumerate(raw))
        )

    def encode_array(value: Any, path: IssuePath) -> Any:
        if not isinstance(value, tuple):
            return _Issues((TypeMismatch(path, "tuple", value),))
        return _collect(
            list, (inner._encode(x, (*path, i)) for i, x in enumerate(value))
        )

    return Schema(decode_array, encode_array)


def Record[KA, KI, VA, VI](
    key: Schema[KA, KI], value: Schema[VA, VI]
) -> Schema[dict[KA, VA], dict[KI, VI]]:
    """A mapping whose keys and values each go through their schema."""

    def walk(direction: str) -> Callable[[Any, IssuePath], Any]:
        def run(raw: Any, path: IssuePath) -> Any:
            if not isinstance(raw, Mapping):
                return _Issues((TypeMismatch(path, "object", raw),))
            entries = []
            for k, v in raw.items():
                at = (*path, k if isinstance(k, str | int) else repr(k))
                entries.append(getattr(key, direction)(k, at))
                entries.append(getattr(value, direction)(v, at))
            return _collect(
                lambda flat: dict(zip(flat[::2], flat[1::2], strict=True)), entries
            )

        return run

    return Schema(walk("_decode"), walk("_encode"))


@overload
def Tuple[A1, I1](m1: Schema[A1, I1], /) -> Schema[tuple[A1], list[I1]]: ...


@overload
def Tuple[A1, I1, A2, I2](
    m1: Schema[A1, I1], m2: Schema[A2, I2], /
) -> Schema[tuple[A1, A2], list[I1 | I2]]: ...


@overload
def Tuple[A1, I1, A2, I2, A3, I3](
    m1: Schema[A1, I1], m2: Schema[A2, I2], m3: Schema[A3, I3], /
) -> Schema[tuple[A1, A2, A3], list[I1 | I2 | I3]]: ...


@overload
def Tuple[A1, I1, A2, I2, A3, I3, A4, I4](
    m1: Schema[A1, I1], m2: Schema[A2, I2], m3: Schema[A3, I3], m4: Schema[A4, I4], /
) -> Schema[tuple[A1, A2, A3, A4], list[I1 | I2 | I3 | I4]]: ...


@overload
def Tuple(*members: Schema[Any, Any]) -> Schema[tuple[Any, ...], list[Any]]: ...


def Tuple(*members: Schema[Any, Any]) -> Any:
    """A fixed-length array with one schema per position."""
    expected = f"array of {len(members)} items"

    def decode_tuple(raw: object, path: IssuePath) -> Any:
        if not isinstance(raw, list | tuple) or len(raw) != len(members):
            return _Issues((TypeMismatch(path, expected, raw),))
        return _collect(
            tuple,
            (
                m._decode(x, (*path, i))
                for i, (m, x) in enumerate(zip(members, raw, strict=True))
            ),
        )

    def encode_tuple(value: Any, path: IssuePath) -> Any:
        if not isinstance(value, tuple) or len(value) != len(members):
            return _Issues(
                (TypeMismatch(path, f"tuple of {len(members)} items", value),)
            )
        return _collect(
            list,
            (
                m._encode(x, (*path, i))
                for i, (m, x) in enumerate(zip(members, value, strict=True))
            ),
        )

    return Schema(decode_tuple, encode_tuple)


@overload
def Union[A1, I1, A2, I2](
    m1: Schema[A1, I1], m2: Schema[A2, I2], /
) -> Schema[A1 | A2, I1 | I2]: ...


@overload
def Union[A1, I1, A2, I2, A3, I3](
    m1: Schema[A1, I1], m2: Schema[A2, I2], m3: Schema[A3, I3], /
) -> Schema[A1 | A2 | A3, I1 | I2 | I3]: ...


@overload
def Union[A1, I1, A2, I2, A3, I3, A4, I4](
    m1: Schema[A1, I1], m2: Schema[A2, I2], m3: Schema[A3, I3], m4: Schema[A4, I4], /
) -> Schema[A1 | A2 | A3 | A4, I1 | I2 | I3 | I4]: ...


@overload
def Union(*members: Schema[Any, Any]) -> Schema[Any, Any]: ...


def Union(*members: Schema[Any, Any]) -> Any:
    """The first member that succeeds wins, decoding and encoding alike."""

    def walk(direction: str) -> Callable[[Any, IssuePath], Any]:
        def run(raw: Any, path: IssuePath) -> Any:
            collected: list[Issue] = []
            for member in members:
                result = getattr(member, direction)(raw, path)
                if not isinstance(result, _Issues):
                    return result
                collected.extend(result.issues)
            return _Issues((NoUnionMember(path, raw, tuple(collected)),))

        return run

    return Schema(walk("_decode"), walk("_encode"))


def NullOr[A, I](schema: Schema[A, I]) -> Schema[A | None, I | None]:
    return Union(_resolve(schema), Null)


@final
@dataclass(frozen=True)
class Invalid:
    """What a transform_or_fail function returns to reject its input."""

    message: str


def transform[A, I, B](
    from_: Schema[A, I], *, decode: Callable[[A], B], encode: Callable[[B], A]
) -> Schema[B, I]:
    """Map a schema's decoded side through a total function pair."""
    return transform_or_fail(from_, decode=decode, encode=encode)


def transform_or_fail[A, I, B](
    from_: Schema[A, I],
    *,
    decode: Callable[[A], B | Invalid],
    encode: Callable[[B], A | Invalid],
) -> Schema[B, I]:
    """Like transform, but either function may return Invalid(message).

    An exception raised by either function is a defect, not a ParseError.
    """

    def decode_through(raw: object, path: IssuePath) -> Any:
        inner: Any = from_._decode(raw, path)
        if isinstance(inner, _Issues):
            return inner
        outer = decode(inner)
        if isinstance(outer, Invalid):
            return _Issues((TransformFailed(path, outer.message, inner),))
        return outer

    def encode_through(value: Any, path: IssuePath) -> Any:
        inner = encode(value)
        if isinstance(inner, Invalid):
            return _Issues((TransformFailed(path, inner.message, value),))
        return from_._encode(inner, path)

    return Schema(decode_through, encode_through)


def filter[A, I](
    predicate: Callable[[A], bool], *, message: str
) -> Callable[[Schema[A, I]], Schema[A, I]]:
    """A refinement for pipe(): the predicate guards decode and encode alike."""

    def refine(schema: Schema[A, I]) -> Schema[A, I]:
        def decode_checked(raw: object, path: IssuePath) -> Any:
            result: Any = schema._decode(raw, path)
            if isinstance(result, _Issues) or predicate(result):
                return result
            return _Issues((RefinementFailed(path, message, result),))

        def encode_checked(value: Any, path: IssuePath) -> Any:
            if not predicate(value):
                return _Issues((RefinementFailed(path, message, value),))
            return schema._encode(value, path)

        return Schema(decode_checked, encode_checked)

    return refine


def min_length[A: Sized, I](n: int) -> Callable[[Schema[A, I]], Schema[A, I]]:
    return filter(lambda v: len(v) >= n, message=f"expected a length of at least {n}")


def max_length[A: Sized, I](n: int) -> Callable[[Schema[A, I]], Schema[A, I]]:
    return filter(lambda v: len(v) <= n, message=f"expected a length of at most {n}")


def pattern[I](regex: str) -> Callable[[Schema[str, I]], Schema[str, I]]:
    compiled = re.compile(regex)
    return filter(
        lambda v: compiled.search(v) is not None,
        message=f"expected a string matching {regex}",
    )


def greater_than[A: float, I](n: float) -> Callable[[Schema[A, I]], Schema[A, I]]:
    return filter(lambda v: v > n, message=f"expected a number greater than {n}")


def greater_than_or_equal_to[A: float, I](
    n: float,
) -> Callable[[Schema[A, I]], Schema[A, I]]:
    return filter(lambda v: v >= n, message=f"expected a number at least {n}")


def less_than[A: float, I](n: float) -> Callable[[Schema[A, I]], Schema[A, I]]:
    return filter(lambda v: v < n, message=f"expected a number less than {n}")


def less_than_or_equal_to[A: float, I](
    n: float,
) -> Callable[[Schema[A, I]], Schema[A, I]]:
    return filter(lambda v: v <= n, message=f"expected a number at most {n}")


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


def _parser[T](parse: Callable[[str], T], message: str) -> Callable[[str], T | Invalid]:
    def run(text: str) -> T | Invalid:
        try:
            return parse(text)
        except ValueError:
            return Invalid(message)

    return run


IntFromString: Schema[int, str] = transform_or_fail(
    String, decode=_parser(int, "expected an integer string"), encode=str
)
FloatFromString: Schema[float, str] = transform_or_fail(
    String, decode=_parser(float, "expected a number string"), encode=str
)
DateTimeFromString: Schema[datetime, str] = transform_or_fail(
    String,
    decode=_parser(datetime.fromisoformat, "expected an ISO 8601 datetime"),
    encode=datetime.isoformat,
)
DateFromString: Schema[date, str] = transform_or_fail(
    String,
    decode=_parser(date.fromisoformat, "expected an ISO 8601 date"),
    encode=date.isoformat,
)
PathFromString: Schema[Path, str] = transform(String, decode=Path, encode=str)


def _resolve(schema: Any) -> Schema[Any, Any]:
    if isinstance(schema, Schema):
        return schema
    raise TypeError(f"expected a Schema, got {schema!r}")


def _settle(result: Any) -> Effect[Any, ParseError]:
    if isinstance(result, _Issues):
        return fail(ParseError(issues=result.issues))
    return success(result)


def _collect(build: Callable[[list[Any]], Any], results: Iterable[Any]) -> Any:
    """Build from every result, or gather every issue if any result failed."""
    values: list[Any] = []
    issues: list[Issue] = []
    for result in results:
        if isinstance(result, _Issues):
            issues.extend(result.issues)
        else:
            values.append(result)
    return _Issues(tuple(issues)) if issues else build(values)


def _at(path: IssuePath, body: str) -> str:
    location = ""
    for segment in path:
        if isinstance(segment, int):
            location += f"[{segment}]"
        else:
            location += f".{segment}" if location else segment
    return f"{location}: {body}" if location else body

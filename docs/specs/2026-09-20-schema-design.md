# E.Schema design

A pydantic / Effect-TS Schema style library for effecton: describe a shape once, then decode untrusted input into typed values and encode typed values back. Pure Python, no new dependencies.

## Goals

- One definition yields both directions: `decode: I -> A` and `encode: A -> I`.
- Failures travel in the typed error channel as a single `ParseError` listing every issue with its path.
- Decoded structs are real frozen dataclasses that ty understands natively.
- Round-trip law for every built-in schema: `decode(encode(a)) == a`, and `encode(decode(x)) == x` for canonical `x` (the string-backed built-ins accept some non-canonical text, such as `" 42 "` or a `Z` suffix, and encode the canonical form).

## Non-goals (v1)

JSON Schema generation, effectful transforms that use services, recursive schemas (`S.suspend`), tagged-union sugar, a strict unknown-key mode, a dict-based struct combinator, and migrating `changesets` or `HttpClient` onto the library.

## Placement

`packages/effecton/src/effecton/std/schema.py`, exported from `effecton/__init__.py` as `E.Schema` (`from effecton.std import schema as Schema`). Consumers alias it: `S = E.Schema`. The module is added to `api_reference`'s `topics.TOPICS`. Tests are collocated: `std/test_schema.py` and `std/test_types_schema.py`. A patch changeset accompanies the change, and a docs page `docs/src/pages/std/schema.md` follows the existing std pages.

## Architecture

Each schema is a plain immutable-by-convention object holding a pair of pure functions (a `@final` class with two private callables, not a dataclass); combinators compose pairs. No AST and no per-node effects: an `Effect` is produced only at the public entry points. An AST can be layered on later without breaking the API.

```python
type IssuePath = tuple[str | int, ...]
type Result[T] = T | Issues          # Issues: a private wrapper around tuple[Issue, ...]

class Schema[A, I]:                  # A: decoded type, I: encoded type
    _decode: Callable[[object, IssuePath], Result[A]]
    _encode: Callable[[A, IssuePath], Result[I]]
    def check(self, *checks: Check[A]) -> Schema[A, I]: ...
```

`_decode` takes `object`, not `I`: input is untrusted, so every schema checks the runtime type itself. Variance of `A` and `I` is declared with old-style TypeVars if ty's inference requires it (see the ty notes in `CLAUDE.md`).

## Entry points

Curried, like `provide` and `catch`:

| Call | Result |
| --- | --- |
| `S.decode(schema)(raw: object)` | `Effect[A, ParseError]` |
| `S.encode(schema)(value: A)` | `Effect[I, ParseError]` |
| `S.decode_json(schema)(text: str)` | `Effect[A, ParseError]` |
| `S.encode_json(schema)(value: A)` | `Effect[str, ParseError]` |

Each is overloaded to accept a `Struct` subclass directly: `S.decode(User)(raw)` is `Effect[User, ParseError]`, and a struct's encoded type is `dict[str, object]`. The returned callables compose with `flat_map`: `response.json().flat_map(S.decode(User))`.

## Building blocks

**Primitives** — `S.String`, `S.Int`, `S.Float`, `S.Bool`, `S.Null`, `S.Unknown`, `S.Literal(*values)`, `S.instance_of(cls)` (any instance of `cls`, unchanged both ways). Strict, no coercion: `S.Int` rejects `bool` and `float`; `S.Float` accepts `int` and `float` (leaving an `int` unchanged) but rejects `bool`; `S.Literal` compares by value and exact type, so `Literal(1)` rejects `True`. Every schema, primitives included, checks the runtime type on encode as well as on decode.

**Collections** — `S.Array(item)` decodes a `list` or `tuple` to a `tuple` (a `str` is not an array) and encodes a `tuple` to a `list`; `S.Record(key, value)` decodes any `Mapping` to a `dict`, running each key and value through its schema, and a key that is neither `str` nor `int` appears in the path as `repr(key)`; `S.Tuple(*items)` is fixed-length, and a wrong length is one `TypeMismatch` on the whole value; `S.Tuple` and `S.Union` have precise overloads up to four members and fall back to `Any` beyond that; `S.Union(*members)` tries members in order on decode, and on encode picks the first member whose encode succeeds; `S.NullOr(schema)` is `Union(schema, Null)`.

**Transforms** — `S.transform(from_, decode=f, encode=g)` for total conversions, and `S.transform_or_fail(from_, decode=f, encode=g)` whose functions return the value or `S.Invalid(message)`, reported as a `TransformFailed` issue carrying the message and the value the function received. The decoded type is inferred from `f` (an annotated `def` infers exactly; a lambda may leave `Unknown` in it under ty). An optional `to=` schema guards the decoded side: on encode it runs before `g`, so a wrongly typed value is a `TypeMismatch` and `g` never sees it; on decode it runs after `f`. Every built-in passes one (`S.Int`, `S.Float`, `S.instance_of(...)`; `S.DateFromString` also rejects a `datetime`). Without `to`, a transform inside a `Union`/`NullOr` can be handed values meant for another member on encode, because a union encodes through the first member whose encode succeeds. Built-ins: `S.IntFromString` and `S.FloatFromString` accept whatever `int()`/`float()` accept and encode with `str`; `S.DateTimeFromString` and `S.DateFromString` use `fromisoformat`/`isoformat`; `S.PathFromString` is a total transform to `E.Path`. Each catches only `ValueError` from its parser. An unexpected exception inside a user function stays a defect.

**Refinements** — `S.filter(predicate, message=...)` and `S.pattern(regex)` (`re.search`, so anchor for a full match), each a `Check[A]` value (length and comparison sugar was dropped: `S.filter(lambda n: n > 0, message=...)` says it as briefly) applied through `schema.check(*checks)`. `Check` is `@final` and keeps its predicate and message private. Refinements run in both directions, as in Effect-TS: encoding an invalid value fails. On encode the inner schema encodes first and the checks run only if it succeeded, so a predicate never sees a value of the wrong type. Every failing check is reported.

## Structs

```python
class User(S.Struct):
    name: str                                   # inferred: S.String
    tags: tuple[str, ...] = ()                  # inferred: S.Array(S.String); default when the key is absent
    created: datetime = S.field(S.DateTimeFromString, key="createdAt")
```

- `Struct` is marked `@dataclass_transform(frozen_default=True, kw_only_default=True, field_specifiers=(field,))` and turns each subclass into a frozen, keyword-only dataclass in `__init_subclass__`.
- The annotation is always the decoded type. A schema is inferred for `str`, `int`, `float`, `bool`, `None`, `T | None`, `tuple[T, ...]`, `Mapping[str, T]`, `Literal[...]`, and nested `Struct` subclasses. Any other annotation without `S.field(schema)` raises `TypeError` at class definition.
- `S.field(schema=None, *, key=None, default=MISSING)`: `key` renames the wire key, and is only ignored when it is `None`, so `key=""` is honored (never test it for truthiness); a default makes the key optional on decode and is validated against the field's schema at class definition by running the schema's encode side on it. Encoding always emits every field. Mutable defaults (`dict`, `list`) are rejected by dataclasses itself with its `ValueError`; there is no `default_factory`.
- Unknown input keys are ignored on decode. Decoding a non-mapping is one `TypeMismatch` expecting `object`; encoding a value that is not an instance of the class is one `TypeMismatch` expecting the class name. Issue paths use wire keys when decoding and field names when encoding, and issues come in field declaration order. Struct inheritance keeps the parent's fields. Nested structs must be defined before the struct that references them (a forward or self reference fails at class definition).
- Definition-time errors are `TypeError`s with these exact messages: `Event.at: no schema can be inferred for <class 'datetime.datetime'>; pass one with S.field(schema)` (also for an annotation of `Struct` itself); `Point: fields 'a' and 'b' share the wire key 'x'`; `Port.number: the default 0 does not satisfy its schema: expected a port, got 0` (issues joined by `; `).
- `S.struct_schema(User)` exposes the underlying `Schema[User, dict[str, object]]` for use inside combinators (`S.Array(S.struct_schema(User))`); `S.Array` and `S.NullOr` also accept a `Struct` class directly, as do the four entry points.

## Errors

```python
@final
@dataclass(frozen=True)
class ParseError(EffectonError):
    issues: tuple[Issue, ...]
    def __str__(self) -> str: ...     # one line per issue: "users[2].createdAt: expected ISO 8601 datetime, got 'yesterday'"

type Issue = TypeMismatch | MissingKey | RefinementFailed | TransformFailed | NoUnionMember | InvalidJson
```

Issues are plain `@final` frozen dataclasses (data, not errors), each with `path: IssuePath` first and a `__str__` message. Their exact fields:

| Issue | Fields | Raised when |
| --- | --- | --- |
| `TypeMismatch` | `path, expected: str, actual: object` | the runtime type is wrong, on decode or encode |
| `MissingKey` | `path` | a struct key with no default is absent (the key is the last path segment; no other field) |
| `RefinementFailed` | `path, message: str, actual: object` | a `Check` predicate returned false |
| `TransformFailed` | `path, message: str, actual: object` | a `transform_or_fail` function returned `Invalid` |
| `NoUnionMember` | `path, actual: object, issues: tuple[Issue, ...]` | no union member matched; `issues` holds every member's issues in member order |
| `InvalidJson` | `path, reason: str` | `decode_json` got malformed or hostile text |

All issues in the input are collected: struct fields, array items, record entries, and tuple positions each contribute theirs. `decode_json` reports `JSONDecodeError` and the integer digit limit as `InvalidJson(reason=str(exception))`, excessive nesting as `InvalidJson(reason="nesting is too deep")`, and a non-`str` argument as `TypeMismatch(expected="JSON text")`; nothing else is caught. `encode_json` leaves an unserializable encoded form as a defect. One error class keeps `catch(S.ParseError)` exact.

### Messages and rendering

These strings are part of the contract; tests compare against them.

- `expected` in a `TypeMismatch` is one of: `string`, `integer`, `number`, `boolean`, `null`, `anything`, the `repr`s of a `Literal`'s values joined by ` | ` (`'a' | 1`), `array` (Array decode), `tuple` (Array encode), `object` (Record and Struct decode), `array of N items` / `tuple of N items` (Tuple decode / encode), `JSON text`, and the class name for `instance_of` and Struct encode.
- Built-in transform messages: `expected an integer string`, `expected a number string`, `expected an ISO 8601 datetime`, `expected an ISO 8601 date`; `DateFromString` rejects a `datetime` on encode with the `RefinementFailed` message `expected a date without a time`. `pattern`'s message is `expected a string matching <regex>`.
- A path renders string segments joined by `.` and int segments as `[i]`: `users[2].createdAt`. The empty path renders nothing.
- `str(issue)` is `<path>: <body>`, or just `<body>` at the root, where the body is `expected <expected>, got <actual!r>` (TypeMismatch), `is missing` (MissingKey), `<message>, got <actual!r>` (RefinementFailed, TransformFailed), `invalid JSON: <reason>` (InvalidJson), and for `NoUnionMember` the line `no union member matched <actual!r>` followed by every nested issue's rendering indented by two spaces, one per line.
- `str(ParseError)` joins `str(issue)` for each issue with newlines.

## Testing

- `test_schema.py` (Arrange-Act-Assert): per-combinator decode, encode, and round-trip; strictness cases (`bool` is not `Int`); issue accumulation with paths across nested structs and arrays; struct defaults, key renames, unknown keys, definition-time `TypeError`; union ordering; refinements failing on encode; JSON codecs and `InvalidJson`; `str(ParseError)` rendering.
- `test_types_schema.py`: `assert_type` pins for the entry points on schemas and on `Struct` classes, `A`/`I` inference through `Array`, `transform`, `Union`, and `check`; struct field and `__init__` types; negative pins (encoding the wrong type, assigning to a frozen field) inside never-called underscore functions.

## Recreation test

Two fresh agents rebuilt the library from this document alone and from this document plus the plan. Both reproduced the public surface and every type pin; the spec-only run failed 29 of the original 57 runtime tests, 24 of them on message wording and the rest on `key=""`, `MissingKey`'s fields, `decode_json` of a non-string and `NoUnionMember` rendering. The fields table, the messages section and the `key=""` sentence above exist to close those gaps.

## Risks

A typing spike against ty 0.0.75+ verified the design: `dataclass_transform` on a base class with `__init_subclass__`, `type[T]` overloads next to `Schema[A, I]` overloads, literal-preserving `S.Literal`, refinements through `pipe`, and `field` overloads all infer and reject as intended. Refinements were first designed as curried functions threaded through a `pipe` method; ty cannot solve that higher-order generic against a union-typed schema (`S.Float`, `S.NullOr(...)`, `S.Union(...)`) and yields `Unknown`. They are therefore values: `Check[A]` is contravariant in `A`, `Schema.check(*checks: Check[A])` needs no inference, and misuse (`S.Int.check(S.pattern("a"))`) is a plain argument error. This matches Effect-TS v4's `schema.check(...)`. There is no `pipe`. `S.Literal("a", "b")` keeps its literal types only where an expected type exists (an annotated variable, or `S.field(...)` on a `Literal[...]`-annotated struct field); bare, ty's literal promotion for invariant generics widens it to `Schema[str, str]`. One quirk remains: `Schema` is invariant, so an expected type must not flow into a `S.Union(...)` call — type pins bind the schema to a local before `assert_type`.

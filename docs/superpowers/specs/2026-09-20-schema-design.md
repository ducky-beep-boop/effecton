# E.Schema design

A pydantic / Effect-TS Schema style library for effecton: describe a shape once, then decode untrusted input into typed values and encode typed values back. Pure Python, no new dependencies.

## Goals

- One definition yields both directions: `decode: I -> A` and `encode: A -> I`.
- Failures travel in the typed error channel as a single `ParseError` listing every issue with its path.
- Decoded structs are real frozen dataclasses that ty understands natively.
- Round-trip law for every built-in schema: `encode(decode(x)) == x` for valid `x`, and `decode(encode(a)) == a`.

## Non-goals (v1)

JSON Schema generation, effectful transforms that use services, recursive schemas (`S.suspend`), tagged-union sugar, a strict unknown-key mode, a dict-based struct combinator, and migrating `changesets` or `HttpClient` onto the library.

## Placement

`packages/effecton/src/effecton/std/schema.py`, exported from `effecton/__init__.py` as `E.Schema` (`from effecton.std import schema as Schema`). Consumers alias it: `S = E.Schema`. The module is added to `api_reference`'s `topics.TOPICS`. Tests are collocated: `std/test_schema.py` and `std/test_types_schema.py`. A patch changeset accompanies the change, and a docs page `docs/src/pages/std/schema.md` follows the existing std pages.

## Architecture

Each schema is a frozen object holding a pair of pure functions; combinators compose pairs. No AST and no per-node effects: an `Effect` is produced only at the public entry points. An AST can be layered on later without breaking the API.

```python
type IssuePath = tuple[str | int, ...]
type Result[T] = T | Issues          # Issues: a private wrapper around tuple[Issue, ...]

class Schema[A, I]:                  # A: decoded type, I: encoded type
    _decode: Callable[[object, IssuePath], Result[A]]
    _encode: Callable[[A, IssuePath], Result[I]]
    def pipe(self, *fs) -> Schema[...]: ...
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

**Primitives** — `S.String`, `S.Int`, `S.Float`, `S.Bool`, `S.Null`, `S.Unknown`, `S.Literal(*values)`. Strict, no coercion: `S.Int` rejects `bool` and `float`; `S.Float` accepts `int` and `float` but rejects `bool`.

**Collections** — `S.Array(item)` decodes a `list` or `tuple` to a `tuple` and encodes to a `list`; `S.Record(key, value)` decodes a mapping to a `dict`; `S.Tuple(*items)` is fixed-length; `S.Union(*members)` tries members in order on decode, and on encode picks the first member whose encode succeeds; `S.NullOr(schema)` is `Union(schema, Null)`.

**Transforms** — `S.transform(from_, to, decode=f, encode=g)` for total conversions, and `S.transform_or_fail(from_, to, decode=f, encode=g)` whose functions return the value or an `S.TransformFailed` message. Built-ins: `S.IntFromString`, `S.FloatFromString`, `S.DateTimeFromString` (ISO 8601), `S.DateFromString`, `S.PathFromString` (`E.Path`). An unexpected exception inside a user function stays a defect.

**Refinements** — `S.filter(predicate, message=...)` plus sugar `S.min_length`, `S.max_length`, `S.pattern`, `S.greater_than`, `S.greater_than_or_equal_to`, `S.less_than`, `S.less_than_or_equal_to`, applied through `schema.pipe(...)`. Refinements run in both directions, as in Effect-TS: encoding an invalid value fails.

## Structs

```python
class User(S.Struct):
    name: str                                   # inferred: S.String
    tags: tuple[str, ...] = ()                  # inferred: S.Array(S.String); default when the key is absent
    created: datetime = S.field(S.DateTimeFromString, key="createdAt")
```

- `Struct` is marked `@dataclass_transform(frozen_default=True, kw_only_default=True, field_specifiers=(field,))` and turns each subclass into a frozen, keyword-only dataclass in `__init_subclass__`.
- The annotation is always the decoded type. A schema is inferred for `str`, `int`, `float`, `bool`, `None`, `T | None`, `tuple[T, ...]`, `Mapping[str, T]`, `Literal[...]`, and nested `Struct` subclasses. Any other annotation without `S.field(schema)` raises `TypeError` at class definition.
- `S.field(schema=None, *, key=None, default=MISSING)`: `key` renames the wire key; a default makes the key optional on decode. Encoding always emits every field.
- Unknown input keys are ignored on decode.
- `S.struct_schema(User)` exposes the underlying `Schema[User, dict[str, object]]` for use inside combinators (`S.Array(S.struct_schema(User))`); combinators also accept a `Struct` class directly where ty's overloads allow.

## Errors

```python
@final
@dataclass(frozen=True)
class ParseError(EffectonError):
    issues: tuple[Issue, ...]
    def __str__(self) -> str: ...     # one line per issue: "users[2].createdAt: expected ISO 8601 datetime, got 'yesterday'"

type Issue = TypeMismatch | MissingKey | RefinementFailed | TransformFailed | NoUnionMember | InvalidJson
```

Issues are plain `@final` frozen dataclasses (data, not errors), each with `path: IssuePath` and a `__str__` message. All issues in the input are collected: struct fields, array items, record entries, and tuple positions each contribute theirs. `NoUnionMember` carries the issues of every member it tried. `InvalidJson` appears at the root from `decode_json`. One error class keeps `catch(S.ParseError)` exact.

## Testing

- `test_schema.py` (Arrange-Act-Assert): per-combinator decode, encode, and round-trip; strictness cases (`bool` is not `Int`); issue accumulation with paths across nested structs and arrays; struct defaults, key renames, unknown keys, definition-time `TypeError`; union ordering; refinements failing on encode; JSON codecs and `InvalidJson`; `str(ParseError)` rendering.
- `test_types_schema.py`: `assert_type` pins for the entry points on schemas and on `Struct` classes, `A`/`I` inference through `Array`, `transform`, `Union`, and `pipe`; struct field and `__init__` types; negative pins (encoding the wrong type, assigning to a frozen field) inside never-called underscore functions.

## Risks

ty's support for `dataclass_transform` on a base class with `__init_subclass__`, and for `type[T]` overloads next to `Schema[A, I]` overloads, is unverified. The implementation plan starts with a typing spike. Fallbacks, in order: a `@S.struct` class decorator instead of the base class; requiring `S.struct_schema(User)` instead of overloading entry points on the class.

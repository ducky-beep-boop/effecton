---
title: Schema
description: Describe a shape once, then decode untrusted input and encode it back, with every issue reported in the typed error channel.
---

# Schema

`E.Schema` describes the shape of data once and works in both directions: `decode` turns untrusted input into typed values, `encode` turns typed values back into their wire form. Both return effects that fail with a single `ParseError` listing every issue found, each tagged with the path where it occurred.

```python
from datetime import datetime

import effecton as E

S = E.Schema


# ---cut---
class User(S.Struct):
    name: str
    age: int = S.field(S.Int.check(S.greater_than_or_equal_to(0)))
    created: datetime = S.field(S.DateTimeFromString, key="createdAt")
    tags: tuple[str, ...] = ()


raw = {"name": "Ada", "age": 36, "createdAt": "2026-09-20T10:30:00"}
user = S.decode(User)(raw)
#  ^?
```

## Structs

A `Struct` subclass is a frozen, keyword-only dataclass, so the decoded value is a plain typed object. Annotations are the decoded types. A schema is inferred for `str`, `int`, `float`, `bool`, `None`, unions of those, `Literal[...]`, `tuple[T, ...]`, `Mapping[str, T]` and nested structs; anything else names its schema through `S.field(schema)`, or the class definition raises `TypeError`. `key=` renames the field on the wire, and a field with a default may be absent from the input; two fields may not share a wire key. Unknown input keys are ignored. A nested struct must be defined before the struct that references it: forward and self references are not supported. Issue paths use wire keys when decoding and field names when encoding.

## Two directions

Every schema is a `Schema[A, I]`: `A` is the decoded type and `I` the encoded one. `S.IntFromString` is a `Schema[int, str]`, so it decodes `"42"` to `42` and encodes `42` back to `"42"`.

```python
import effecton as E

S = E.Schema

# ---cut---
user_ids = S.Array(S.IntFromString)
#  ^?
decoded = S.decode(user_ids)(["1", "2"])  # succeeds with (1, 2)
encoded = S.encode(user_ids)((1, 2))  # succeeds with ["1", "2"]
```

Build your own with `S.transform`, or with `S.transform_or_fail` when a direction can reject its input by returning `S.Invalid(message)`. An exception raised inside a transform is a defect, not a `ParseError`. Pass `to=` a schema for the decoded type — usually `S.instance_of(cls)` or a primitive — and encode checks the value against it before calling your function, while decode checks your function's result. Without `to`, encode hands the value straight to the function, so inside a `S.Union` or `S.NullOr` your function can receive a value meant for another member; every built-in transform is guarded this way.

```python
import effecton as E

S = E.Schema


# ---cut---
def parse_port(n: int) -> int | S.Invalid:
    return n if 0 < n < 65536 else S.Invalid("expected a port number")


Port = S.transform_or_fail(S.IntFromString, decode=parse_port, encode=parse_port)
```

## Building blocks

| Kind | Schemas |
| --- | --- |
| Primitives | `S.String`, `S.Int`, `S.Float`, `S.Bool`, `S.Null`, `S.Unknown`, `S.Literal(...)`, `S.instance_of(cls)` |
| Collections | `S.Array(item)`, `S.Record(key, value)`, `S.Tuple(...)`, `S.Union(...)`, `S.NullOr(schema)` |
| Transforms | `S.IntFromString`, `S.FloatFromString`, `S.DateTimeFromString`, `S.DateFromString`, `S.PathFromString` |
| Refinements | `S.filter`, `S.min_length`, `S.max_length`, `S.pattern`, `S.greater_than`, `S.greater_than_or_equal_to`, `S.less_than`, `S.less_than_or_equal_to` |

Primitives are strict and never coerce: `S.Int` rejects `True` and `1.0`. Arrays decode to tuples. Refinements are `Check` values built by `S.filter` and the comparison helpers, attached with `schema.check(...)`, and guard both directions, so encoding an invalid value fails too. `schema.check(c1, c2)` reports every check that fails, not just the first. `S.Array` and `S.NullOr` take a `Struct` class directly; elsewhere use `S.struct_schema(User)`. `S.Literal("a", "b")` keeps its literal member types only where an expected type guides inference, such as an annotated variable or a `Literal[...]`-typed struct field; called bare, it widens to `Schema[str, str]`.

## Errors

A failed decode or encode fails with `S.ParseError`. Its `issues` tuple holds every problem in the input — `TypeMismatch`, `MissingKey`, `RefinementFailed`, `TransformFailed`, `NoUnionMember` or `InvalidJson` — and `str(error)` renders one line per issue:

```
name: expected string, got 1
address.zip: is missing
tags[1]: expected string, got 2
```

## JSON

`S.decode_json(schema)(text)` parses JSON text before decoding, reporting malformed text as an `InvalidJson` issue, and `S.encode_json(schema)(value)` serializes after encoding. Decoding also composes with anything else that yields raw data, such as an HTTP response body:

```python
import effecton as E

S = E.Schema


class Release(S.Struct):
    tag: str = S.field(key="tag_name")


# ---cut---
@E.gen
def latest_release(
    url: str,
) -> E.EffectGen[
    Release,
    E.HttpClient.TransportError | E.HttpClient.InvalidJson | S.ParseError,
    E.HttpClient.Protocol,
]:
    http = yield from E.require(E.HttpClient.Protocol)

    response = yield from http.get(url)
    raw = yield from response.json()
    return (yield from S.decode(Release)(raw))
```

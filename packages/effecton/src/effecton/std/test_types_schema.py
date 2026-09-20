"""Type-level pins for Schema. Nothing here runs: ty checks the function
bodies and pytest never calls them."""

from collections.abc import Sized
from datetime import date, datetime
from typing import Literal, assert_type

import effecton as E

S = E.Schema


class Address(S.Struct):
    city: str
    zip_code: str = S.field(key="zip")


class User(S.Struct):
    name: str
    age: int = S.field(S.IntFromString)
    address: Address
    tags: tuple[str, ...] = ()


class Member(S.Struct):
    role: Literal["admin", "member"] = S.field(S.Literal("admin", "member"), key="r")


def _primitives_carry_both_sides() -> None:
    assert_type(S.String, S.Schema[str, str])
    assert_type(S.Int, S.Schema[int, int])
    assert_type(S.IntFromString, S.Schema[int, str])
    assert_type(S.DateTimeFromString, S.Schema[datetime, str])
    assert_type(S.DateFromString, S.Schema[date, str])
    assert_type(S.PathFromString, S.Schema[E.Path, str])
    # Bare, ty's literal promotion for invariant generics widens the members...
    widened = S.Literal("a", "b")
    assert_type(widened, S.Schema[str, str])
    # ...while an expected type keeps them.
    literal: S.Schema[Literal["a", "b"], Literal["a", "b"]] = S.Literal("a", "b")
    assert_type(literal, S.Schema[Literal["a", "b"], Literal["a", "b"]])
    assert_type(S.decode(literal)("a"), E.Effect[Literal["a", "b"], S.ParseError])


def _entry_points_return_effects_failing_with_parse_error() -> None:
    assert_type(S.decode(S.IntFromString)("1"), E.Effect[int, S.ParseError])
    assert_type(S.encode(S.IntFromString)(1), E.Effect[str, S.ParseError])
    assert_type(S.decode_json(S.IntFromString)('"1"'), E.Effect[int, S.ParseError])
    assert_type(S.encode_json(S.IntFromString)(1), E.Effect[str, S.ParseError])


def _collections_compose_both_sides() -> None:
    # Bind first: an expected type inside assert_type leaks into an invariant call.
    array = S.Array(S.IntFromString)
    assert_type(array, S.Schema[tuple[int, ...], list[str]])
    record = S.Record(S.String, S.IntFromString)
    assert_type(record, S.Schema[dict[str, int], dict[str, str]])
    pair = S.Tuple(S.String, S.Int)
    assert_type(pair, S.Schema[tuple[str, int], list[str | int]])
    union = S.Union(S.String, S.IntFromString)
    assert_type(union, S.Schema[str | int, str])
    nullable = S.NullOr(S.Int)
    assert_type(nullable, S.Schema[int | None, int | None])
    assert_type(S.decode(union)("x"), E.Effect[str | int, S.ParseError])


def _transforms_and_refinements_keep_types() -> None:
    length = S.transform(S.String, decode=len, encode=lambda n: "x" * n)
    assert_type(length, S.Schema[int, str])

    def halve(n: int) -> int | S.Invalid:
        return n // 2 if n % 2 == 0 else S.Invalid("odd")

    def double(n: int) -> int | S.Invalid:
        return n * 2

    halved = S.transform_or_fail(S.Int, decode=halve, encode=double)
    assert_type(halved, S.Schema[int, int])
    refined = S.String.check(S.min_length(1), S.pattern("^a"))
    assert_type(refined, S.Schema[str, str])
    positive = S.IntFromString.check(S.greater_than(0))
    assert_type(positive, S.Schema[int, str])
    even = S.Int.check(S.filter(lambda n: n % 2 == 0, message="even"))
    assert_type(even, S.Schema[int, int])

    ranged = S.Float.check(S.greater_than(0), S.less_than(1))
    assert_type(ranged, S.Schema[float, float])
    maybe_long = S.NullOr(S.String).check(
        S.filter(lambda v: v is None or len(v) > 1, message="m")
    )
    assert_type(maybe_long, S.Schema[str | None, str | None])
    min_len_check = S.min_length(1)
    assert_type(min_len_check, S.Check[Sized])
    greater_than_check = S.greater_than(0)
    assert_type(greater_than_check, S.Check[float])


def _structs_are_typed_dataclasses_and_schemas() -> None:
    user = User(name="Ada", age=36, address=Address(city="London", zip_code="N1"))
    assert_type(user.name, str)
    assert_type(user.age, int)
    assert_type(user.address, Address)
    assert_type(user.tags, tuple[str, ...])
    assert_type(S.decode(User)({}), E.Effect[User, S.ParseError])
    assert_type(S.encode(User)(user), E.Effect[dict[str, object], S.ParseError])
    assert_type(S.decode_json(User)("{}"), E.Effect[User, S.ParseError])
    assert_type(S.encode_json(User)(user), E.Effect[str, S.ParseError])
    assert_type(S.struct_schema(User), S.Schema[User, dict[str, object]])
    users = S.Array(User)
    assert_type(users, S.Schema[tuple[User, ...], list[dict[str, object]]])
    maybe = S.NullOr(User)
    assert_type(maybe, S.Schema[User | None, dict[str, object] | None])
    member = Member(role="admin")
    assert_type(member.role, Literal["admin", "member"])


def _decoded_effects_compose_with_flat_map() -> None:
    program = E.success({"city": "A", "zip": "1"}).flat_map(S.decode(Address))
    assert_type(program, E.Effect[Address, S.ParseError])
    caught = program.catch(S.ParseError)(lambda e: E.success(str(e)))
    assert_type(caught, E.Effect[Address | str])


def _schema_negative() -> None:
    # encode takes the decoded type.
    S.encode(S.IntFromString)("1")  # ty: ignore[invalid-argument-type]
    S.encode(User)(Address(city="A", zip_code="1"))  # ty: ignore[invalid-argument-type]

    # Struct construction is keyword-only, typed and complete.
    Address("A", "1")  # ty: ignore[missing-argument, too-many-positional-arguments]
    Address(city=1, zip_code="1")  # ty: ignore[invalid-argument-type]
    Address(city="A")  # ty: ignore[missing-argument]

    # Struct instances are frozen.
    address = Address(city="A", zip_code="1")
    address.city = "B"  # ty: ignore[invalid-assignment]

    # A field's schema must decode to the annotated type.
    _must_be_int: int = S.field(S.String)  # ty: ignore[invalid-assignment]

    # Refinements only fit schemas of the right decoded type.
    S.Int.check(S.min_length(1))  # ty: ignore[invalid-argument-type]
    S.String.check(S.greater_than(1))  # ty: ignore[invalid-argument-type]
    S.Int.check(S.pattern("a"))  # ty: ignore[invalid-argument-type]
    S.NullOr(S.String).check(S.min_length(1))  # ty: ignore[invalid-argument-type]

    # Literal members are str, int, bool or None.
    S.Literal(1.5)  # ty: ignore[invalid-argument-type]

    # A field's literal schema must match the annotated literal members.
    Member(role="owner")  # ty: ignore[invalid-argument-type]

    # Schema is a leaf.
    class Custom(S.Schema[int, int]):  # ty: ignore[subclass-of-final-class]
        pass

    # Check is a leaf.
    class CustomCheck(S.Check[int]):  # ty: ignore[subclass-of-final-class]
        pass

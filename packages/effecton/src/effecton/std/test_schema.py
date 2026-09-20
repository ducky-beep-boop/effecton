from datetime import date, datetime

import effecton as E

S = E.Schema


def ok(value: object):
    return E.Succeeded(value)


def bad(*issues: S.Issue):
    return E.Failure(cause=E.Fail(S.ParseError(issues=issues)))


def test_string_decodes_and_encodes_a_str():
    decoded = E.run_sync_exit(S.decode(S.String)("hi"))
    encoded = E.run_sync_exit(S.encode(S.String)("hi"))

    assert decoded == ok("hi")
    assert encoded == ok("hi")


def test_string_rejects_other_types_with_a_type_mismatch():
    r = E.run_sync_exit(S.decode(S.String)(1))

    assert r == bad(S.TypeMismatch(path=(), expected="string", actual=1))


def test_int_is_strict_about_bool_and_float():
    from_bool = E.run_sync_exit(S.decode(S.Int)(True))
    from_float = E.run_sync_exit(S.decode(S.Int)(1.0))
    from_int = E.run_sync_exit(S.decode(S.Int)(7))

    assert from_bool == bad(S.TypeMismatch(path=(), expected="integer", actual=True))
    assert from_float == bad(S.TypeMismatch(path=(), expected="integer", actual=1.0))
    assert from_int == ok(7)


def test_float_accepts_int_and_float_but_not_bool():
    from_int = E.run_sync_exit(S.decode(S.Float)(1))
    from_float = E.run_sync_exit(S.decode(S.Float)(1.5))
    from_bool = E.run_sync_exit(S.decode(S.Float)(False))

    assert from_int == ok(1)
    assert from_float == ok(1.5)
    assert from_bool == bad(S.TypeMismatch(path=(), expected="number", actual=False))


def test_bool_null_and_unknown():
    a_bool = E.run_sync_exit(S.decode(S.Bool)(True))
    not_bool = E.run_sync_exit(S.decode(S.Bool)(1))
    a_null = E.run_sync_exit(S.decode(S.Null)(None))
    not_null = E.run_sync_exit(S.decode(S.Null)(0))
    anything = E.run_sync_exit(S.decode(S.Unknown)([1, "x"]))

    assert a_bool == ok(True)
    assert not_bool == bad(S.TypeMismatch(path=(), expected="boolean", actual=1))
    assert a_null == ok(None)
    assert not_null == bad(S.TypeMismatch(path=(), expected="null", actual=0))
    assert anything == ok([1, "x"])


def test_literal_accepts_only_its_values_and_keeps_bool_apart_from_int():
    schema = S.Literal("a", 1)

    hit = E.run_sync_exit(S.decode(schema)("a"))
    miss = E.run_sync_exit(S.decode(schema)("b"))
    bool_is_not_one = E.run_sync_exit(S.decode(schema)(True))
    encode_miss = E.run_sync_exit(S.encode(schema)("b"))

    assert hit == ok("a")
    assert miss == bad(S.TypeMismatch(path=(), expected="'a' | 1", actual="b"))
    assert bool_is_not_one == bad(
        S.TypeMismatch(path=(), expected="'a' | 1", actual=True)
    )
    assert encode_miss == bad(S.TypeMismatch(path=(), expected="'a' | 1", actual="b"))


def test_encode_checks_the_runtime_type_too():
    r = E.run_sync_exit(S.encode(S.Int)("x"))  # ty: ignore[invalid-argument-type]

    assert r == bad(S.TypeMismatch(path=(), expected="integer", actual="x"))


def test_decode_is_lazy_until_run():
    calls: list[object] = []

    def spy(raw: object, path: S.IssuePath) -> object:
        calls.append(raw)
        return raw

    schema = S.Schema(spy, spy)

    effect = S.decode(schema)("x")

    assert calls == []
    assert E.run_sync_exit(effect) == ok("x")
    assert calls == ["x"]


def test_parse_error_renders_one_line_per_issue_with_paths():
    error = S.ParseError(
        issues=(
            S.TypeMismatch(path=(), expected="string", actual=1),
            S.MissingKey(path=("users", 2, "createdAt")),
            S.RefinementFailed(path=("name",), message="too short", actual=""),
            S.TransformFailed(path=("a", "b"), message="not ISO 8601", actual="x"),
            S.InvalidJson(path=(), reason="Expecting value"),
            S.NoUnionMember(
                path=("id",),
                actual=1.5,
                issues=(S.TypeMismatch(path=("id",), expected="string", actual=1.5),),
            ),
        )
    )

    rendered = str(error)

    assert rendered == "\n".join(
        [
            "expected string, got 1",
            "users[2].createdAt: is missing",
            "name: too short, got ''",
            "a.b: not ISO 8601, got 'x'",
            "invalid JSON: Expecting value",
            "id: no union member matched 1.5",
            "  id: expected string, got 1.5",
        ]
    )


def test_array_decodes_to_a_tuple_and_encodes_to_a_list():
    schema = S.Array(S.Int)

    from_list = E.run_sync_exit(S.decode(schema)([1, 2]))
    from_tuple = E.run_sync_exit(S.decode(schema)((1, 2)))
    encoded = E.run_sync_exit(S.encode(schema)((1, 2)))

    assert from_list == ok((1, 2))
    assert from_tuple == ok((1, 2))
    assert encoded == ok([1, 2])


def test_array_collects_every_item_issue_with_its_index():
    r = E.run_sync_exit(S.decode(S.Array(S.Int))([1, "x", 3, None]))

    assert r == bad(
        S.TypeMismatch(path=(1,), expected="integer", actual="x"),
        S.TypeMismatch(path=(3,), expected="integer", actual=None),
    )


def test_array_rejects_non_sequences_and_strings():
    not_a_list = E.run_sync_exit(S.decode(S.Array(S.String))("ab"))
    encode_a_list = E.run_sync_exit(S.encode(S.Array(S.Int))([1]))  # ty: ignore[invalid-argument-type]

    assert not_a_list == bad(S.TypeMismatch(path=(), expected="array", actual="ab"))
    assert encode_a_list == bad(S.TypeMismatch(path=(), expected="tuple", actual=[1]))


def test_record_round_trips_and_reports_key_and_value_issues():
    schema = S.Record(S.String, S.Int)

    decoded = E.run_sync_exit(S.decode(schema)({"a": 1}))
    encoded = E.run_sync_exit(S.encode(schema)({"a": 1}))
    broken = E.run_sync_exit(S.decode(schema)({"a": "x", 2: 3}))
    not_a_mapping = E.run_sync_exit(S.decode(schema)([]))

    assert decoded == ok({"a": 1})
    assert encoded == ok({"a": 1})
    assert broken == bad(
        S.TypeMismatch(path=("a",), expected="integer", actual="x"),
        S.TypeMismatch(path=(2,), expected="string", actual=2),
    )
    assert not_a_mapping == bad(S.TypeMismatch(path=(), expected="object", actual=[]))


def test_tuple_is_fixed_length_and_positional():
    schema = S.Tuple(S.String, S.Int)

    decoded = E.run_sync_exit(S.decode(schema)(["a", 1]))
    encoded = E.run_sync_exit(S.encode(schema)(("a", 1)))
    wrong_length = E.run_sync_exit(S.decode(schema)(["a"]))
    wrong_item = E.run_sync_exit(S.decode(schema)([1, "a"]))

    assert decoded == ok(("a", 1))
    assert encoded == ok(["a", 1])
    assert wrong_length == bad(
        S.TypeMismatch(path=(), expected="array of 2 items", actual=["a"])
    )
    assert wrong_item == bad(
        S.TypeMismatch(path=(0,), expected="string", actual=1),
        S.TypeMismatch(path=(1,), expected="integer", actual="a"),
    )


def test_union_takes_the_first_member_that_matches():
    schema = S.Union(S.Int, S.String)

    an_int = E.run_sync_exit(S.decode(schema)(1))
    a_str = E.run_sync_exit(S.decode(schema)("a"))
    encoded = E.run_sync_exit(S.encode(schema)("a"))

    assert an_int == ok(1)
    assert a_str == ok("a")
    assert encoded == ok("a")


def test_union_reports_every_members_issues_when_none_matches():
    r = E.run_sync_exit(S.decode(S.Union(S.Int, S.String))(1.5))

    assert r == bad(
        S.NoUnionMember(
            path=(),
            actual=1.5,
            issues=(
                S.TypeMismatch(path=(), expected="integer", actual=1.5),
                S.TypeMismatch(path=(), expected="string", actual=1.5),
            ),
        )
    )


def test_null_or_accepts_none_in_both_directions():
    schema = S.NullOr(S.Int)

    a_none = E.run_sync_exit(S.decode(schema)(None))
    an_int = E.run_sync_exit(S.decode(schema)(1))
    encoded = E.run_sync_exit(S.encode(schema)(None))

    assert a_none == ok(None)
    assert an_int == ok(1)
    assert encoded == ok(None)


def test_transform_maps_both_directions():
    schema = S.transform(S.String, decode=len, encode=lambda n: "x" * n)

    decoded = E.run_sync_exit(S.decode(schema)("abc"))
    encoded = E.run_sync_exit(S.encode(schema)(3))
    wrong_wire_type = E.run_sync_exit(S.decode(schema)(1))

    assert decoded == ok(3)
    assert encoded == ok("xxx")
    assert wrong_wire_type == bad(S.TypeMismatch(path=(), expected="string", actual=1))


def test_transform_or_fail_reports_invalid_as_a_transform_issue():
    def halve(n: int) -> int | S.Invalid:
        return n // 2 if n % 2 == 0 else S.Invalid("expected an even number")

    schema = S.transform_or_fail(S.Int, decode=halve, encode=lambda n: n * 2)

    decoded = E.run_sync_exit(S.decode(schema)(4))
    rejected = E.run_sync_exit(S.decode(schema)(3))

    assert decoded == ok(2)
    assert rejected == bad(
        S.TransformFailed(path=(), message="expected an even number", actual=3)
    )


def test_an_exception_inside_a_transform_is_a_defect():
    boom = ValueError("boom")

    def explode(_: str) -> int:
        raise boom

    schema = S.transform(S.String, decode=explode, encode=str)

    r = E.run_sync_exit(S.decode(schema)("x"))

    assert r == E.Failure(cause=E.Die(defect=boom))


def test_builtin_string_transforms_round_trip():
    an_int = E.run_sync_exit(S.decode(S.IntFromString)("42"))
    a_float = E.run_sync_exit(S.decode(S.FloatFromString)("1.5"))
    a_moment = E.run_sync_exit(S.decode(S.DateTimeFromString)("2026-09-20T10:30:00"))
    a_day = E.run_sync_exit(S.decode(S.DateFromString)("2026-09-20"))
    a_path = E.run_sync_exit(S.decode(S.PathFromString)("/a/b"))
    int_back = E.run_sync_exit(S.encode(S.IntFromString)(42))
    moment_back = E.run_sync_exit(
        S.encode(S.DateTimeFromString)(datetime(2026, 9, 20, 10, 30))
    )
    day_back = E.run_sync_exit(S.encode(S.DateFromString)(date(2026, 9, 20)))
    path_back = E.run_sync_exit(S.encode(S.PathFromString)(E.Path("/a/b")))

    assert an_int == ok(42)
    assert a_float == ok(1.5)
    assert a_moment == ok(datetime(2026, 9, 20, 10, 30))
    assert a_day == ok(date(2026, 9, 20))
    assert a_path == ok(E.Path("/a/b"))
    assert int_back == ok("42")
    assert moment_back == ok("2026-09-20T10:30:00")
    assert day_back == ok("2026-09-20")
    assert path_back == ok("/a/b")


def test_builtin_string_transforms_reject_malformed_text():
    not_int = E.run_sync_exit(S.decode(S.IntFromString)("4x"))
    not_float = E.run_sync_exit(S.decode(S.FloatFromString)("nope"))
    not_moment = E.run_sync_exit(S.decode(S.DateTimeFromString)("yesterday"))
    not_day = E.run_sync_exit(S.decode(S.DateFromString)("2026-13-40"))

    assert not_int == bad(
        S.TransformFailed(path=(), message="expected an integer string", actual="4x")
    )
    assert not_float == bad(
        S.TransformFailed(path=(), message="expected a number string", actual="nope")
    )
    assert not_moment == bad(
        S.TransformFailed(
            path=(), message="expected an ISO 8601 datetime", actual="yesterday"
        )
    )
    assert not_day == bad(
        S.TransformFailed(
            path=(), message="expected an ISO 8601 date", actual="2026-13-40"
        )
    )


def test_filter_guards_decode_and_encode():
    even = S.Int.pipe(S.filter(lambda n: n % 2 == 0, message="expected an even number"))

    passed = E.run_sync_exit(S.decode(even)(2))
    decode_rejected = E.run_sync_exit(S.decode(even)(3))
    encode_rejected = E.run_sync_exit(S.encode(even)(3))
    wrong_type = E.run_sync_exit(S.decode(even)("x"))

    assert passed == ok(2)
    assert decode_rejected == bad(
        S.RefinementFailed(path=(), message="expected an even number", actual=3)
    )
    assert encode_rejected == bad(
        S.RefinementFailed(path=(), message="expected an even number", actual=3)
    )
    assert wrong_type == bad(S.TypeMismatch(path=(), expected="integer", actual="x"))


def test_refinement_sugar():
    name = S.String.pipe(S.min_length(2), S.max_length(3), S.pattern(r"^[a-z]+$"))
    percent = S.Int.pipe(S.greater_than_or_equal_to(0), S.less_than_or_equal_to(100))
    open_unit = S.Float.pipe(S.greater_than(0), S.less_than(1))

    assert E.run_sync_exit(S.decode(name)("ab")) == ok("ab")
    assert E.run_sync_exit(S.decode(name)("a")) == bad(
        S.RefinementFailed(
            path=(), message="expected a length of at least 2", actual="a"
        )
    )
    assert E.run_sync_exit(S.decode(name)("abcd")) == bad(
        S.RefinementFailed(
            path=(), message="expected a length of at most 3", actual="abcd"
        )
    )
    assert E.run_sync_exit(S.decode(name)("AB")) == bad(
        S.RefinementFailed(
            path=(), message="expected a string matching ^[a-z]+$", actual="AB"
        )
    )
    assert E.run_sync_exit(S.decode(percent)(100)) == ok(100)
    assert E.run_sync_exit(S.decode(percent)(101)) == bad(
        S.RefinementFailed(path=(), message="expected a number at most 100", actual=101)
    )
    assert E.run_sync_exit(S.decode(percent)(-1)) == bad(
        S.RefinementFailed(path=(), message="expected a number at least 0", actual=-1)
    )
    assert E.run_sync_exit(S.decode(open_unit)(0)) == bad(  # ty: ignore[invalid-argument-type]
        S.RefinementFailed(
            path=(), message="expected a number greater than 0", actual=0
        )
    )
    assert E.run_sync_exit(S.decode(open_unit)(1)) == bad(  # ty: ignore[invalid-argument-type]
        S.RefinementFailed(path=(), message="expected a number less than 1", actual=1)
    )

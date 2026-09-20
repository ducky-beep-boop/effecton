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

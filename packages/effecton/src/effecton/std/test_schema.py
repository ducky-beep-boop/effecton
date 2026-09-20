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

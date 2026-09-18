---
title: Type checkers
description: effecton officially supports ty. Set up its language server, and learn the two places where Python type checkers struggle with effect types.
---

# Type checkers

An effect's type is its contract: `Effect[A, E, R]` records what it succeeds with, every error it can fail with, and every requirement it still needs. That contract is only as good as the type checker that reads it, and effecton leans on features that Python type checkers support unevenly.

**[ty](https://docs.astral.sh/ty/) is the only officially supported type checker.** effecton is developed and tested against it: the library's type behavior is pinned in ty-checked tests, and every snippet on this site is type-checked by ty at build time. Other checkers can still read effecton code, but they lose precision in the places described under [Type checker limitations](#type-checker-limitations).

## Setup

Add ty as a dev dependency and run it like any other checker:

```sh
uv add --dev ty
uv run ty check
```

### Install the language server

For the best experience, run ty as a language server in your editor, not only as a CLI step. Most of what effecton tells you is in inferred types: the error union left after a `catch`, the requirements left after a `provide`, the value a `yield from` sends back. Hovering an expression shows them while you write, the same way the hovers on this site do, and errors show up as you type instead of in CI.

- **VS Code**: install the [ty extension](https://marketplace.visualstudio.com/items?itemName=astral-sh.ty). It turns off Pylance's language server by default. Keep it that way, because Pylance is built on pyright, which infers some effect types differently (see [Subtracting from unions](#subtracting-from-unions)).
- **Other editors**: point your LSP client at `ty server`. The [ty editor guide](https://docs.astral.sh/ty/editors/) covers Neovim, Zed, PyCharm and others.

## Type checker limitations

Python type checkers struggle with effect types in two places. ty handles the first precisely and needs a little help with the second.

### Subtracting from unions

Handling an error or providing a requirement removes one member from a union type. `catch(RecoverableError)` turns `FatalError | RecoverableError` into `FatalError`, and `provide(E.Random.Protocol)` turns `Random.Protocol | Clock.Protocol` into `Clock.Protocol`:

```python
from dataclasses import dataclass
from typing import final

import effecton as E


@final
@dataclass(frozen=True)
class FatalError(E.EffectonError):
    pass


@final
@dataclass(frozen=True)
class RecoverableError(E.EffectonError):
    pass


# ---cut---
@E.gen
def program() -> E.EffectGen[
    int,
    FatalError | RecoverableError,
    E.Random.Protocol | E.Clock.Protocol,
]:
    rng = yield from E.require(E.Random.Protocol)
    clock = yield from E.require(E.Clock.Protocol)

    roll = yield from rng.randint(1, 4)
    if roll == 1:
        yield from E.fail(FatalError())
    if roll == 2:
        yield from E.fail(RecoverableError())
    return roll


caught = program().catch(RecoverableError)(lambda _: E.success(0))
# ^?

provided = program().provide(E.Random.Protocol)(E.Random.Test())
# ^?
```

Python has no type operator for "this union minus that member". effecton expresses the subtraction by matching a union pattern: the handler's `self` is typed as `Effect[A, T | E2, R]` with the caught class `T` already bound, and the checker solves `E2` to whatever remains. This is why `catch` and `provide` are curried (`catch(T)(handler)`, never `catch(T, handler)`): binding `T` first leaves exactly one unknown in the match, which ty can solve. It is also why errors must be `@final` leaves (see [Error handling](/core/error-handling)): a checker cannot tell a subclass from its base when it subtracts one from a union.

This kind of solving is where checkers differ most. Tested against effecton at the time of writing:

| Checker | `catch` / partial `provide` | Providing the last requirement |
| --- | --- | --- |
| ty | Subtracts precisely | `Never`, so the effect is runnable |
| pyright 1.1.414 | Subtracts precisely | `Unknown`, which hides any requirement composed in later |
| mypy 2.3.1 | Joins the union into its common base, such as `EffectonError`, so nothing is subtracted | Joins into `ImplicitRequirement` |

With mypy, `caught` above is `Effect[int, EffectonError, ...]`: the checker no longer knows which errors are left, and exhaustive handling of the rest becomes impossible.

### Generator syntax needs a return annotation

`@E.gen` programs rely on `yield from`, which runs through the generator's `Generator[Yield, Send, Return]` type. ty checks every `yield from` against the declared `E.EffectGen[A, E, R]`: an effect that fails with an undeclared error, or needs an undeclared requirement, is an `invalid-yield` error. It also types the value each `yield from` sends back. Use `yield from`, not a bare `yield`, which types the sent-back value as `Any`.

What ty does not do yet is infer that type from the body. Without the return annotation, ty types the whole program as `Effect[Unknown, Unknown, Unknown]`. The errors and requirements disappear from the type, and running the program without providing anything is not reported:

```python
import effecton as E


# ---cut---
@E.gen
def roll():  # no return annotation
    rng = yield from E.require(E.Random.Protocol)

    return (yield from rng.randint(1, 6))


program = roll()
# ^?

E.run_sync(program)  # needs Random.Protocol, yet type-checks
```

So always annotate `@E.gen` functions with `E.EffectGen[A, E, R]`. The annotation is the program's contract anyway, and ty then checks the body against it. To enforce this, enable ruff's [`ANN`](https://docs.astral.sh/ruff/rules/#flake8-annotations-ann) rules, which report functions without a return annotation.

---
name: recreating-from-spec
description: Use when a design spec on some branch should be tested for completeness by having a fresh agent rebuild the feature from the spec alone and comparing the result with what shipped. Invoked explicitly as /recreating-from-spec <spec-path> [--from <ref>] [--base <ref>].
disable-model-invocation: true
argument-hint: "<spec-path> [--from <ref>] [--base <ref>]"
---

# Recreating a feature from its spec

CLAUDE.md's bar for a design spec: a fresh agent can rebuild the feature from it alone and pass the existing tests. This skill runs that experiment. You orchestrate; a subagent that has never seen the shipped code does the rebuild; you measure the result against the original and report.

**The implementing subagent must see only the spec and the pre-feature repo.** Every guardrail below exists to keep the shipped implementation out of its reach, including through git.

## Arguments

- `<spec-path>`: path of the spec on `--from` (e.g. `docs/specs/2026-09-20-schema-design.md`).
- `--from <ref>`: ref holding the spec and the shipped implementation. Default: `HEAD`. Check that the spec exists there (`git cat-file -e <from>:<spec-path>`); if not, stop and say which refs do contain it (`git log --all --oneline -- <spec-path>`).
- `--base <ref>`: commit the rebuild starts from; the feature must be absent there. Default: the parent of the first commit on `--from` that touches the spec. Check the default: every file the spec's placement section names must be missing at base (`git cat-file -e <base>:<file>` fails). If one exists, stop and ask for an explicit `--base`.

## Procedure

1. **Read the spec at `--from`** (`git show <from>:<spec-path>`), plus the shipped diff stat (`git diff --stat <base> <from>`). From the spec's placement section list the deliverables: implementation files, test files, exports and registrations, docs page, changeset. Collect the verification commands from every agent guide that governs a deliverable's directory: the root CLAUDE.md, and a nested one such as `docs/CLAUDE.md` when a docs page is a deliverable. These fill the brief.
2. **Isolate.** Create a shallow clone of base so the shipped objects are physically absent, then copy only the spec in:
   ```bash
   REPO=$(git rev-parse --show-toplevel); TOPIC=<spec basename minus date and -design.md>
   WORK=$(dirname "$REPO")/$(basename "$REPO")-recreate-$TOPIC
   git branch recreate-base-$TOPIC <base>
   git clone --depth 1 --single-branch --branch recreate-base-$TOPIC "file://$REPO" "$WORK"
   mkdir -p "$WORK/$(dirname <spec-path>)" && git show <from>:<spec-path> > "$WORK/<spec-path>"
   git -C "$WORK" remote remove origin        # git fetch cannot pull the feature in
   (cd "$WORK" && uv sync --all-packages && uv run ut fix)   # green before hand-off, or stop
   ```
   The spec goes in verbatim, including any prior "Recreation test" section: it is part of the document as committed.
3. **Dispatch one `general-purpose` subagent** with `run_in_background: false`, using the brief in `brief.md` with its placeholders filled. Send it nothing else: no hints, no follow-up corrections, no second attempt. If it asks a question, the answer is "decide and record it in RECREATION_NOTES.md".
4. **Audit the hand-back.** Grep the subagent's report for `git log`, `git show`, `git fetch`, `git diff <ref>`, paths outside `$WORK`, or web searches for the feature. Any hit voids the run: say so in the report and do not score it.
5. **Measure** in `$WORK`, yourself:
   - Run the verification commands again and record the outcome and the rebuild's test count.
   - Copy each test file the original ships into the clone next to the rebuilt one with an `_original` suffix (`git show <from>:<path> > $WORK/<path-with-_original>`). Run pytest on the runtime copies and count pass/fail; run `ty check` on each type pin copy and count diagnostics. Run only those two commands while the copies exist, then delete them.
   - Classify every original-test failure as one of: message wording, path or rendering format, semantic difference, missing API, spec-silent behavior, original test asserts something the spec never states.
   - Diff the public surface: names exported by the rebuilt module versus the original.
6. **Report** with the shape below, then stop. Leave `$WORK` and the base branch in place; the report names both and the two commands that delete them. Do not edit the spec: propose the sentences that would close each gap and let the user apply them.

## Report shape

1. **Verdict**: sufficient or insufficient, one sentence, tied to the numbers.
2. **Isolation**: base commit, clone path, audit result.
3. **Verification**: each command with pass/fail; rebuild test count.
4. **Original tests against the rebuild**: passed/total for runtime tests, diagnostics count for type pins, then a table of failures by category with the spec sentence or gap behind each.
5. **Public surface differences**.
6. **Decisions the spec left open** and **Spec problems**, copied from `RECREATION_NOTES.md`.
7. **Proposed spec edits**: one bullet per gap, sentence-level, not applied.
8. **Cleanup commands**.

## Common mistakes

| Mistake | Why it breaks the experiment |
|---|---|
| Worktree instead of shallow clone | Worktrees share `.git/objects`; `git show <from>:file` exposes the shipped code. |
| Base chosen by merge-base only | On a squashed main the spec and feature land together; the parent of the spec commit is the base. |
| Copying the plan or notes in with the spec | Tests the plan, not the spec. The spec is the only description. |
| Pre-applying tooling changes from the shipped diff | Ruff or ty config the feature needed is part of what the spec must convey. |
| Fixing the rebuild yourself before measuring | Scores your knowledge, not the spec. Measure first; fixes belong to the spec. |
| Reporting only the rebuild's own tests | A rebuild always passes its own tests. The original tests are the metric. |

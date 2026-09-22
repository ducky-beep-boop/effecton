# Brief for the implementing subagent

Fill every `{PLACEHOLDER}`, then send it as the whole prompt. Add nothing about the shipped implementation.

```
Implement the design in {SPEC_PATH} in the repository at {WORK}. Run every
command from that directory and never leave it. Read that file, CLAUDE.md,
and the existing modules under {SIBLING_DIRS} for conventions before
writing anything. Do not run git log, git show, git diff against a ref,
git fetch, or read any other checkout or branch; do not search the web
for this feature. The spec is your only description of it.

Deliverables:
{DELIVERABLES}

Work test-first. Where the spec is silent on a detail you need (an exact
error message, a path format, an ordering), pick something reasonable and
list every such decision in a file named RECREATION_NOTES.md at the repo
root under the heading "Decisions the spec left open". Under the heading
"Spec problems" in the same file, list anything you found contradictory,
impossible to type-check, or wrong. Never ask a question: decide, record
the decision, and continue.

Verify with {VERIFY_COMMANDS}; all must pass. Commit when done and report
the test counts, the list of files you created or changed, and the full
contents of RECREATION_NOTES.md.
```

Placeholders:

- `{SPEC_PATH}`: the spec's path inside the clone, as given on the command line.
- `{WORK}`: absolute path of the shallow clone.
- `{SIBLING_DIRS}`: the directories the spec's placement section puts new files in (e.g. `packages/effecton/src/effecton/std/`).
- `{DELIVERABLES}`: one `- ` bullet per file, export, registration, docs page and changeset the spec's placement section requires, with exact paths.
- `{VERIFY_COMMANDS}`: the verification commands collected in step 1, backticked, one per guide (e.g. `` `uv run ut fix`, `uv run api-reference`, and `pnpm typecheck && pnpm build` in `docs/` ``).

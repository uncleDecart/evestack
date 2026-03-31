---
name: eve-commit
description: EVE project commit discipline — linter, SPDX headers, commit message format, and DCO sign-off. Use this whenever the user is committing to lf-edge/eve or a fork of it, even if they just say "commit my changes" or "make a commit". Also applies when eve-pr needs a commit made.
argument-hint: [optional context about what changed]
---

# EVE Commit Discipline

Enforces the EVE project's mandatory commit rules. Use this standalone when
committing outside of a full PR workflow, or it will be invoked automatically
by the `eve-pr` skill.

## Step 0: Resolve committer identity

```bash
GIT_NAME=$(git config user.name)
GIT_EMAIL=$(git config user.email)
```

Use `$GIT_NAME <$GIT_EMAIL>` for the `Signed-off-by` line throughout.

---

## Step 1: Run the linter

Before staging anything:

```bash
make MYETUS_VERBOSE=Y mini-yetus
```

Fix all errors before proceeding. Do not commit if the linter fails.

---

## Step 2: SPDX headers

Every **new** file must have this at the very top:

```
# Copyright (c) <year> Zededa, Inc.
# SPDX-License-Identifier: Apache-2.0
```

- Go files: use `//` comment style
- `<year>`: creation year only (e.g. `2026`) for new files
- For modified existing files: keep the original start year through current year (e.g. `2018-2026`)

---

## Step 3: Stage and commit

```bash
git add <files>
git commit -s -m "$(cat <<EOF
<subsystem>: <short summary in imperative mood, ≤72 chars>

<Body: explain what changed and why, not how. Wrap at ~72 chars.>

Signed-off-by: $GIT_NAME <$GIT_EMAIL>
EOF
)"
```

Note: the heredoc delimiter is unquoted (`EOF`, not `'EOF'`) so that `$GIT_NAME` and `$GIT_EMAIL` expand to the values resolved in Step 0.

### Commit message rules (non-negotiable)

- **Subject**: `subsystem: summary` — e.g. `build: add mk/linuxkit.mk`
- **Body**: mandatory and non-empty — a one-liner with no body is not acceptable
- **Never** include Jira ticket keys (e.g. `EV-1234`) in the message
- Always use `-s` (DCO sign-off)

### Subsystem prefix guide

Derive the subsystem from the primary directory or component changed:
`pkg/`, `cmd/`, `build:`, `docs:`, `api:`, etc.

---

## Step 4: Fixup discipline

Squash fixups immediately — never leave them as separate commits on the branch.
Amend while still on the branch:

```bash
git commit --amend -s
```

---

## Force-push rule

When amending or updating an existing branch:

```bash
git push --force-with-lease origin <branch>
```

Never use plain `--force`.

---
name: context-save
description: Save working context so any future session can pick up without losing a beat. Captures git state, decisions made, and remaining work. Use when asked to "save progress", "save state", "context save", or "save my work". Pair with /context-restore to resume later.
argument-hint: "[title]"
---

# context-save — Save Working Context

Capture the full working context so that any future session can resume without
losing a beat via `/context-restore`.

**Hard gate:** do NOT implement code changes. This skill captures state only.

---

## Step 0: Check EVE Brain

```bash
BRAIN_ENABLED=false
BRAIN_DIR=""
[ -f "$HOME/.evestack/config" ] && source "$HOME/.evestack/config"
BRAIN_DIR="${BRAIN_DIR:-$HOME/.evestack/brain}"
[ "$BRAIN_ENABLED" = "true" ] && [ -d "$BRAIN_DIR/.git" ] && BRAIN_READY=true || BRAIN_READY=false
echo "BRAIN_READY=$BRAIN_READY"
```

If `BRAIN_READY=true`, contexts are written to the brain repo. Otherwise they
go to `~/.evestack/contexts/`. The behavior is identical — only the destination
changes.

---

## Detect command

Parse the user's input:

- `/context-save` or `/context-save <title>` → **Save**
- `/context-save list` → **List**

If the user provides a title (e.g. `/context-save auth refactor`), use it.
Otherwise infer a short title from the current work.

If the user types `/context-save resume` or `/context-save restore`, tell them:
"Use `/context-restore` instead — save and restore are separate skills."

---

## Save flow

### Step 1: Gather git state

```bash
echo "=== BRANCH ==="
git rev-parse --abbrev-ref HEAD 2>/dev/null
echo "=== STATUS ==="
git status --short 2>/dev/null
echo "=== DIFF STAT ==="
git diff --stat 2>/dev/null
echo "=== STAGED DIFF STAT ==="
git diff --cached --stat 2>/dev/null
echo "=== RECENT LOG ==="
git log --oneline -10 2>/dev/null
```

### Step 2: Summarize context

Using the gathered state plus conversation history, produce a summary covering:

1. **What's being worked on** — the high-level goal or feature
2. **Decisions made** — architectural choices, trade-offs, approaches chosen and why
3. **Remaining work** — concrete next steps in priority order
4. **Notes** — gotchas, blocked items, open questions, things tried that didn't work

Infer a concise title (3–6 words) if the user didn't provide one.

### Step 3: Compute destination and write the context file

```bash
# Prefer owner/repo from git remote URL (collision-safe across forks);
# fall back to basename when no remote is configured.
_REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
if [ -n "$_REMOTE_URL" ]; then
  REPO=$(printf '%s' "$_REMOTE_URL" \
    | sed 's|.*[:/]\([^/]*/[^/]*\)\.git$|\1|;s|.*[:/]\([^/]*/[^/]*\)$|\1|' \
    | tr '/' '-' | tr -cd 'a-zA-Z0-9._-')
fi
[ -z "${REPO:-}" ] && REPO=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null || echo "unknown")

if [ "$BRAIN_READY" = "true" ]; then
  CONTEXT_DIR="$BRAIN_DIR/contexts/$REPO"
else
  CONTEXT_DIR="$HOME/.evestack/contexts/$REPO"
fi

mkdir -p "$CONTEXT_DIR"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
```

Sanitize the title to a filename slug (lowercase, spaces to hyphens, only
`a-z0-9.-`, max 60 chars). Write a new file — never overwrite existing ones.

File format:

```markdown
---
status: in-progress
branch: {current branch}
timestamp: {ISO-8601 timestamp}
files_modified:
  - path/to/file1
  - path/to/file2
---

## Working on: {title}

### Summary

{1–3 sentences: high-level goal and current progress}

### Decisions Made

{Bulleted list of architectural choices and reasoning}

### Remaining Work

{Numbered list of concrete next steps, priority order}

### Notes

{Gotchas, blocked items, open questions, failed approaches}
```

`files_modified` comes from `git status --short` — relative paths from repo root.

### Step 4: Commit to brain (if brain is ready)

```bash
if [ "$BRAIN_READY" = "true" ]; then
  cd "$BRAIN_DIR"
  git add "contexts/"
  git commit -m "context: $REPO — $TITLE_SLUG ($(date +%Y-%m-%d))"
  echo "BRAIN_COMMITTED=true"
fi
```

### Step 5: Confirm to the user

```
CONTEXT SAVED
════════════════════════════════════════
Title:    {title}
Branch:   {branch}
File:     {path}
Modified: {N} files
Storage:  {brain repo | local ~/.evestack/contexts/}
════════════════════════════════════════

Restore later with /context-restore.
```

If brain is ready, add: "Run /brain-sync to push to remote."

---

## List flow

```bash
_REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
if [ -n "$_REMOTE_URL" ]; then
  REPO=$(printf '%s' "$_REMOTE_URL" \
    | sed 's|.*[:/]\([^/]*/[^/]*\)\.git$|\1|;s|.*[:/]\([^/]*/[^/]*\)$|\1|' \
    | tr '/' '-' | tr -cd 'a-zA-Z0-9._-')
fi
[ -z "${REPO:-}" ] && REPO=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null || echo "unknown")

if [ "$BRAIN_READY" = "true" ]; then
  CONTEXT_DIR="$BRAIN_DIR/contexts/$REPO"
else
  CONTEXT_DIR="$HOME/.evestack/contexts/$REPO"
fi

find "$CONTEXT_DIR" -maxdepth 1 -name "*.md" -type f 2>/dev/null | sort -r
```

By default show contexts for the **current branch** only. With `--all`, show
all branches.

Read frontmatter of each file to extract `status`, `branch`, `timestamp`. Parse
the title from the filename (part after the timestamp prefix).

Present as a table:

```
SAVED CONTEXTS ({branch} branch)
════════════════════════════════════════
#  Date        Title                    Status
─  ──────────  ───────────────────────  ───────────
1  2026-04-24  nim-debug                in-progress
2  2026-04-23  vault-tpm-fix            completed
════════════════════════════════════════
```

If no saved contexts exist: "No saved contexts yet. Run `/context-save` to save
your current working state."

---

## Rules

- Never modify code. Only read state and write the context file.
- Always include the branch name in frontmatter.
- Saved files are append-only. Each save creates a new file.
- Infer the title from git state and conversation — only ask if it genuinely
  cannot be determined.

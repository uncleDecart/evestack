---
name: context-restore
description: Restore working context saved earlier by /context-save. Loads the most recent saved state so you can pick up where you left off — even across sessions and machines. Use when asked to "resume", "restore context", "where was I", or "pick up where I left off". Pair with /context-save.
---

# context-restore — Restore Saved Working Context

Load the most recent saved context and present it clearly so work can resume
without losing a beat.

**Hard gate:** do NOT implement code changes. This skill only reads saved
context files and presents the summary.

**Default: load the most recent saved context across ALL branches.** A context
saved on one branch can be resumed from another — cross-branch resume is
intentional.

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

If `BRAIN_READY=true`, contexts are read from the brain repo. Otherwise from
`~/.evestack/contexts/`. Behavior is identical — only the source changes.

---

## Detect command

Parse the user's input:

- `/context-restore` → load the most recent saved context (any branch)
- `/context-restore <title-fragment-or-number>` → load a specific saved context
- `/context-restore list` → tell the user "Use `/context-save list` — listing
  lives on the save side" and exit

---

## Restore flow

### Step 1: Find saved contexts

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

if [ ! -d "$CONTEXT_DIR" ]; then
  echo "NO_CONTEXTS"
else
  FILES=$(find "$CONTEXT_DIR" -maxdepth 1 -name "*.md" -type f 2>/dev/null | sort -r | head -20)
  [ -z "$FILES" ] && echo "NO_CONTEXTS" || echo "$FILES"
fi
```

Candidates include every `.md` file regardless of branch — branch is in
frontmatter, not used for filtering here.

### Step 2: Load the right file

- If the user specified a title fragment or number: find the matching file.
- Otherwise: load the **first file from `sort -r`** — newest
  `YYYYMMDD-HHMMSS` prefix is the canonical "most recent."

Read the chosen file and present:

```
RESUMING CONTEXT
════════════════════════════════════════
Title:    {title}
Branch:   {branch from frontmatter}
Saved:    {timestamp, human-readable}
Status:   {status}
Source:   {brain repo | local}
════════════════════════════════════════

### Summary
{summary from saved file}

### Remaining Work
{remaining work items}

### Notes
{notes}
```

If the current branch differs from the saved context's branch, note it:
"This context was saved on `{saved-branch}`. You are currently on
`{current-branch}`. You may want to switch branches before continuing."

### Step 3: Offer next steps

After presenting the context, ask the user:

- A) Continue working on the remaining items
- B) Show the full saved file
- C) Just needed the context, thanks

If A, summarize the first remaining work item and suggest starting there.

---

## If no saved contexts exist

Tell the user: "No saved contexts yet. Run `/context-save` first to save your
current working state, then `/context-restore` will find it."

If `BRAIN_READY=true`, also note: "Contexts from other machines will appear here
after a `/brain-sync`."

---

## Rules

- Never modify code. Only read saved files and present them.
- Search across all branches by default — do not filter by current branch.
- "Most recent" means the `YYYYMMDD-HHMMSS` filename prefix, not filesystem
  mtime (mtime drifts across copies and is not authoritative).

---
name: brain-init
description: Enable or disable EVE Brain — the per-developer private repository that stores context saves, learnings, and RCA reports across sessions and machines. Use whenever the user says "enable brain", "disable brain", "setup brain", "configure brain", "init brain", or asks why their contexts or learnings aren't persisting. When enabling, checks if the brain repo exists and walks the user through first-time setup if not.
---

# brain-init — EVE Brain Setup

EVE Brain is a private git repository that stores your personal EVE institutional
memory: context saves, operational learnings, and RCA report summaries. It travels
with you across machines.

Config lives at `~/.evestack/config`. All brain-aware skills source this file.

---

## Step 1: Read current config

```bash
BRAIN_ENABLED=false
BRAIN_REPO=""
BRAIN_DIR=""
[ -f "$HOME/.evestack/config" ] && source "$HOME/.evestack/config"
BRAIN_DIR="${BRAIN_DIR:-$HOME/.evestack/brain}"
echo "BRAIN_ENABLED=$BRAIN_ENABLED"
echo "BRAIN_REPO=$BRAIN_REPO"
echo "BRAIN_DIR=$BRAIN_DIR"
[ -d "$BRAIN_DIR/.git" ] && echo "REPO_EXISTS=true" || echo "REPO_EXISTS=false"

# Portability file — URL-only, written by brain-init, safe to copy to new machines
[ -f "$HOME/.evestack-brain-remote.txt" ] && \
  PORTABLE_REMOTE=$(cat "$HOME/.evestack-brain-remote.txt" | tr -d '[:space:]') || \
  PORTABLE_REMOTE=""
echo "PORTABLE_REMOTE=$PORTABLE_REMOTE"
```

If `BRAIN_ENABLED=false` and `PORTABLE_REMOTE` is non-empty, this is likely a
new machine where the user copied `~/.evestack-brain-remote.txt` from another
machine. Offer to use that URL automatically as the default for cloning.

---

## Step 2: Decide what to do

### If user wants to **disable** brain

Set `BRAIN_ENABLED=false` in config:

```bash
mkdir -p "$HOME/.evestack"
# Preserve other config values, just flip BRAIN_ENABLED
if [ -f "$HOME/.evestack/config" ]; then
  sed -i.bak 's/^BRAIN_ENABLED=.*/BRAIN_ENABLED=false/' "$HOME/.evestack/config"
  grep -q '^BRAIN_ENABLED=' "$HOME/.evestack/config" || echo "BRAIN_ENABLED=false" >> "$HOME/.evestack/config"
else
  echo "BRAIN_ENABLED=false" > "$HOME/.evestack/config"
fi
```

Confirm: "EVE Brain disabled. Your existing brain data is untouched at
`$BRAIN_DIR`. Re-enable anytime with `/brain-init`."

---

### If brain is already enabled and repo exists

Report status:

```bash
cd "$BRAIN_DIR"
echo "=== BRAIN STATUS ==="
echo "Repo: $(git remote get-url origin 2>/dev/null || echo 'local only')"
echo "Branch: $(git rev-parse --abbrev-ref HEAD)"
echo "Last commit: $(git log --oneline -1)"
echo ""
echo "=== CONTENTS ==="
find contexts learnings.jsonl rca-reports -maxdepth 2 2>/dev/null | head -30
echo ""
LEARNING_COUNT=$(wc -l < learnings.jsonl 2>/dev/null | tr -d ' ')
RCA_COUNT=$(find rca-reports -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
CONTEXT_COUNT=$(find contexts -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
echo "Learnings: $LEARNING_COUNT"
echo "RCA reports: $RCA_COUNT"
echo "Context saves: $CONTEXT_COUNT"
```

---

### If brain is not configured or `BRAIN_ENABLED=false`

Walk the user through setup.

#### Step 2a: Ask for repo URL

Ask the user:
- A) Create a new private repo automatically (requires `gh` CLI)
- B) I already have a repo — provide the URL

If A, create it:
```bash
gh repo create eve-brain --private --description "EVE Brain — personal EVE knowledge base" 2>&1
BRAIN_REPO="https://github.com/$(gh api user --jq .login)/eve-brain.git"
echo "BRAIN_REPO=$BRAIN_REPO"
```

If B, prompt for the URL and set `BRAIN_REPO=<provided URL>`.

#### Step 2b: Clone or init the repo

Set `BRAIN_DIR="$HOME/.evestack/brain"` (or let user override).

```bash
BRAIN_DIR="$HOME/.evestack/brain"
mkdir -p "$HOME/.evestack"

if [ -d "$BRAIN_DIR/.git" ]; then
  echo "ALREADY_CLONED=true"
elif [ -n "$BRAIN_REPO" ]; then
  git clone "$BRAIN_REPO" "$BRAIN_DIR" 2>&1
  echo "CLONED=true"
else
  # Local-only brain (no remote)
  mkdir -p "$BRAIN_DIR"
  git -C "$BRAIN_DIR" init
  echo "LOCAL_INIT=true"
fi
```

#### Step 2c: Initialize repo structure

Only create files that don't already exist:

```bash
cd "$BRAIN_DIR"

# contexts/ directory
mkdir -p contexts rca-reports

# learnings.jsonl — append-only, one JSON object per line
[ -f learnings.jsonl ] || touch learnings.jsonl

# Register union merge driver for learnings.jsonl so concurrent appends
# from two machines auto-resolve instead of producing a git conflict.
# The built-in 'union' driver concatenates both sides — correct for
# append-only JSONL where entries are never modified, only added.
git config merge.union.driver true 2>/dev/null || true
if [ ! -f .gitattributes ] || ! grep -q 'learnings.jsonl' .gitattributes 2>/dev/null; then
  echo "learnings.jsonl merge=union" >> .gitattributes
fi

# README
if [ ! -f README.md ]; then
  cat > README.md << 'EOF'
# EVE Brain

Personal EVE knowledge base — context saves, operational learnings, and RCA report summaries.

Managed by [evestack](https://github.com/pabramov/evestack) skills:
- `/context-save` / `/context-restore` — session continuity
- `/brain-learn` — add a learning or quirk
- `/brain-sync` — push/pull to remote
- `/root-cause-analysis` — RCA reports saved here automatically

To set up on a new machine: copy `~/.evestack-brain-remote.txt` from this
machine and run `/brain-init` — it will detect the URL and clone automatically.
EOF
fi

# Initial commit if repo is empty
if [ -z "$(git log --oneline 2>/dev/null)" ]; then
  git add -A
  git commit -m "brain: initial structure"
  [ -n "$(git remote)" ] && git push -u origin HEAD 2>&1 || true
fi
```

#### Step 2d: Write config and portability file

```bash
mkdir -p "$HOME/.evestack"
cat > "$HOME/.evestack/config" << EOF
BRAIN_ENABLED=true
BRAIN_REPO=${BRAIN_REPO}
BRAIN_DIR=${BRAIN_DIR}
EOF
echo "CONFIG_WRITTEN=true"

# Portability file — URL only, no secrets. Copy this to a new machine and
# brain-init will detect it and offer to clone automatically.
if [ -n "${BRAIN_REPO}" ]; then
  echo "${BRAIN_REPO}" > "$HOME/.evestack-brain-remote.txt"
  echo "REMOTE_FILE_WRITTEN=$HOME/.evestack-brain-remote.txt"
fi
```

#### Step 2e: Confirm

```
EVE BRAIN ENABLED
════════════════════════════════════════
Repo:   {BRAIN_REPO or "local only"}
Local:  {BRAIN_DIR}
════════════════════════════════════════

Your brain is ready. Going forward:
- /context-save and /context-restore use the brain repo
- /root-cause-analysis saves RCA summaries automatically
- /brain-learn adds operational learnings
- /brain-sync pushes and pulls changes

Run /brain-sync to keep it in sync across machines.
```

---

## Rules

- Never delete existing brain data.
- If `gh` is not available, skip the auto-create option and ask for a URL or offer local-only mode.
- Local-only mode (no remote) is valid — the user can add a remote later with `git remote add origin <url>`.

---
name: autoupdate
description: Check for and apply updates to evestack EVE development skills from the remote repository. Use whenever the user runs /autoupdate, mentions updating skills, asks if skills are up to date, or wants to pull the latest evestack changes.
---

# autoupdate

Check for and apply updates to evestack from the remote repository.

## How this skill locates evestack

Your context includes a line: `Base directory for this skill: <PATH>`. That path is a symlink into the evestack directory. From it:

```bash
SKILL_BASE="<path from context>"                        # e.g. ~/.claude/skills/autoupdate
EVESTACK_DIR="$(dirname "$(readlink "$SKILL_BASE")")"   # e.g. ~/.claude/skills/evestack
SKILLS_PARENT="$(dirname "$SKILL_BASE")"                # e.g. ~/.claude/skills
SKILL_NAME="$(basename "$SKILL_BASE")"                  # autoupdate or evestack-autoupdate
```

Prefix mode detection: if `$SKILL_NAME` starts with `evestack-`, pass `--prefix` to setup; otherwise pass `--no-prefix`.

Local install detection: if `$SKILLS_PARENT` is not `$HOME/.claude/skills`, it's a local (project) install — pass `--local` to setup and `cd` to the project root (two levels above `SKILLS_PARENT`) before calling it.

## Commands to run

Run these phases in order. Stop and report clearly on any failure.

### Phase 0 — Path setup

```bash
SKILL_BASE="<extracted from context>"
EVESTACK_DIR="$(dirname "$(readlink "$SKILL_BASE")")"
SKILLS_PARENT="$(dirname "$SKILL_BASE")"
SKILL_NAME="$(basename "$SKILL_BASE")"

if [[ "$SKILL_NAME" == evestack-* ]]; then
  SETUP_PREFIX="--prefix"
else
  SETUP_PREFIX="--no-prefix"
fi

if [[ "$SKILLS_PARENT" == "$HOME/.claude/skills" ]]; then
  LOCAL_FLAG=""
else
  LOCAL_FLAG="--local"
  PROJECT_ROOT="$(cd "$SKILLS_PARENT/../.." && pwd)"
fi
```

### Phase 1 — Pre-flight checks

```bash
# Verify git repo
if ! git -C "$EVESTACK_DIR" rev-parse --git-dir > /dev/null 2>&1; then
  echo "evestack at $EVESTACK_DIR is not a git repository."
  echo "Auto-update requires a git clone. To update manually, re-clone:"
  echo "  git clone https://github.com/pabramov/evestack.git $EVESTACK_DIR && $EVESTACK_DIR/setup"
  exit 0
fi

# Check for detached HEAD
BRANCH=$(git -C "$EVESTACK_DIR" symbolic-ref --short HEAD 2>/dev/null) || {
  echo "evestack is in detached HEAD state — cannot update safely."
  echo "Fix: cd $EVESTACK_DIR && git checkout main"
  exit 0
}

# Warn about local modifications (don't block — let --ff-only handle conflicts)
DIRTY=$(git -C "$EVESTACK_DIR" status --porcelain 2>/dev/null)
if [[ -n "$DIRTY" ]]; then
  echo "Warning: evestack has local modifications:"
  git -C "$EVESTACK_DIR" status --short
  echo ""
  echo "Proceeding with pull (--ff-only). If it fails, resolve manually in $EVESTACK_DIR"
  echo ""
fi
```

### Phase 2 — Fetch and compare

```bash
echo "Checking for updates..."
if ! git -C "$EVESTACK_DIR" fetch origin 2>&1; then
  echo "Could not reach remote. Check your network connection."
  REMOTE_URL=$(git -C "$EVESTACK_DIR" remote get-url origin 2>/dev/null || echo "not configured")
  echo "Remote: $REMOTE_URL"
  exit 0
fi

LOCAL=$(git -C "$EVESTACK_DIR" rev-parse HEAD)
REMOTE=$(git -C "$EVESTACK_DIR" rev-parse @{u} 2>/dev/null) || {
  echo "No upstream tracking branch configured."
  echo "Fix: cd $EVESTACK_DIR && git branch --set-upstream-to=origin/main $BRANCH"
  exit 0
}

if [[ "$LOCAL" == "$REMOTE" ]]; then
  echo "evestack is up to date ($(git -C "$EVESTACK_DIR" rev-parse --short HEAD))."
  exit 0
fi

BEHIND=$(git -C "$EVESTACK_DIR" rev-list HEAD..@{u} --count)
echo "evestack is $BEHIND commit(s) behind. Updating..."
echo ""
```

### Phase 3 — Show what will change

```bash
# Skill names at local HEAD
LOCAL_SKILLS=$(git -C "$EVESTACK_DIR" ls-tree --name-only HEAD | while read -r name; do
  [[ -f "$EVESTACK_DIR/$name/SKILL.md" ]] && echo "$name"
done | sort)

# Skill names at remote HEAD
REMOTE_SKILLS=$(git -C "$EVESTACK_DIR" ls-tree --name-only @{u} | while read -r name; do
  git -C "$EVESTACK_DIR" cat-file -e "@{u}:$name/SKILL.md" 2>/dev/null && echo "$name"
done | sort)

NEW_SKILLS=$(comm -13 <(echo "$LOCAL_SKILLS") <(echo "$REMOTE_SKILLS") | tr '\n' ' ' | xargs)
REMOVED_SKILLS=$(comm -23 <(echo "$LOCAL_SKILLS") <(echo "$REMOTE_SKILLS") | tr '\n' ' ' | xargs)
CHANGED_SKILLS=$(git -C "$EVESTACK_DIR" diff --name-only HEAD @{u} \
  | grep '/' | cut -d/ -f1 | sort -u \
  | grep -Fxv -f <(printf '%s\n' $NEW_SKILLS $REMOVED_SKILLS) \
  | tr '\n' ' ' | xargs) 2>/dev/null || CHANGED_SKILLS=""

echo "Changes in this update:"
[[ -n "$NEW_SKILLS" ]]     && echo "  + New:     $NEW_SKILLS"
[[ -n "$REMOVED_SKILLS" ]] && echo "  - Removed: $REMOVED_SKILLS"
[[ -n "$CHANGED_SKILLS" ]] && echo "  ~ Updated: $CHANGED_SKILLS"
echo ""
```

### Phase 4 — Pull

```bash
if ! git -C "$EVESTACK_DIR" pull --ff-only 2>&1; then
  echo "Pull failed (local changes conflict with remote)."
  echo "Resolve manually: cd $EVESTACK_DIR && git pull"
  exit 0
fi
echo "Pull successful ($(git -C "$EVESTACK_DIR" rev-parse --short HEAD))."
echo ""
```

### Phase 5 — Re-run setup

setup handles pruning of stale symlinks and registration of new ones automatically.

```bash
echo "Updating skill symlinks..."
if [[ -n "$LOCAL_FLAG" ]]; then
  (cd "$PROJECT_ROOT" && "$EVESTACK_DIR/setup" $SETUP_PREFIX --local)
else
  "$EVESTACK_DIR/setup" $SETUP_PREFIX
fi
```

### Phase 6 — Session implications

```bash
echo ""
echo "evestack update complete."
echo ""

NEEDS_RESTART=false

if [[ -n "$NEW_SKILLS" ]]; then
  echo "  New skills ($NEW_SKILLS) are registered but not yet available as slash commands."
  NEEDS_RESTART=true
fi

if [[ -n "$REMOVED_SKILLS" ]]; then
  echo "  Removed skills ($REMOVED_SKILLS): symlinks cleaned up."
  echo "  If loaded this session, they remain in context until you restart."
fi

if [[ -n "$CHANGED_SKILLS" ]]; then
  echo "  Updated skills ($CHANGED_SKILLS): new content is on disk."
  echo "  The version loaded at session start is still active — changes apply next session."
  NEEDS_RESTART=true
fi

if [[ "$NEEDS_RESTART" == true ]]; then
  echo ""
  echo "Restart your Claude Code session to activate the changes above."
fi
```

## Corner cases

| Situation | Response |
|---|---|
| Not a git repo | Warn with re-clone instructions, stop |
| No network | Warn, show remote URL, stop |
| Already up to date | Report current SHA, stop |
| Detached HEAD | Warn with `git checkout main`, stop |
| No upstream branch | Warn with `git branch --set-upstream-to`, stop |
| Local modifications | Warn, proceed; `--ff-only` will fail cleanly if there's a conflict |
| New skill added | Note: restart required to use as slash command |
| Skill deleted | Symlink pruned by setup; warn if it was loaded this session |
| Skill content updated | New content on disk immediately; session sees it next restart |

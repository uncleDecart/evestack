---
name: brain-sync
description: Push and pull EVE Brain — sync your personal EVE knowledge base (context saves, learnings, RCA reports) with the remote repository. Use when asked to "sync brain", "push brain", "pull brain", or "update brain". Keeps the brain in sync across machines.
---

# brain-sync — Sync EVE Brain

Push local brain changes to the remote and pull any changes from other machines.

---

## Step 1: Check brain is configured

```bash
BRAIN_ENABLED=false
BRAIN_DIR=""
[ -f "$HOME/.evestack/config" ] && source "$HOME/.evestack/config"
BRAIN_DIR="${BRAIN_DIR:-$HOME/.evestack/brain}"

echo "BRAIN_ENABLED=$BRAIN_ENABLED"
[ -d "$BRAIN_DIR/.git" ] && echo "REPO_EXISTS=true" || echo "REPO_EXISTS=false"
[ -n "$(git -C "$BRAIN_DIR" remote 2>/dev/null)" ] && echo "HAS_REMOTE=true" || echo "HAS_REMOTE=false"
```

If `BRAIN_ENABLED=false`: tell the user "EVE Brain is disabled. Run `/brain-init`
to enable it." and stop.

If `REPO_EXISTS=false`: tell the user "Brain repo not found at `$BRAIN_DIR`.
Run `/brain-init` to set it up." and stop.

If `HAS_REMOTE=false`: tell the user "Brain has no remote configured — nothing
to sync. To add a remote: `git -C $BRAIN_DIR remote add origin <url>`." and stop.

---

## Step 2: Pull

```bash
cd "$BRAIN_DIR"
echo "=== PULL ==="
git fetch origin 2>&1
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "@{u}" 2>/dev/null || echo "")
if [ "$LOCAL" = "$REMOTE" ]; then
  echo "PULL_STATUS=up-to-date"
else
  git pull --ff-only 2>&1 && echo "PULL_STATUS=updated" || echo "PULL_STATUS=conflict"
fi
```

If `PULL_STATUS=conflict`: tell the user "Pull failed — local and remote have
diverged. Resolve manually: `cd $BRAIN_DIR && git pull`." and stop.

---

## Step 3: Secret scan

Before committing, scan text files in the brain for credential-shaped content.
Run only if there are changes to commit.

```bash
cd "$BRAIN_DIR"
if [ -n "$(git status --porcelain)" ]; then
  python3 - "$BRAIN_DIR" << 'PYEOF'
import os, re, sys
from pathlib import Path

PATTERNS = [
    (r'AKIA[0-9A-Z]{16}',                                          'AWS access key'),
    (r'ghp_[0-9A-Za-z]{36}',                                       'GitHub PAT'),
    (r'gho_[0-9A-Za-z]{36}',                                       'GitHub OAuth token'),
    (r'github_pat_[0-9A-Za-z_]{59}',                               'GitHub fine-grained PAT'),
    (r'sk-[A-Za-z0-9]{48}',                                        'OpenAI key'),
    (r'-----BEGIN [A-Z ]+PRIVATE KEY-----',                        'PEM private key'),
    (r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',   'JWT'),
    (r'"(?:api_key|authorization|bearer|token)"\s*:\s*"[A-Za-z0-9._\-]{20,}"',
                                                                    'credential in JSON'),
]

brain_dir = sys.argv[1]
hits = []
for root, dirs, files in os.walk(brain_dir):
    dirs[:] = [d for d in dirs if d != '.git']
    for fname in files:
        if not fname.endswith(('.md', '.jsonl', '.json', '.txt')):
            continue
        try:
            content = Path(os.path.join(root, fname)).read_text(errors='replace')
        except Exception:
            continue
        for pattern, label in PATTERNS:
            if re.search(pattern, content):
                hits.append(f"{label}: {os.path.relpath(os.path.join(root, fname), brain_dir)}")

if hits:
    print("SECRET_SCAN=blocked")
    for h in hits:
        print(f"  HIT: {h}")
else:
    print("SECRET_SCAN=clean")
PYEOF
else
  echo "SECRET_SCAN=skipped (nothing to commit)"
fi
```

If `SECRET_SCAN=blocked`: stop immediately. Tell the user which files matched,
e.g. "Credential found in rca-reports/EV-1234.md — redact before syncing."
Do NOT commit or push until the user resolves it.

---

## Step 4: Push

```bash
cd "$BRAIN_DIR"
echo "=== STATUS ==="
git status --short

if [ -n "$(git status --porcelain)" ]; then
  echo "=== COMMITTING ==="
  git add -A
  git commit -m "brain: sync $(date -u +%Y-%m-%dT%H:%M:%SZ)" 2>&1
  echo "COMMIT_STATUS=committed"
else
  echo "COMMIT_STATUS=nothing-to-commit"
fi

echo "=== PUSH ==="
git push 2>&1 && echo "PUSH_STATUS=ok" || echo "PUSH_STATUS=failed"
```

---

## Step 5: Report

```
BRAIN SYNC COMPLETE
════════════════════════════════════════
Pull:  {up-to-date | updated | skipped}
Push:  {committed + pushed | nothing to commit | failed}
Repo:  {remote URL}
════════════════════════════════════════
```

If push failed, show the git error and suggest: `cd $BRAIN_DIR && git push`.

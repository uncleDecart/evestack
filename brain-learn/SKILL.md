---
name: brain-learn
description: Add an operational learning or device quirk to EVE Brain. Use when the user says "remember this", "add a learning", "note this quirk", "brain learn", or "save this for later". Also invoked automatically by root-cause-analysis after a successful investigation. Learnings are tagged with EVE version, component, and source so future sessions can find them.
argument-hint: "[learning text]"
---

# brain-learn — Add a Learning to EVE Brain

Record an operational discovery — a device quirk, a gotcha, a pattern that
recurs — so future sessions can find it.

---

## Step 1: Check brain is configured

```bash
BRAIN_ENABLED=false
BRAIN_DIR=""
[ -f "$HOME/.evestack/config" ] && source "$HOME/.evestack/config"
BRAIN_DIR="${BRAIN_DIR:-$HOME/.evestack/brain}"

echo "BRAIN_ENABLED=$BRAIN_ENABLED"
[ -d "$BRAIN_DIR/.git" ] && echo "REPO_EXISTS=true" || echo "REPO_EXISTS=false"
```

If `BRAIN_ENABLED=false` or `REPO_EXISTS=false`: tell the user "EVE Brain is not
set up. Run `/brain-init` first." and stop.

---

## Step 2: Gather the learning

If the user provided text as an argument, use it directly.

Otherwise gather from conversation context:

- **Insight** — the core finding, stated concisely (1–3 sentences)
- **Tags** — relevant labels: EVE version (e.g. `14.5.x`), component (`nim`,
  `vaultmgr`, `domainmgr`, `kvm`, `xen`, `kubevirt`), hardware platform,
  cloud/enterprise name
- **Source** — Jira ticket ID, archive name, or "observed" if from conversation
- **EVE version** — if known; omit if general

Ask only for what's genuinely missing. Infer tags from context.

---

## Step 3: Append to learnings.jsonl

Build the JSON entry and append it:

```bash
ENTRY=$(cat << EOF
{"date":"$(date -u +%Y-%m-%d)","insight":"INSIGHT_TEXT","tags":["TAG1","TAG2"],"eve_version":"EVE_VERSION","source":"SOURCE"}
EOF
)
echo "$ENTRY" >> "$BRAIN_DIR/learnings.jsonl"
echo "APPENDED=true"
```

Replace `INSIGHT_TEXT`, `TAG1`, `TAG2`, `EVE_VERSION`, `SOURCE` with actual
values. Omit `eve_version` key entirely if unknown — don't write empty strings.

---

## Step 4: Local commit

```bash
cd "$BRAIN_DIR"
git add learnings.jsonl
git commit -m "learn: $(date -u +%Y-%m-%d) — $(echo "$ENTRY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['insight'][:60])" 2>/dev/null || echo "new entry")"
echo "COMMITTED=true"
```

---

## Step 5: Confirm

```
LEARNING SAVED
════════════════════════════════════════
{insight — first 80 chars}
Tags:    {tags joined by space}
Source:  {source}
════════════════════════════════════════

Run /brain-sync to push to remote.
```

---

## Rules

- `learnings.jsonl` is append-only. Never modify existing entries.
- Keep insights concrete and actionable — "X causes Y on Z hardware, workaround
  is W" is a good learning. Vague observations are not.
- Do not push automatically — that's `/brain-sync`'s job.

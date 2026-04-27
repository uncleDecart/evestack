---
name: root-cause-analysis
description: Root cause analysis for EVE device issues. Given a Jira ticket ID, fetches the ticket via Atlassian MCP, locates any associated info-collect log archives (attached to ticket or provided locally), runs full EVE log triage using the eve-log-analyze skill, and produces a comprehensive report that links log evidence to ticket symptoms. Use this whenever someone runs /root-cause-analysis, provides an EVE Jira ticket ID (like EV-1234), mentions an info-collect archive alongside a bug ticket, asks why an EVE device or app is failing/broken, or wants to investigate an EVE device issue end-to-end. Trigger even if the user just says "investigate EV-1234" or "why is this device broken" with a ticket reference.
---

# EVE Root Cause Analysis

Combine a Jira ticket's context with EVE log analysis to identify root causes quickly and produce actionable reports. This skill orchestrates two things: pulling structured context from Jira, and running deep log triage — then merging both into a single coherent narrative.

## Arguments

```
/root-cause-analysis <TICKET_ID> [ARCHIVE_PATH]
```

- `TICKET_ID` — Jira ticket key, e.g. `EV-1730`
- `ARCHIVE_PATH` — optional local path to an info-collect directory or `.tar.gz`. If omitted, look for attachments on the ticket.

---

## Step 1 — Fetch the Jira ticket

Run these two calls in parallel:

1. `mcp__claude_ai_Atlassian__getAccessibleAtlassianResources` — get the `cloudId` for the site (usually `*.atlassian.net`).
2. `mcp__claude_ai_Atlassian__getJiraIssue` with `issueIdOrKey: TICKET_ID`, `responseContentFormat: "markdown"` — get the full ticket.

Extract and hold onto:
- Summary, description, steps to reproduce
- Affected device name(s), and any "works on device X / fails on device Y" comparisons — these are gold for root cause isolation
- Attachment filenames — look for `eve-info-*`, `info-collect-*`, `device-logs-*`, `*.tar.gz`, `*.gz`
- Comments — may contain follow-up findings, workarounds, or a second reporter's data
- Status, assignee, priority, labels

---

## Step 2 — Locate the info-collect archive

Check in this order:

1. **Argument provided**: if `ARCHIVE_PATH` was given, use it. Skip the rest of this step.

2. **Ticket attachments**: scan attachment filenames for patterns: `eve-info-*`, `info-collect-*`, `device-logs-*`, `*.tar.gz`. If found, try fetching via `mcp__claude_ai_Atlassian__fetchAtlassian` using the attachment content URL. Binary/large files may not transfer cleanly — if that happens, tell the user the filename and ask them to download it and re-run with the path.

3. **Ticket body/comments**: scan for local file paths or download links the reporter may have pasted.

4. **Nothing found**: proceed with ticket-only analysis (Step 4), but flag the limitation prominently in the report. A ticket-only analysis can still produce probable causes from the error text.

If the archive is a `.tar.gz`, extract first:
```bash
tar -xzf <file> -C "$(dirname <file>)"
ARCHIVE="$(dirname <file>)/$(basename <file> .tar.gz)"
```

---

## Step 3 — Analyze the logs

Read and execute the full workflow from:

```
~/.claude/skills/eve-log-analyze/SKILL.md
```

Run all steps against `ARCHIVE`:
- **Step 1**: detect EVE version → set `GH_BASE` for source links
- **Step 2**: fast triage — `diag.out`, reboot-reason, watchdog, panics, memory, SMART, df-h, service liveness, network
- **Step 3**: assess whether triage is sufficient
- **Step 4**: deep analysis if needed (`extract-logs.py --summary`, then `--last-boot --errors-only`)

**Tool discipline**: use `Read` and `Grep` for all file reads — not `cat`/`tail`/`grep` via Bash. Reserve Bash for commands that genuinely need a shell (tar extraction, python3 for SMART JSON, extract-logs.py). Combining many reads into one large Bash script causes the tool to run in the background, losing output and forcing retries.

As you go, actively cross-reference log findings against what the ticket says:
- Does the error message in the logs match what the reporter pasted?
- Does the UUID in the logs match the app/device in the ticket?
- If the ticket says "works on device X", does anything in the logs (IOMMU topology, chipset, EVE version) explain why?

Keep notes on all findings — you'll weave them into the report.

---

## Step 4 — Synthesize the report

Merge Jira context and log findings into this format:

---

## Root Cause Analysis: \<TICKET_ID\>

**Ticket**: \<ID\> · \<issue type\> · \<status\> · Assignee: \<name\>
**Device**: \<device name from ticket\> — \<hardware model from dmidecode/logs\>
**EVE Version**: \<from archive\>
**Cloud**: \<controller URL from run/config/server\>
**Enterprise**: \<enterprise/org name, or "unknown"\>
**Collection date**: \<from archive name or log timestamps\>
**App/service affected**: \<from diag.out or ticket\>

### Summary
2–4 sentences covering: what failed, the underlying cause, and how it surfaced to the user.

### Root Cause
**\<Primary finding, stated plainly\>** — Confidence: High / Medium / Low

Explain the mechanism — trace from the root constraint (hardware limitation, misconfiguration, software bug) through to the user-visible symptom. Don't just restate the error; explain *why* it happened.

### Evidence Chain
Link each log finding to a ticket symptom:
- `<log finding>` → confirms ticket error: *"quote from ticket"*
- `<log finding>` → explains device-specific failure (if ticket says "works elsewhere")
- Source: `<file in archive>`

### Why the Error is Misleading *(include when the surface symptom obscures the real cause)*
Explain the gap — e.g. "QMP timeout looks like a connectivity issue but QEMU never started due to VFIO rejection." This section saves hours for whoever investigates next.

### Recommendations

**Immediate** — fix or workaround for this specific ticket

**EVE improvement** — what EVE could change to surface a better error, pre-validate the config, or prevent this class of issue entirely

### Source References
- \<description\>: `\<GH_BASE\>/path/to/file.go#L\<line\>`

### Timeline *(include when sequence of events matters)*
Chronological key events from the logs.

---

## Step 5 — Save to EVE Brain

After producing the report, check whether EVE Brain is configured:

```bash
BRAIN_ENABLED=false
BRAIN_DIR=""
[ -f "$HOME/.evestack/config" ] && source "$HOME/.evestack/config"
BRAIN_DIR="${BRAIN_DIR:-$HOME/.evestack/brain}"
[ "$BRAIN_ENABLED" = "true" ] && [ -d "$BRAIN_DIR/.git" ] && BRAIN_READY=true || BRAIN_READY=false
echo "BRAIN_READY=$BRAIN_READY"
```

If `BRAIN_READY=true`:

### 5a. Save RCA report

Write the full report to `$BRAIN_DIR/rca-reports/<TICKET_ID>.md` (or
`rca-reports/<TICKET_ID>-<date>.md` if no ticket ID). Then commit:

```bash
cd "$BRAIN_DIR"
git add "rca-reports/"
git commit -m "rca: $TICKET_ID — $(date +%Y-%m-%d)"
echo "RCA_SAVED=true"
```

### 5b. Offer to save key findings as a learning

If the root cause is clearly identified (confidence High or Medium), ask the
user: "Save the root cause as a brain learning so future sessions recognize
this pattern?"

If yes, invoke the `/brain-learn` skill with the root cause summary, tagging
it with the EVE version and affected component from the report.

Tell the user: "RCA saved to brain. Run `/brain-sync` to push to remote."

---

## Handling multiple archives

If the ticket has multiple info-collect archives (different time periods, different devices):
- Analyze each one separately
- Note differences: EVE version, IOMMU topology, error pattern
- Synthesize across them — if device A fails and device B succeeds, the difference *is* the root cause

## Handling no archive

If no archive is available, do a ticket-only analysis:
- Extract the verbatim error message from the description/comments
- Identify the EVE service that produced it (domainmgr, nim, vaultmgr, etc.)
- Reason about probable causes from the error pattern
- State clearly: "Analysis based on ticket only — no logs available. Confidence: Low/Medium."
- Recommend what info-collect data would be needed to confirm

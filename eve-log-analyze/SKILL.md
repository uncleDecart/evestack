---
name: eve-log-analyze
description: Analyze an EVE info-collect archive (directory or tar.gz) to find the root cause of a device issue. Use whenever the user shares or mentions an EVE log bundle, info-collect archive, device logs, or asks why an EVE device crashed, rebooted, lost connectivity, or behaved unexpectedly. Points findings to source files in the correct version of lf-edge/eve on GitHub.
argument-hint: <path-to-archive-or-directory>
---

# EVE Log Analysis

Analyze an EVE info-collect archive (directory or `.tar.gz`) to find the root
cause of a problem. Works in two stages: fast triage (seconds) then deep log
analysis (minutes) if needed.

The `extract-logs.py` script in this skill's directory handles log extraction.
Locate it from the `Base directory for this skill: <PATH>` line in your context:
```bash
SKILL_DIR="<path from context>"   # e.g. ~/.claude/skills/eve-log-analyze
```

---

## Step 0: Locate the archive

The archive path comes from the skill argument — shown as `ARGUMENTS: <path>` in
your context. If no argument was provided, ask the user for the path.

The path is either:
- A directory (e.g. `eve-info-v40-d309dd5b-...`) — use directly
- A `.tar.gz` file — extract first: `tar -xzf <file> -C "$(dirname <file>)"`, then use the extracted directory

```bash
ARCHIVE="<value from ARGUMENTS>"
```

Set `ARCHIVE` for all subsequent steps.

---

## Step 1: EVE version → GitHub base URL

```bash
cat "$ARCHIVE/root-run/eve-release"
# Example output: 14.5.2-lts-kvm-amd64
```

Parse the version:
1. Strip the hypervisor suffix: `-kvm`, `-xen`, `-kubevirt`
2. Strip the architecture suffix: `-amd64`, `-arm64`
3. Result is the git ref, e.g. `14.5.2-lts`

Set:
```
EVE_VERSION=<stripped version>
GH_BASE=https://github.com/lf-edge/eve/blob/$EVE_VERSION
```

Use `$GH_BASE/<file>#L<line>` for all source links in the report.

---

## Step 2: Fast triage (always run — takes seconds)

Read these files in order. Each one may reveal the root cause without needing
to parse the compressed logs.

### 2a. System summary
```bash
cat "$ARCHIVE/root-run/diag.out"
```
Look for: connectivity status, vault/attest state, number of apps running/starting.

### 2b. Reboot reason
```bash
cat "$ARCHIVE/persist-log/reboot-reason.log"
cat "$ARCHIVE/persist-log/reboot-stack.log"
```
A non-empty `reboot-reason.log` or `reboot-stack.log` is usually the primary
root cause. Stack trace in `reboot-stack.log` → find the goroutine that panicked.

### 2c. Watchdog
```bash
cat "$ARCHIVE/persist-log/watchdog.log"
```
Look for `BootReasonWatchdogPid` or process names that stopped responding.
The last process listed before the watchdog trigger is the suspect.

### 2d. Go panics / backtraces
```bash
zcat "$ARCHIVE/pillar-backtraces.gz" 2>/dev/null | head -200
zcat "$ARCHIVE/pillar-memory-backtraces.gz" 2>/dev/null | head -200
ls "$ARCHIVE/persist-newlog/panicStacks/" 2>/dev/null
# If panicStacks is non-empty:
ls "$ARCHIVE/persist-newlog/panicStacks/"
cat "$ARCHIVE/persist-newlog/panicStacks/"*
```

### 2e. Memory pressure
```bash
cat "$ARCHIVE/root-run/memory-monitor.log" | tail -50
cat "$ARCHIVE/persist-memory-monitor-output" | head -50
```
Look for OOM kills, memory threshold crossings, process evictions.

### 2f. Disk health (SMART)
```bash
python3 -c "
import json, sys
data = json.load(open('$ARCHIVE/SMART_details.json'))
# Handle both single-disk and multi-disk format
disks = data if isinstance(data, list) else [data]
for d in disks:
    dev = d.get('device', {}).get('name', '?')
    model = d.get('model_name', '?')
    status = d.get('smart_status', {})
    attrs = d.get('ata_smart_attributes', {}).get('table', [])
    bad = [a for a in attrs if a.get('raw', {}).get('value', 0) > 0 and
           a.get('id') in [5, 10, 184, 187, 188, 196, 197, 198, 199]]
    print(f'{dev} ({model}): passed={status.get(\"passed\")} bad_attrs={[a[\"name\"] for a in bad]}')
"
```
IDs 5, 187, 196, 197, 198 are reallocated/pending/uncorrectable sectors — critical.

### 2g. Disk space
```bash
cat "$ARCHIVE/df-h"
```
Look for partitions at 100% or `/persist` near full.

### 2h. Service liveness
```bash
cat "$ARCHIVE/root-run/watchdog.log" | tail -30
# Check for missing .touch files (services that didn't check in)
ls "$ARCHIVE/root-run/"*.touch 2>/dev/null | xargs -I{} basename {} .touch | sort
```

### 2i. Network state
```bash
cat "$ARCHIVE/root-run/diag.out"          # already read above
cat "$ARCHIVE/network/ifconfig"
cat "$ARCHIVE/network/ip-route-show-table-all"
```

---

## Step 3: Assess — is triage sufficient?

If any of the above clearly explains the issue (panic, OOM kill, disk full,
SMART failure, watchdog kill of a known service), **go directly to Step 5**.

If the cause is unclear, continue to Step 4.

---

## Step 4: Deep log analysis

The `extract-logs.py` script is at `$SKILL_DIR/extract-logs.py` (using `$SKILL_DIR` resolved above).

### 4a. Quick summary of key events (fast, no large file)
```bash
python3 $SKILL_DIR/extract-logs.py "$ARCHIVE" --summary
```
This prints only boot timestamps and annotated events (vault, TPM, attest, reboot)
to stdout. Good for understanding the timeline without reading a huge log.

### 4b. Last-boot errors only (focused, manageable output)
```bash
python3 $SKILL_DIR/extract-logs.py "$ARCHIVE" \
  --last-boot --errors-only --context 10 \
  -o /tmp/eve-errors.txt
wc -l /tmp/eve-errors.txt
head -500 /tmp/eve-errors.txt
```
If the file is large, read it in sections. Focus on the first error cluster
and the last error cluster — those are usually most relevant.

### 4c. Full last-boot log (if still unclear)
```bash
python3 $SKILL_DIR/extract-logs.py "$ARCHIVE" \
  --last-boot --annotate --max-lines 100000 \
  -o /tmp/eve-lastboot.txt
```
Read in chunks: beginning (startup sequence), around any annotated events, and end.

### 4d. Individual service logs (quick alternatives)
Before running the full parser, check the live service logs — these are often enough:
```bash
tail -100 "$ARCHIVE/root-run/pillar.log"
tail -100 "$ARCHIVE/root-run/nim.log"          # network interface manager
tail -100 "$ARCHIVE/root-run/zedagent.log"     # controller communication
tail -100 "$ARCHIVE/root-run/vaultmgr.log"     # vault/TPM
tail -100 "$ARCHIVE/root-run/domainmgr.log"    # VM/container lifecycle
tail -100 "$ARCHIVE/root-run/baseosmgr.log"    # base OS updates
```

---

## Step 5: Root cause report

Structure the report as:

```
## EVE Log Analysis Report

**EVE Version**: <version>
**Device UUID**: <from archive name or root-run/eve.id>
**Collection date**: <from archive name or dmesg timestamps>

### Summary
<1–3 sentence description of what happened>

### Root Cause
<Primary finding with confidence: High / Medium / Low>

Evidence:
- <finding 1> — source: <file in archive>
- <finding 2> — source: <file in archive>

### Source References
Point to the relevant EVE source files using $GH_BASE:
- <description>: $GH_BASE/<path/to/file.go>#L<line>

### Timeline
<Chronological sequence of key events if relevant>

### Recommendations
<What to check or fix>
```

### How to find source references

After identifying an error message or function name:
1. Search for the exact string in the EVE repo using GitHub search:
   `https://github.com/lf-edge/eve/search?q=<error+string>&type=code`
   or use `gh api` to search
2. Identify the file and line number
3. Link using `$GH_BASE/<file>#L<line>`

Common files by symptom:
| Symptom | Likely source files |
|---------|-------------------|
| Vault locked / TPM failure | `pkg/vaultmgr/`, `pkg/tpmmgr/` |
| Network not coming up | `pkg/nim/`, `pkg/pillar/cmd/nim/` |
| App not starting | `pkg/domainmgr/`, `pkg/zedmanager/` |
| Controller not reachable | `pkg/zedagent/`, `pkg/zedclient/` |
| OOM / memory pressure | `pkg/memory-monitor/`, `pkg/pillar/` |
| Base OS update stuck | `pkg/baseosmgr/` |
| Watchdog kill | `cmd/watchdog/`, `pkg/watchdog/` |
| Log pipeline issues | `pkg/newlogd/` |

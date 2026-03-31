---
name: eve-pr
description: Full PR workflow for lf-edge/eve — Jira ticket, git branch, commit, push, GitHub PR, and Jira update. Use this whenever the user wants to open a PR against lf-edge/eve, create or reference a Jira ticket for EVE work, prepare a branch for EVE, or do any part of the EVE contribution workflow — even if they only mention one step like "create a PR" or "update the ticket".
argument-hint: [jira-ticket-key or description of the change]
---

# EVE Pull Request Workflow

End-to-end workflow: Jira → branch → commit → PR → Jira update.
Commit discipline is handled by the `eve-commit` skill (invoked in Step 2).

## Prerequisites

### Atlassian MCP server

Jira operations require the Atlassian MCP server. It is registered automatically
by the evestack `setup` script, but you can also add it manually:

```json
// ~/.claude/settings.json
{
  "mcpServers": {
    "atlassian": {
      "type": "http",
      "url": "https://mcp.atlassian.com/v1/mcp"
    }
  }
}
```

**Auth**: OAuth 2.1 — no API tokens or env vars needed. On first Jira tool use,
Claude Code opens a browser window to authorize your Atlassian account. After
that, credentials are stored locally.

**Requirements**:
- Atlassian Cloud account with access to `zededa.atlassian.net`
- Permission to create/edit issues and add comments in the `EV` project

> If `getAccessibleAtlassianResources` returns 401, ignore it — the skill
> already falls through to using `zededa.atlassian.net` directly.

### GitHub CLI

`gh` must be authenticated for PR creation:

```bash
gh auth status   # check
gh auth login    # if not authenticated
```

## Constants

| Key | Value |
|-----|-------|
| Jira cloud | `zededa.atlassian.net` |
| Jira project | `EV` |
| GitHub upstream | `lf-edge/eve` |
| Default branch | `master` |
| PR base | `lf-edge/eve:master` |
| Jira PR field | `customfield_11237` (ADF format) |
| Jira "In Review" transition | `111` |

---

## Step 0: Resolve user identity

```bash
GH_USER=$(gh api user --jq .login 2>/dev/null \
  || git config user.name | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
GIT_NAME=$(git config user.name)
GIT_EMAIL=$(git config user.email)
```

`$GH_USER` is used for branch names and `head` in PR creation.
`$GIT_NAME / $GIT_EMAIL` are used for Signed-off-by.

---

## Step 1: Jira ticket

Ask the user: **new ticket or existing?**

### Option A — Create new ticket

Ask for: epic key (e.g. `EV-1998`), summary, description (generate from context if not given).

Create with `createJiraIssue`:
- `cloudId`: `zededa.atlassian.net`
- `projectKey`: `EV`
- `issueTypeName`: `Task` (unless user specifies)
- `parent`: epic key
- `assignee_account_id`: resolve with `atlassianUserInfo`

> If `getAccessibleAtlassianResources` returns 401, ignore it and use
> `zededa.atlassian.net` directly.

### Option B — Use existing ticket

Ask for the ticket key, fetch with `getJiraIssue`, read description for context.

Store the ticket key as `$JIRA_KEY` for use in Step 4.

---

## Step 2: Prepare git branch

```bash
git stash
git fetch upstream
git checkout master
git pull upstream master
git checkout -b $GH_USER/<descriptive-branch-name>
```

- Branch name: `$GH_USER/<descriptive-name>` — keep it short and descriptive
- If `git pull` fails due to `index.lock`: `rm -f .git/index.lock` and retry

---

## Step 3: Make changes and commit

Apply the changes (or instruct the user to), then follow the **`eve-commit`** skill
rules for linting, SPDX headers, and commit message formatting. The full rules are
in `eve-commit/SKILL.md` — follow them in their entirety here rather than having
the user run a separate command.

Key rules (from `eve-commit`):
- Run `make MYETUS_VERBOSE=Y mini-yetus` before staging anything — fix all errors first
- Every new file needs a Zededa SPDX header
- Commit with `-s` (DCO sign-off); body is mandatory
- Never include `$JIRA_KEY` in the commit message

---

## Step 4: Push and create PR

```bash
git push origin $GH_USER/<branch-name>
```

Create PR with `create_pull_request`:
- `owner`: `lf-edge`, `repo`: `eve`
- `head`: `$GH_USER:$GH_USER/<branch-name>`
- `base`: `master`
- `title`: same as commit subject line (no Jira key)

### PR body template

Follow `.github/pull_request_template.md`:

```markdown
# Description

<Clear description of what changed and why>

## How to test and validate this PR

<Steps to verify the change works>

## Changelog notes

<User-facing description for release notes, or "No user-facing changes">

## PR Backports

- 16.0-stable: <To be backported / No, reason>
- 14.5-stable: <To be backported / No, reason>
- 13.4-stable: <To be backported / No, reason>

## Checklist

- [x] I've provided a proper description
- [ ] I've added the proper documentation
- [ ] I've tested my PR on amd64 device
- [ ] I've tested my PR on arm64 device
- [x] I've written the test verification instructions
- [ ] I've set the proper labels to this PR

- [x] I've checked the boxes above, or I've provided a good reason why I didn't
  check them.
```

- Ask the user about backport decisions if not clear from context
- Omit "PR dependencies" section unless there are actual dependencies
- Omit backport checklist items for non-backport PRs
- **Never** include `$JIRA_KEY` in the PR title or body

---

## Step 5: Update Jira ticket

After the PR is created, do **all three**:

**1. Set the "Pull Requests" field** via `editJiraIssue` on `$JIRA_KEY`:

```json
{
  "customfield_11237": {
    "type": "doc",
    "version": 1,
    "content": [{
      "type": "paragraph",
      "content": [{
        "type": "text",
        "text": "https://github.com/lf-edge/eve/pull/<NUMBER>",
        "marks": [{"type": "link", "attrs": {"href": "https://github.com/lf-edge/eve/pull/<NUMBER>"}}]
      }]
    }]
  }
}
```

If the field already has content (other PRs), **append** — do not overwrite.

**2. Add a comment** with the PR link via `addCommentToJiraIssue`.

**3. Transition to "In Review"** via `transitionJiraIssue` with `{"id": "111"}`.

---

## Step 6: Offer cleanup

Ask the user: switch back to the previous branch and pop the stash, or stay?

```bash
# If switching back:
git checkout -
git stash pop
```

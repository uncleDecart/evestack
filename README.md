# evestack

A curated collection of Claude Code skills for EVE development.

Inspired by [gstack](https://github.com/garrytan/gstack) — a skill library that turns Claude Code into a structured engineering team. evestack follows the same installation pattern but provides a custom set of skills tailored to EVE development workflows.

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and configured
- Git

## Installation

### Machine-level install (recommended)

Clone evestack into your Claude skills directory and run setup:

```bash
git clone --single-branch --depth 1 https://github.com/pabramov/evestack.git ~/.claude/skills/evestack && cd ~/.claude/skills/evestack && ./setup
```

This makes all evestack skills available globally across your projects as `/evestack-<skill>`.

### Project-local install

To vendor evestack into a specific project:

```bash
cp -r ~/.claude/skills/evestack .claude/skills/evestack
rm -rf .claude/skills/evestack/.git
cd .claude/skills/evestack && ./setup --local
```

### Options

| Flag | Description |
|------|-------------|
| `--no-prefix` | Use short skill names (`/myskill` instead of `/evestack-myskill`) |
| `--host codex` | Install for Codex instead of Claude Code |
| `--local` | Install into the current project instead of globally |

## Adding skills

Each skill is a directory at the repo root containing a `SKILL.md` file:

```
evestack/
  my-skill/
    SKILL.md        # Skill definition (required)
    ...             # Any supporting files
  another-skill/
    SKILL.md
```

After adding a skill, re-run `./setup` to register it.

## Updating

```bash
cd ~/.claude/skills/evestack && git pull && ./setup
```

## License

MIT

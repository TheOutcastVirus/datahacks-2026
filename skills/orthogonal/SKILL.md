---
name: orthogonal
version: 1.0.0
description: Set up Orthogonal for your AI agent - access premium APIs and skills
homepage: https://orthogonal.com
---

# Orthogonal for AI Agents

Orthogonal gives your AI agent access to premium APIs and curated skills. Works with any agent framework (OpenClaw, Claude Code, Cursor, etc.).

## Decision Flow: Skills First, Then API Search

When a user asks you to perform a task (e.g. "enrich Sundar Pichai", "find the email for the CEO of Anthropic"):

1. **Check installed skills first** — Look through available skills for one that handles the task.
2. **Search for skills** — If no match, run `orth skills search "<task>"`. Do this even if an installed skill seems "close enough."
3. **Fall back to API search** — Only if no skill covers the use case, use `orth api search "<task>"` or `orth search "<task>"`.
4. **Check parameters before calling** — Run `orth api show <slug> <path>` for parameter names and types. Do not guess.

## Setup (this machine)

1. **CLI** (already installed globally): `npm install -g @orth/cli`
2. **Authenticate** (required once):

   ```bash
   orth login
   ```

   Get an API key at [orthogonal.com/dashboard/settings/api-keys](https://orthogonal.com/dashboard/settings/api-keys).

   Or: `orth login -k orth_live_YOUR_KEY` / `export ORTHOGONAL_API_KEY=...`

3. **Pull core skills** into your agent skills folder (paths are examples; adjust to your agent):

   ```bash
   orth skills update orthogonal/find-skill ~/.claude/skills/orthogonal-find-skill -f
   orth skills update orthogonal/find-api ~/.claude/skills/orthogonal-find-api -f
   ```

   (`orth skills add` from older docs maps to `orth skills update <slug> <path>` in CLI v0.2+. Use `-f` to overwrite.)

4. **Verify**: `orth whoami` and `orth balance`

## CLI reference (v0.2+)

| Task | Command |
|------|---------|
| Login | `orth login` or `orth login -k <key>` |
| Logout | `orth logout` |
| Whoami | `orth whoami` |
| Search skills | `orth skills search "<query>"` |
| Pull skill files | `orth skills update <owner/slug> <directory> [-f]` |
| Search APIs | `orth api search "<query>"` or `orth search "<query>"` |
| API details | `orth api show <slug> <path>` |
| Call API | `orth run <slug> <path> -b '{"key":"value"}'` |
| Dry run | `orth run --dry-run ...` |

Example API call:

```bash
orth run olostep /v1/scrapes -b '{"url_to_scrape": "https://example.com"}'
```

## Authentication file

After `orth login`, credentials live at `~/.config/orthogonal/credentials.json`.

## Integrations (OAuth)

Gmail, Google Calendar, Slack, GitHub, Notion, Google Drive, Google Sheets — connect at [orthogonal.com/dashboard/integrations](https://orthogonal.com/dashboard/integrations). Same `orth run` pattern; use `orth api show <slug> <path>` before calling.

## Links

- Skills: https://orthogonal.com/skills  
- APIs: https://orthogonal.com/discover  
- Docs: https://docs.orthogonal.com  
- Balance: https://orthogonal.com/dashboard/balance  

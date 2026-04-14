# Knowledge Frontend and Xiaohongshu Collection

This document describes the new knowledge-base frontend bridge and Xiaohongshu collection pipeline.

## Obsidian as Knowledge Frontend

The knowledge vault is now scaffolded under the workspace knowledge root and can be used as an Obsidian vault frontend.

Current vault layout:

- `raw/<source>/<domain>/`
- `parsed/<source>/<domain>/`
- `canonical/archive/<domain>/<source>/`
- `canonical/concepts/<domain>/`
- `gist/`
- `synthesis/topics/`
- `synthesis/fusion/`
- `inbox/`
- `collections/xiaohongshu/`
- `research/xiaohongshu/`
- `research/expansion_queue/`
- `AGENTS.md`
- `index.md`
- `log.md`

Obsidian integration is intentionally lightweight:
- we do not require Obsidian for backend storage
- we use Obsidian CLI only as an optional frontend and operator surface
- the same vault can still be read and written directly by filesystem-backed knowledge code

The scaffold now also initializes a minimal maintenance surface:
- `AGENTS.md` for knowledge-organization and update rules
- `index.md` as the canonical navigation entrypoint
- `log.md` as an append-only maintenance record
- `gist/` as a reserved high-density retrieval layer above the wiki surface

Config keys:

```json
{
  "knowledge": {
    "enabled": true,
    "root": "~/.nanobot/workspace/knowledge",
    "obsidian": {
      "enabled": true,
      "command": "obsidian",
      "vaultPath": "~/.nanobot/workspace/knowledge",
      "autoScaffold": true
    }
  }
}
```

CLI commands:

- `nanobot knowledge status`
- `nanobot knowledge obsidian scaffold`
- `nanobot knowledge obsidian search "agent memory"`
- `nanobot knowledge obsidian open canonical/example.md`

## Xiaohongshu Collection

The system now supports a dedicated Xiaohongshu collection path via the external `xhs` CLI.

Reference used for the integration contract:
- PyPI package page for `xiaohongshu-cli` with documented commands such as
  `xhs search`, `xhs read`, and `xhs comments`

Config keys:

```json
{
  "knowledge": {
    "xiaohongshu": {
      "enabled": true,
      "command": "xhs",
      "autoCollectSharedLinks": true,
      "collectComments": true,
      "collectCommentsAll": false,
      "activeDefaultLimit": 3,
      "passiveAllowedChannels": ["discord"]
    },
    "expansion": {
      "enabled": true,
      "autoMaintainOnShare": true,
      "autoQueueOnIngest": false,
      "autoRunOnIngest": false,
      "maxQueriesPerJob": 3,
      "maxLinksPerJob": 8,
      "allowWebSearch": false
    }
  }
}
```

### Passive Collection

When a user message contains a Xiaohongshu URL:

1. the personalization gateway detects the URL
2. if `xhs` is available, the note is fetched with `xhs read`
3. optional comments are fetched with `xhs comments`
4. the payload is normalized into layered artifacts:
   - `raw`
   - `parsed`
   - `canonical`
5. low-level artifacts are classified into a domain such as `finance`, `paper`, or `llm`
6. if `autoMaintainOnShare` is enabled, the share is treated as a knowledge-maintenance event:
   - an expansion job is queued automatically
   - the worker writes `synthesis/fusion/`
   - the worker refreshes `gist/`
   - the worker updates `index.md` and `log.md`
7. if explicit promotion is requested, an expansion job is queued even when automatic maintenance is disabled
8. promoted jobs materialize into `synthesis/fusion/`
9. the turn log records the resulting knowledge activity

If `xhs` is unavailable, the URL is queued into:

- `knowledge/inbox/xiaohongshu_url_queue.jsonl`

### Active Collection

You can actively scan a topic with:

- `nanobot knowledge xhs scan-topic "agentic rl" --sort latest --limit 3`

If `xhs` is unavailable, the scan request is queued into:

- `knowledge/inbox/xiaohongshu_topic_queue.jsonl`

The command also emits a compact research note under:

- `knowledge/research/xiaohongshu/`

## New CLI Commands

- `nanobot knowledge status`
- `nanobot knowledge obsidian scaffold`
- `nanobot knowledge obsidian search "agent memory"`
- `nanobot knowledge obsidian open canonical/example.md`
- `nanobot knowledge xhs status`
- `nanobot knowledge xhs collect-url "<url>"`
- `nanobot knowledge xhs collect-url "<url>" --queue-expansion`
- `nanobot knowledge xhs scan-topic "agentic rl" --sort latest --limit 3`
- `nanobot knowledge xhs scan-topic "agentic rl" --sort latest --limit 3 --queue-expansion`
- `nanobot knowledge expand enqueue-note canonical/archive/paper/xiaohongshu/example.md`
- `nanobot knowledge expand run`
- `nanobot knowledge expand run --with-search`

## Current Boundaries

Implemented:
- CLI bridge
- passive link detection
- active topic scan entry point
- filesystem-backed vault persistence
- layered artifact generation for Xiaohongshu ingests with low-level default archiving
- domain-aware low-level routing for archive knowledge
- automatic share-time maintenance path
- explicit expansion-queue generation
- explicit synthesis/fusion promotion
- expansion worker with optional web search, gist refresh, and index/log maintenance
- Discord-first passive collection defaults
- auto archive into `raw/<source>/<domain>/`, `parsed/<source>/<domain>/`, and `canonical/archive/<domain>/<source>/` inside the vault
- expansion queue persistence and completion tracking

Not implemented yet:
- periodic scheduler-driven topic scans
- retrieval of KB notes back into online personalization candidates
- ranking/overlay updates from reward assignment

## Background Fusion and Expansion

After a Xiaohongshu post is archived, the system can optionally create a background expansion job.

Queue files:

- `knowledge/inbox/expansion_jobs.jsonl`
- `knowledge/inbox/expansion_done.jsonl`

Generated notes:

- `knowledge/research/expansion_queue/`
- `knowledge/synthesis/fusion/`

Behavior:

- On Discord passive share ingest:
  - archive raw/parsed/canonical notes
  - if `autoMaintainOnShare` is enabled, run the maintenance path automatically
  - otherwise, keep the older archive-only behavior unless explicit promotion is requested
- For explicit promotion:
  - run `nanobot knowledge xhs collect-url "<url>" --queue-expansion`
  - or run `nanobot knowledge expand enqueue-note <vault-relative-path>`
  - then run `nanobot knowledge expand run`
- For heavier enrichment:
  - optionally run `nanobot knowledge expand run --with-search` if web search is enabled

The expansion worker currently:
- classifies outbound links as papers / code / blogs / other
- trims and normalizes suggested follow-up queries
- builds a traceable fusion note with `derived_from`, `domain`, and optional cross-domain bridges
- optionally runs lightweight web search over selected queries

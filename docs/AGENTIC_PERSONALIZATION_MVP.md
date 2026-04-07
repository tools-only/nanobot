# Agentic Personalization Architecture MVP

This document describes the current architecture skeleton added for layered personalization, layered memory, and future knowledge-base integration.

## Scope

This version focuses on infrastructure, not full product behavior.

Implemented:
- typed personalization middleware
- layered knowledge runtime skeleton
- layered memory runtime skeleton
- extensible context-variable provider registry
- shortlist-first online evaluation path
- richer trajectory logging for future reward assignment

Not implemented yet:
- concrete knowledge-source adapters for real platforms
- persistent layered memory backend
- real asynchronous reward judge / reward updater
- knowledge retrieval in the online path
- learned reranker or contextual bandit

## Design Goals

- Keep knowledge base and reward loosely coupled.
- Keep reward mostly posterior and asynchronous.
- Preserve the ability to add any context variable later:
  prompt, memory, tool, MCP, skill, search policy, knowledge page, section, or source.
- Avoid evaluating the full combinatorial context space online.
- Support future heterogeneous knowledge sources with different MCP dependencies and data formats.

## Runtime Overview

Current online flow:

1. Build `RuntimeState`
2. Generate typed candidates
3. Shortlist a small candidate set per surface
4. Run lightweight online comparison only on shortlisted items
5. Route selected items into adaptive context
6. Run normal agent loop
7. Log trajectory, proxy metrics, feedback signals, and pending reward request
8. Materialize layered memory units from the completed turn

## New Architecture Layers

### 1. Personalization Middleware

Files:
- `nanobot/personalization/contracts.py`
- `nanobot/personalization/gateway.py`
- `nanobot/personalization/candidate_generators.py`
- `nanobot/personalization/providers.py`
- `nanobot/personalization/shortlist.py`
- `nanobot/personalization/online_eval.py`
- `nanobot/personalization/router.py`
- `nanobot/personalization/assembler.py`
- `nanobot/personalization/store.py`
- `nanobot/personalization/feedback.py`
- `nanobot/personalization/telemetry.py`
- `nanobot/personalization/reward_assigner.py`

Responsibilities:
- define typed surfaces
- build runtime state
- generate candidates from local rules and future providers
- shortlist candidates before online comparison
- compare only a small set online
- assemble adaptive context
- log turn-level data for future reward assignment

Current surfaces:
- `context_evidence`
- `capability_exposure`
- `acquisition_policy`
- `interaction_hint`
- `knowledge_exposure` (reserved for future integration)

### 2. Layered Knowledge Runtime

Files:
- `nanobot/knowledge/contracts.py`
- `nanobot/knowledge/base.py`
- `nanobot/knowledge/pipeline.py`
- `nanobot/knowledge/__init__.py`

Responsibilities:
- define common contracts for heterogeneous knowledge sources
- normalize source payloads into `KnowledgeArtifact`
- support multiple source platforms through adapters
- support future compilation, retention, and retrieval pipelines

Core abstractions:
- `KnowledgeSourceSpec`
- `KnowledgeArtifact`
- `KnowledgeIngestRequest`
- `KnowledgeQuery`
- `KnowledgeSourceAdapter`
- `KnowledgeStore`
- `KnowledgeCompiler`
- `KnowledgeRetentionPolicy`
- `KnowledgeRuntime`

Platform-specific adapter bases included:
- `FilesystemKnowledgeAdapter`
- `WebKnowledgeAdapter`
- `MCPKnowledgeAdapter`
- `APIKnowledgeAdapter`

Current default behavior:
- no-op store by default
- optional in-memory store for tests
- passthrough compiler
- simple admission policy

### 3. Layered Memory Runtime

Files:
- `nanobot/memory_layers/contracts.py`
- `nanobot/memory_layers/base.py`
- `nanobot/memory_layers/manager.py`
- `nanobot/memory_layers/__init__.py`

Responsibilities:
- represent memory as layered units instead of a single bucket
- support evolution from working state to higher-level memory
- provide a stable interface for future promotion, demotion, retention, and persistence

Current layers:
- `working`
- `episodic`
- `semantic`
- `policy`

Core abstractions:
- `MemoryUnit`
- `MemoryObservation`
- `MemoryQuery`
- `MemoryPromotionDecision`
- `MemoryLayerStore`
- `MemoryEvolutionPolicy`
- `LayeredMemoryManager`

Current default behavior:
- in-memory storage
- simple materialization into `working` and `episodic` units
- simple promotion policy skeleton

## Context Variable Extension Model

To support future KB/memory integration without rewriting the router, this version adds:

- `ContextVariableProvider`
- `ContextVariableRegistry`

These let future modules emit typed personalization candidates without coupling candidate generation to one source family.

Expected future providers:
- memory exposure provider
- knowledge exposure provider
- tool / MCP exposure provider
- prompt-block provider
- search-policy provider

## Changes to Existing Agent Flow

### `nanobot/agent/context.py`

System prompt construction now accepts dynamic adaptive blocks and appends them under an `# Adaptive Context` section.

### `nanobot/agent/loop.py`

The loop now:
- runs personalization `before_turn()` before building messages
- runs personalization `after_turn()` after a turn is completed
- passes tool usage, usage stats, and turn trace metadata into logging

### `nanobot/personalization/gateway.py`

The gateway now owns:
- `KnowledgeRuntime`
- `LayeredMemoryManager`
- `ContextVariableRegistry`

And after each completed turn, it:
- extracts feedback signals
- collects proxy metrics
- appends trajectory logs
- creates a pending reward-assignment request
- materializes layered memory units and promotion decisions

## Logging and Data Collection

Turn logs now include:
- runtime state
- candidates
- shortlisted items
- selected items
- online evaluation summary
- feedback signals
- proxy metrics
- simplified trace
- layered memory units
- memory promotion decisions

Reward requests now include enough structure to support future posterior reward assignment over shortlisted and selected items.

## Reliability / Maintainability Fixes

To avoid import cycles introduced by the new modular architecture:
- `nanobot/personalization/__init__.py` now uses lazy export
- `nanobot/agent/__init__.py` now uses lazy export

## Verification

Verified in this version:
- compile checks for `knowledge`, `memory_layers`, `personalization`, and related tests
- smoke execution for:
  - knowledge runtime ingest + retrieve
  - layered memory materialization + retrieval
  - provider registry injecting external candidates
  - `after_turn()` logging layered memory decisions

## Next Steps

Recommended next implementations:

1. Add one concrete knowledge adapter, preferably local markdown / vault-backed.
2. Add a `KnowledgeExposureProvider` that retrieves KB candidates into the shortlist path.
3. Replace in-memory layered memory storage with persistent storage.
4. Add `RewardAssignmentResult` and asynchronous score-table updates.
5. Introduce delayed feedback joins and real reward assignment.

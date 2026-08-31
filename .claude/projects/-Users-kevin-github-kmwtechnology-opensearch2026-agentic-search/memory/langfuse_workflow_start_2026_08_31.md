---
name: langfuse_workflow_start_session
description: Workflow-start prep for issue #18 Phase 1; decision points, plan, tasks ready to code
metadata:
  type: project
---

# Langfuse Phase 1 Workflow-Start (Issue #18) — 2026-08-31

## Status
**Ready to code** — Three decision points pending user confirmation, then proceed to feature branch.

## Context Summary
- **Ticket**: #18 Add Langfuse observability for cost/quality tracking & evals (OPEN)
- **Current branch**: `main`, clean
- **Research artifacts**: Moved to memory (`langfuse_integration_mapping.md`, `langfuse_integration_research.md`)
- **Key finding**: Langfuse callback handler pattern works; cost tracking is Phase 2+ (not automatic)

## Three Decision Points (Awaiting User Clarification)

1. **Local dev environment** — Should developers:
   - Connect to GCP Langfuse (network dependency during dev)?
   - Skip Langfuse entirely in local dev (simplest; Phase 2+ can add Docker)?
   - **Research recommendation**: Skip for now; Phase 2 can add Docker option

2. **GCP project for Phase 1** — Do you have:
   - A GCP project ID ready for Terraform deployment?
   - GCP auth configured locally?

3. **Cost dashboard in Phase 1** — Include:
   - Just execution graph visibility (pure Phase 1 scope)?
   - Basic cost dashboard stub (requires Phase 2 instrumentation anyway)?
   - **Research recommendation**: Execution graphs only; Phase 2 adds per-node cost tracking

## Approved Plan (Ready to Execute)

**Scope**: Minimal callback handler integration + env var setup + documentation.
- 7 lines in `main.py` (import, instantiate, pass to StateGraph)
- 5 lines in `api/main.py` (lifespan startup/shutdown)
- 4 env vars in `config.py`
- Doc updates: README (GCP deployment, local dev), CLAUDE.md (Phase 1 ref)

**Out of scope (Phase 2+)**:
- Per-node cost tracking (Langfuse doesn't auto-track per-node)
- Custom observation types
- Evaluation workflows / human annotation
- LLM-as-Judge integration
- Async callback workaround

**Risk mitigations**:
- Env vars default to disabled (zero overhead if not configured)
- No middleware/pipeline changes
- Research verified callback handler pattern works

## Tasks (Ready to Execute)

```
a. Confirm three decision points (local dev, GCP project, cost dashboard scope)
b. Create branch: feat/issue-18-langfuse-phase1-callback-handler
c. Implement config.py: add 4 Langfuse env vars
d. Implement main.py: init CallbackHandler, pass to StateGraph.compile()
e. Implement api/main.py: lifespan startup/shutdown
f. Add unit test: callback handler instantiation (env vars present vs disabled)
g. Update docs: README (GCP Terraform deployment), CLAUDE.md (Phase 1 ref)
h. Grep docs for stale references
i. Commit + open draft PR
j+k (parallel): CI watch + self-review
l. Flip draft → ready
```

## Next Action
**When resuming**: Confirm the three decision points, then I'll transition issue to In Progress and start coding.

## Research References
- `[[langfuse_integration_mapping]]` — 8-node graph, instrumentation per node, env vars, files to modify
- `[[langfuse_integration_research]]` — 15 verified claims, 10 refuted, cost tracking constraints, async workaround notes

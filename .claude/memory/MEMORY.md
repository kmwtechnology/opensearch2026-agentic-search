# Agentic Hybrid Search — Working Memory

## Quick Lookup by Topic

**Talk & Messaging**: [Haystack 2026 accepted abstract](haystack_2026_talk_abstract.md) | [OpenSearchCon 2026 brainstorm](opensearchcon_2026_proposal_brainstorm.md)

**Documentation**: [Documentation expansion complete (6 phases, 20 files)](documentation_expansion_complete.md) | [README hierarchy complete (6 new files)](documentation_hierarchy_2026-06-04.md)

**Collaboration & Workflow**: [Claude collaboration prefs](feedback_claude_collaboration_prefs.md) | [Session workflow rhythm (13-phase)](feedback_session_workflow_rhythm.md) | [Common gotchas (quick-ref)](feedback_common_gotchas.md) | [Documentation hierarchy principle (all audiences)](feedback_documentation_hierarchy_principle.md) | [No Slack PR announcements — not a Nasuni project](feedback_no_slack_announcements.md)

**Auth & Security**: [Login gate + session](login_gate_2026-04-29.md) | [Admin auth enforcement](admin_auth_enforcement_2026-04-30.md) | [Origin auth Host fallback rule](feedback_origin_auth_host_fallback.md)

**Testing Strategy**: [E2E collection gate](feedback_e2e_collect_only.md) | [Run e2e locally](feedback_run_e2e_locally.md) | [Smoke-test budget (16–25s/msg)](feedback_smoke_test_budget.md) | [Local smoke before deploy push](feedback_local_smoke_before_deploy.md)

**Deployment & CI/CD**: [GCP Cloud Run](gcp_deployment_complete.md) | [GitHub Actions + WIF](github_actions_cicd.md) | [Env vars in both paths](feedback_required_env_vars_in_both_deploy_paths.md)

**Performance & Observability**: [Cross-encoder latency (FETCH_K=40, ~35s)](cross_encoder_latency_fix_2026-05-01.md) | [LLM Judge retry gate](judge_categorical_retry_gate.md) | [Filter relaxation — drops multi_match filters when < 3 results (PR #71)](filter_relaxation_retriever.md)

**Data & Infrastructure**: [ESCI dataset](esci_dataset.md) | [ESCI 10k precomputed embeddings (PR #40)](esci_sample_precomputed_embeddings.md) | [OpenSearch VM](project_opensearch_vm.md)

**Reference**: [Never force-add gitignored files](feedback_never_force_add_gitignored.md) | [File orthogonal bugs separately](feedback_file_orthogonal_bugs.md)

---

## Recent Work (Current Session — Documentation Expansion)

- **Phase 1–3 Documentation Complete (PRs #61–63)** — Created operations guide (5 runbooks: deployment, monitoring, troubleshooting, scaling, health), integration guide (REST API, WebSocket, auth patterns with examples), contributing guide (code patterns, testing pyramid, PR process). All merged to main (commits a59c20c, 7ed3c0b, 9bbf584). Combined with prior phases 4–6: 20 markdown files, ~2000 lines, covering all 4 documentation audiences (operators, integrators, developers, frontend devs).

---

## Memory Files (Curated Core Set)

This directory stores project-specific context for Claude Code sessions:

| Memory Type | Files | Purpose |
|-------------|-------|---------|
| **User Prefs** | feedback_* | How to collaborate with this user (code-first, no trailing summaries, branch suggestions, etc.) |
| **Project Status** | documentation_*, deployment_*, github_actions_* | Ongoing work, decisions, infrastructure state |
| **Tech Decisions** | cross_encoder_*, judge_*, esci_* | Architecture choices, performance tradeoffs, data setup |
| **Auth & Security** | login_gate_*, admin_auth_*, feedback_origin_auth_* | Session management, CORS, WebSocket auth |
| **Testing** | feedback_*_tests, feedback_smoke_* | Local vs CI, latency budgets, test markers |

See linked files above for detailed notes.

---

## How to Use This Directory

1. **Before starting work:** Read relevant memory files to understand project context
2. **During work:** If you discover something surprising or important, note it
3. **After work:** Update MEMORY.md index and relevant files before the session ends
4. **Preserve context:** Keep memory files in sync with code (e.g., when APIs change, update the notes)

Memory is **not** a replacement for reading code or git history. It's for non-obvious decisions, patterns, and gotchas that would otherwise be lost.

---

**Last Updated:** 2026-06-04 (documentation expansion complete)

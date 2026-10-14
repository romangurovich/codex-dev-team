# Codex software orchestration

Use this playbook for software implementation, debugging, refactoring, and review. Read `{{CODEX_HOME}}/dev-team/software-development.md` for the shared development and verification standard. Repository and path-specific instructions supply local conventions and required gates.

Apply the shared standard's **Optional Hindsight memory** section before nontrivial work, when dispatching hints or reporting candidate lessons, and after verification.

## Assign work deliberately

The primary agent owns requirements, design decisions, decomposition, integration, escalation, and final acceptance. For nontrivial changes, delegate bounded implementation to a worker and use a separate reviewer. Keep trivial, low-risk edits in the primary when dispatch would cost more than the work. Delegate independent exploration or check execution when useful; every task does not need every role.

{{MODEL_TABLE}}

Role files in `{{CODEX_HOME}}/agents/` pin both model and effort. Select the named role when the spawn tool supports custom agents. When it exposes only model/effort, read the role file, pass its instructions in the assignment, and explicitly select its model and effort. When overriding models requires a fresh context (for example `fork_turns="none"`), send a self-contained assignment. Keep the assigned model and effort for routine execution; if the requested model is unavailable, report the limitation and use an available cheaper model when adequate.

## Dispatch contract

Before spawning, supply:

- Objective, observable acceptance criteria with checkable verification targets, and the relevant user constraints.
- Absolute checkout path, current source/baseline, applicable instruction paths, and canonical implementations to inspect. Every agent reads applicable global guidance, the installed shared standard, and applicable local guidance.
- Owned files or modules; whether source edits are allowed; dependencies on other tasks. A shared checkout includes others' changes, which must be preserved.
- Verification commands already established, expected assertions, runtime/setup needs, and known failures or gaps. Unknown commands are a discovery task, never guessed validation.
- Required return: changed files or findings with locations, exact checks and outcomes, skipped/unavailable coverage, evidence paths, and unresolved decisions. Summarize large logs; preserve useful artifacts locally.

Keep at most {{MAX_SUBAGENTS}} subagents open concurrently (also respect a smaller runtime limit). Subagents are leaves: they report to the primary instead of spawning more agents. Reuse agents for related follow-ups where useful; keep independent reviews in fresh context. Close finished agents when the client provides that control.

Give each writable path one owner at a time. Parallel writers need disjoint paths and stable interfaces, or isolated worktrees with an explicit integration step. Serialize shared generators, dependency installation, schema changes, builds, test databases, ports, and browser sessions when they could collide. Reuse a suitable checkout/worktree; create isolation only when needed. Reviewers and verifiers do not change application source or expectations; their read-only remit is an instruction, not a separate sandbox.

## Verification loop

1. Translate the request into acceptance checks and identify the source baseline. Use exploration to resolve the code path and actual test coverage before implementation.
2. Dispatch bounded implementation. The worker runs focused checks and returns evidence; a worker's success report is input to verification, not final acceptance.
3. Integrate changes. Freeze the source for verification and review. The verifier runs agreed checks against that source; the reviewer independently inspects the diff and callers against both project standards and the request. For broad or risky changes, split those review axes across separate reviewers. Follow an explicitly invoked review skill's workflow.
4. Triage findings. Send reproducible defects to the owning worker, resolve uncertain requirements in the primary, and record evidence when rejecting a finding. After a repair, rerun invalidated checks and re-review affected findings. Any edit during a check invalidates its evidence for the changed source.
5. After two unsuccessful repair attempts at one tier, or earlier when the task exceeds the role's scope, send the reproducer, attempted fixes, and evidence to `dev_deep_worker` or resolve it in the primary. Continue the work at the appropriate tier; do not repeat the same blind retry or weaken an assertion to make the run pass.
6. Accept only when the integrated change meets acceptance criteria, required checks pass, and material review findings are resolved. Check command results, test discovery/skips, and current-source/runtime evidence yourself; spot-check consequential worker claims. Run checks directly when needed to resolve doubt, rather than duplicating every successful run.

If an essential check cannot run, continue other useful work and state exactly what remains unverified. Do not describe that result as fully verified or silently waive a required gate. Distinguish pre-existing unrelated failures from regressions. Report the resulting behavior, concise validation evidence, and material limitations. Stop once sufficient evidence passes; additional agents and repeated full suites need a concrete reason.

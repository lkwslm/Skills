# Typed state machines

Normal transitions are fixed:

- Greenfield: `captured → baselined → planned → executing → verified → closed`.
- Brownfield: `captured → baselined → planned → executing → implementation_accepted → release_ready → releasing → released → production_validated → closed`.
- Task: `draft → approved → implementing → verifying → accepted`.
- Contract: `draft → reviewed → frozen → superseded|retired`.

The reducer, not the caller, selects required gate types for each edge. Every gate ref resolves a previous signed event and exact record ID/version/digest. Subject, run/attempt, scope/environment and target commit must equal the transition. Normal progression accepts only `APPROVED`/`RISK_ACCEPTED` approvals and `PASS` evidence/audits within their validity interval. Audit overall is computed from clauses.

`blocked`, `failed`, `stale` and `deprecated` retain the previous normal recovery origin and never skip a normal edge. Completion states additionally require fixed relation-aware trace paths; callers cannot supply a smaller path policy.

# State machines

Use only these normal transitions:

- Greenfield delivery: `captured → baselined → planned → executing → verified → closed`.
- Brownfield change: `captured → baselined → planned → executing → implementation_accepted → release_ready → releasing → released → production_validated → closed`.
- Slice/task: `draft → approved → implementing → verifying → accepted`.
- Contract: `draft → reviewed → frozen → superseded` or `draft → reviewed → frozen → retired`.

Any object may enter `blocked`, `failed`, `stale`, or `deprecated`. Enter `blocked` or `stale` only with gate result `BLOCKED`, enter `failed` only with `FAIL`, and enter `deprecated` only with `PASS`. Advance to a normal state only with `PASS`.

When entering an exceptional state, retain the preceding normal state as the recovery origin. Resume only to that origin or to its immediate normal successor, and record new successful gate evidence. Do not use an exceptional state to skip an intermediate gate. `RISK_ACCEPTED` is an approval decision, not a state bypass.

Record old/new state, object ID, actor, timezone-aware timestamp, non-empty input versions, resolvable evidence references, and gate result for every transition. Preserve chronological, contiguous history from the kind's initial state and require the object's current state to equal its final transition. Reject undefined, missing, discontinuous, out-of-order, or ungrounded transitions. A Greenfield child may not change its Brownfield parent's state.

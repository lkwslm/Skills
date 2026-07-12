# Permission model

Assign one role per attempt and enforce actual capabilities where possible:

| Role | May write | Must not write |
|---|---|---|
| orchestrator | task packages, gates, owned state | business implementation, approvals, direct release |
| fact-extractor | baseline and discovery artifacts | Spec, implementation, approvals |
| spec-author | pre-approval authoritative Spec/tasks | implementation, self-approval |
| contract-owner | owned contract versions | consumer implementations, compatibility exceptions |
| implementer | approved code/test paths and evidence | baseline, Spec, approvals, production state |
| verifier | attempts, raw results, audits | implementation, Spec, release approval |
| release-controller | authorized environment and release state | code, Spec, expanded scope |
| human-approver | versioned approval records | untraceable verbal approval |

Validate actor, artifact type, normalized relative path and parent/child ownership before writes. Reject absolute paths, drive-qualified paths and `..` traversal. Compare the real Git diff, including untracked files, with the approved base tree and scope.

For an environment write, resolve the authorization's approval ID through `.delivery/approvals.json`, then bind its object ID, version, content hash, path scope, environment, decision, and expiry to the corresponding artifact-registry record. Treat an authorization embedded only in the proposed write manifest as untrusted input. If runtime capability cannot enforce a critical boundary, record the degradation and stop at the gate that requires isolation.

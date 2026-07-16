# Signed permission model

Authorization is derived from the currently replayed trust policy. Each actor is bound to one Ed25519 public-key fingerprint, capabilities, relative POSIX path scopes, environments, validity interval and optional revocation sequence. The event signature key must match that actor. Only the externally anchored root key may rotate policy.

Never read role, allowed paths, approval status or environment authority from a proposed write manifest. Validate the actual operation paths and environment against signed policy. Trust changes and approvals are signed events; approval payloads bind subject ID/version/digest, run, attempt, scope, environment, decision, nonce and validity interval.

A `spec-integrator` with both `provider.write` and `artifact.write` may register or supersede only provider-backed `spec` and `task` artifacts through `observe-provider`; this records native output and does not grant authority to author Git-backed specs or approve them. The actor's signed path scope must still cover every provider authority path.

State writes additionally require an active claim for the exact object identity. A claim has an unpredictable lease token and monotonically increasing fencing token. Renew, release and expire must match both; a paused old holder cannot write after another fence is issued.

A `fact-extractor` or `spec-author` with `state.write` may only register an initial state object. Normal transitions remain restricted to lifecycle roles and always require an active exact claim.

Store root private keys outside the repository. CI identities need separate scoped keys; do not share the root key. Rotate/revoke by a root-signed policy event and update the protected external trust-root history before accepting the new external checkpoint.

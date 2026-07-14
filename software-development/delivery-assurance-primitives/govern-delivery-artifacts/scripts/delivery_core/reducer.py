"""Pure, deterministic reducer for signed delivery operations."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from .events import validate_operation
from .crypto import public_key_fingerprint
from .gates import GateError, record_digest, validate_transition
from .permissions import PermissionDenied, authorize_operation, require_active_claim


class ReducerError(ValueError):
    """An otherwise well-formed operation violates ledger invariants."""


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "trust_policy": None,
        "artifacts": {},
        "current_versions": {},
        "approvals": {},
        "runs": {},
        "attempts": {},
        "evidence": {},
        "audits": {},
        "claims": {},
        "claim_fences": {},
        "states": {},
        "trace_nodes": {},
        "trace_edges": {},
        "provider_profiles": {},
        "migrations": {},
        "seen_operation_ids": [],
    }


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ReducerError("operation timestamp must be UTC")
    return parsed


def _identity_key(identity: Mapping[str, Any]) -> str:
    return f"{identity['artifact_id']}@{identity['version']}"


def _record_key(record: Mapping[str, Any], id_field: str) -> str:
    return f"{record[id_field]}@{record['version']}"


def _require_artifact(state: Mapping[str, Any], identity: Mapping[str, Any]) -> None:
    record = state["artifacts"].get(_identity_key(identity))
    if record is None or record["digest"] != identity["digest"]:
        raise ReducerError(f"artifact identity does not resolve: {_identity_key(identity)}")


def _add_versioned(index: dict[str, Any], record: Mapping[str, Any], id_field: str, event_id: str) -> None:
    key = _record_key(record, id_field)
    if key in index:
        raise ReducerError(f"duplicate record identity: {key}")
    index[key] = {"event_id": event_id, "record": deepcopy(record)}


def _audit_result(clauses: list[Mapping[str, Any]]) -> str:
    results = {clause["result"] for clause in clauses}
    if "FAIL" in results:
        return "FAIL"
    if "BLOCKED" in results:
        return "BLOCKED"
    return "PASS"


def _validate_policy(policy: Mapping[str, Any]) -> None:
    actor_ids = [item["actor_id"] for item in policy["actors"]]
    fingerprints = [item["key_fingerprint"] for item in policy["actors"]]
    if len(actor_ids) != len(set(actor_ids)) or len(fingerprints) != len(set(fingerprints)):
        raise ReducerError("trust policy actor IDs and key fingerprints must be unique")
    for actor in policy["actors"]:
        try:
            actual = public_key_fingerprint(actor["public_key_pem"].encode("utf-8"))
        except ValueError as exc:
            raise ReducerError(f"actor public key is invalid: {actor['actor_id']}") from exc
        if actual != actor["key_fingerprint"]:
            raise ReducerError(f"actor public key fingerprint mismatch: {actor['actor_id']}")
        if actor["valid_until"] is not None and _utc(actor["valid_until"]) <= _utc(actor["valid_from"]):
            raise ReducerError(f"actor key validity interval is invalid: {actor['actor_id']}")
    roots = [item for item in policy["actors"] if item["key_fingerprint"] == policy["root_key_fingerprint"] and "trust.manage" in item["capabilities"]]
    if len(roots) != 1:
        raise ReducerError("trust policy must bind exactly one trust-managing root actor")


RELATION_MATRIX = {
    "derives": {("source", "requirement"), ("source", "contract"), ("context-package", "requirement"), ("context-package", "contract"), ("context-package", "current-behavior"), ("spec", "task"), ("implementation", "test")},
    "specifies": {("requirement", "spec"), ("contract", "spec")},
    "implements": {("task", "implementation")},
    "verifies": {("test", "evidence")},
    "audits": {("evidence", "audit")},
    "mitigates": {("risk-acceptance", "requirement"), ("risk-acceptance", "contract")},
    "migrates": {("current-behavior", "migration-plan"), ("migration-plan", "target-behavior")},
    "observes": {("target-behavior", "observation-plan")},
    "stops": {("observation-plan", "stop-condition")},
    "preserves": {("current-behavior", "unchanged-behavior")},
}

TRACE_ARTIFACT_TYPES = {
    "source": {"source"}, "requirement": {"requirement"}, "contract": {"contract"},
    "spec": {"spec"}, "task": {"task"}, "implementation": {"implementation"},
    "test": {"test"}, "evidence": {"evidence"}, "audit": {"audit"},
    "context-package": {"context-package"},
    "risk-acceptance": {"evidence"}, "migration-plan": {"spec"},
    "observation-plan": {"test"}, "stop-condition": {"requirement"},
    "current-behavior": {"requirement"}, "target-behavior": {"requirement"},
    "unchanged-behavior": {"requirement"},
}


def _validate_artifact_authority(artifact: Mapping[str, Any]) -> None:
    if artifact["authority"]["kind"] == "delivery_blob" and artifact["artifact_type"] not in {"evidence", "audit", "migration"}:
        raise ReducerError("delivery_blob authority is restricted to evidence, audit, and migration artifacts")


def apply_operation(
    old_state: Mapping[str, Any],
    operation: Mapping[str, Any],
    *,
    actor_id: str,
    signer_fingerprint: str,
    sequence: int,
    event_id: str,
    at: str,
    genesis: bool = False,
) -> dict[str, Any]:
    validate_operation(operation)
    state = deepcopy(old_state)
    if operation["operation_id"] in state["seen_operation_ids"]:
        raise ReducerError(f"replayed operation_id: {operation['operation_id']}")
    event_type = operation["type"]
    payload = operation["payload"]
    if genesis:
        if sequence != 1 or state["trust_policy"] is not None or event_type != "trust_policy_initialized":
            raise ReducerError("genesis must be sequence 1 and initialize the trust policy")
        policy = payload["policy"]
        _validate_policy(policy)
        if policy["root_key_fingerprint"] != signer_fingerprint:
            raise ReducerError("genesis signer does not match the external root fingerprint")
        root_actors = [item for item in policy["actors"] if item["key_fingerprint"] == signer_fingerprint]
        if len(root_actors) != 1 or "trust.manage" not in root_actors[0]["capabilities"]:
            raise ReducerError("genesis policy must bind exactly one trust-managing root actor")
        state["trust_policy"] = deepcopy(policy)
    else:
        try:
            authorize_operation(state, operation, actor_id=actor_id, signer_fingerprint=signer_fingerprint, sequence=sequence, at=at)
            require_active_claim(state, operation, actor_id=actor_id, at=at)
        except PermissionDenied as exc:
            raise ReducerError(str(exc)) from exc
        if event_type == "trust_policy_rotated":
            policy = payload["policy"]
            _validate_policy(policy)
            if policy["ledger_id"] != state["trust_policy"]["ledger_id"]:
                raise ReducerError("trust policy rotation cannot change ledger_id")
            if policy["policy_version"] == state["trust_policy"]["policy_version"]:
                raise ReducerError("trust policy rotation must create a new policy version")
            state["trust_policy"] = deepcopy(policy)
        elif event_type == "artifact_registered":
            artifact = payload["artifact"]
            _validate_artifact_authority(artifact)
            if _utc(artifact["created_at"]) > _utc(at):
                raise ReducerError("artifact created_at cannot be in the future of its signed event")
            key = f"{artifact['artifact_id']}@{artifact['version']}"
            if key in state["artifacts"] or artifact["artifact_id"] in state["current_versions"]:
                raise ReducerError("artifact registration requires a new stable artifact ID")
            for source in artifact["derived_from"]:
                _require_artifact(state, source)
            state["artifacts"][key] = deepcopy(artifact)
            state["current_versions"][artifact["artifact_id"]] = artifact["version"]
        elif event_type == "artifact_superseded":
            artifact = payload["artifact"]
            _validate_artifact_authority(artifact)
            if _utc(artifact["created_at"]) > _utc(at):
                raise ReducerError("superseding artifact created_at cannot be in the future of its signed event")
            artifact_id = payload["artifact_id"]
            previous_version = payload["previous_version"]
            if artifact["artifact_id"] != artifact_id or artifact["version"] == previous_version:
                raise ReducerError("superseding artifact identity is invalid")
            if state["current_versions"].get(artifact_id) != previous_version:
                raise ReducerError("supersedes must name the explicit current version")
            old_key = f"{artifact_id}@{previous_version}"
            new_key = f"{artifact_id}@{artifact['version']}"
            if new_key in state["artifacts"]:
                raise ReducerError("artifact version already exists")
            for source in artifact["derived_from"]:
                _require_artifact(state, source)
            state["artifacts"][old_key]["status"] = "superseded"
            state["artifacts"][new_key] = deepcopy(artifact)
            state["current_versions"][artifact_id] = artifact["version"]
            stale_frontier = {old_key}
            while stale_frontier:
                upstream = stale_frontier.pop()
                upstream_id, upstream_version = upstream.rsplit("@", 1)
                for dependent_key, dependent in state["artifacts"].items():
                    if dependent["status"] in {"superseded", "deprecated", "stale"}:
                        continue
                    if any(source["artifact_id"] == upstream_id and source["version"] == upstream_version for source in dependent["derived_from"]):
                        dependent["status"] = "stale"
                        stale_frontier.add(dependent_key)
        elif event_type == "approval_recorded":
            approval = payload["approval"]
            if _utc(approval["issued_at"]) > _utc(at):
                raise ReducerError("approval issued_at cannot be in the future of its signed event")
            _require_artifact(state, approval["subject"])
            run = state["runs"].get(approval["run_id"])
            attempt = state["attempts"].get(approval["attempt_id"])
            if run is None or attempt is None or attempt["record"]["run_id"] != approval["run_id"]:
                raise ReducerError("approval run/attempt does not resolve")
            if run["record"]["target_commit"] != approval["target_commit"] or attempt["record"]["target_commit"] != approval["target_commit"]:
                raise ReducerError("approval target commit differs from run or attempt")
            if approval["subject"] not in run["record"]["inputs"]:
                raise ReducerError("approval subject is absent from run inputs")
            if any(item["record"]["nonce"] == approval["nonce"] for item in state["approvals"].values()):
                raise ReducerError("approval nonce has already been used")
            if _utc(approval["expires_at"]) <= _utc(approval["issued_at"]):
                raise ReducerError("approval expiry must follow issue time")
            if _utc(approval["issued_at"]) < _utc(attempt["record"]["started_at"]):
                raise ReducerError("approval cannot predate its attempt")
            _add_versioned(state["approvals"], approval, "approval_id", event_id)
        elif event_type == "run_started":
            run = payload["run"]
            if _utc(run["started_at"]) > _utc(at):
                raise ReducerError("run started_at cannot be in the future of its signed event")
            if run["run_id"] in state["runs"]:
                raise ReducerError("run_id already exists")
            for identity in run["inputs"]:
                _require_artifact(state, identity)
            state["runs"][run["run_id"]] = {"event_id": event_id, "record": deepcopy(run)}
        elif event_type == "attempt_started":
            attempt = payload["attempt"]
            if _utc(attempt["started_at"]) > _utc(at):
                raise ReducerError("attempt started_at cannot be in the future of its signed event")
            run = state["runs"].get(attempt["run_id"])
            if run is None or run["record"]["target_commit"] != attempt["target_commit"]:
                raise ReducerError("attempt does not resolve to its run and target commit")
            if attempt["attempt_id"] in state["attempts"]:
                raise ReducerError("attempt_id already exists")
            expected_digests = [item["digest"] for item in run["record"]["inputs"]]
            if sorted(attempt["input_digests"], key=lambda item: (item["canonicalization"], item["value"])) != sorted(expected_digests, key=lambda item: (item["canonicalization"], item["value"])):
                raise ReducerError("attempt input digests differ from the exact run inputs")
            expected_sequence = 1 + sum(1 for item in state["attempts"].values() if item["record"]["run_id"] == attempt["run_id"])
            if attempt["sequence"] != expected_sequence:
                raise ReducerError("attempt sequence is not contiguous")
            state["attempts"][attempt["attempt_id"]] = {"event_id": event_id, "record": deepcopy(attempt), "completion": None}
        elif event_type == "attempt_completed":
            completion = payload["completion"]
            if _utc(completion["ended_at"]) > _utc(at):
                raise ReducerError("attempt ended_at cannot be in the future of its signed event")
            attempt = state["attempts"].get(completion["attempt_id"])
            if attempt is None or attempt["record"]["run_id"] != completion["run_id"] or attempt["completion"] is not None:
                raise ReducerError("attempt completion does not resolve to one open attempt")
            if _utc(completion["ended_at"]) < _utc(attempt["record"]["started_at"]):
                raise ReducerError("attempt completion precedes start")
            attempt["completion"] = deepcopy(completion)
        elif event_type == "evidence_recorded":
            evidence = payload["evidence"]
            _require_artifact(state, evidence["subject"])
            attempt = state["attempts"].get(evidence["attempt_id"])
            if attempt is None or attempt["completion"] is None:
                raise ReducerError("evidence requires a completed attempt")
            if attempt["record"]["run_id"] != evidence["run_id"] or attempt["record"]["target_commit"] != evidence["target_commit"]:
                raise ReducerError("evidence run/attempt/target commit binding is invalid")
            run = state["runs"].get(evidence["run_id"])
            if run is None or evidence["subject"] not in run["record"]["inputs"]:
                raise ReducerError("evidence subject is absent from the exact run inputs")
            if _utc(evidence["recorded_at"]) < _utc(attempt["completion"]["ended_at"]) or _utc(evidence["recorded_at"]) > _utc(at):
                raise ReducerError("evidence recorded_at is outside the completed signed attempt interval")
            if attempt["completion"]["result"] != evidence["result"] or attempt["completion"]["log_digest"] != evidence["log_authority"]["digest"]:
                raise ReducerError("evidence result or log digest differs from attempt completion")
            _add_versioned(state["evidence"], evidence, "evidence_id", event_id)
        elif event_type == "audit_recorded":
            audit = payload["audit"]
            _require_artifact(state, audit["subject"])
            if audit["overall"] != _audit_result(audit["clauses"]):
                raise ReducerError("audit overall must be derived from clause results")
            run = state["runs"].get(audit["run_id"])
            attempt = state["attempts"].get(audit["attempt_id"])
            if run is None or attempt is None or attempt["completion"] is None or attempt["record"]["run_id"] != audit["run_id"]:
                raise ReducerError("audit run/attempt does not resolve to one completed attempt")
            if audit["subject"] not in run["record"]["inputs"] or run["record"]["target_commit"] != audit["target_commit"] or attempt["record"]["target_commit"] != audit["target_commit"]:
                raise ReducerError("audit subject or target commit differs from its exact run inputs")
            if attempt["completion"]["result"] != audit["overall"]:
                raise ReducerError("audit overall differs from its completed audit attempt")
            if sorted(audit["input_digests"], key=lambda item: (item["canonicalization"], item["value"])) != sorted(attempt["record"]["input_digests"], key=lambda item: (item["canonicalization"], item["value"])):
                raise ReducerError("audit input digests differ from its attempt")
            if audit["policy_version"] != state["trust_policy"]["policy_version"]:
                raise ReducerError("audit policy_version differs from the current signed policy")
            required_clauses = {
                "requirements-traceability", "scope-conformance", "test-conformance",
                "evidence-integrity", "staleness",
            }
            if run["record"]["suite"] == "greenfield":
                required_clauses.add("contract-conformance")
            else:
                required_clauses.update({"migration-observability", "unchanged-behavior-preservation"})
            if {clause["clause_id"] for clause in audit["clauses"]} != required_clauses:
                raise ReducerError("audit clauses differ from the fixed suite policy")
            if _utc(audit["recorded_at"]) < _utc(attempt["completion"]["ended_at"]) or _utc(audit["recorded_at"]) > _utc(at):
                raise ReducerError("audit recorded_at is outside the completed signed attempt interval")
            for clause in audit["clauses"]:
                for reference in clause["evidence_refs"]:
                    if reference["ref_type"] != "evidence":
                        raise ReducerError("audit clauses may reference only typed evidence records")
                    evidence = state["evidence"].get(f"{reference['record_id']}@{reference['record_version']}")
                    if evidence is None or evidence["event_id"] != reference["event_id"] or record_digest(evidence["record"]) != reference["digest"]:
                        raise ReducerError("audit evidence reference does not resolve exactly")
                    record = evidence["record"]
                    for field in ("subject", "target_commit", "scope", "environment"):
                        if record[field] != audit[field]:
                            raise ReducerError(f"audit evidence {field} binding mismatch")
                    if clause["result"] != record["result"]:
                        raise ReducerError("audit clause result differs from evidence result")
            _add_versioned(state["audits"], audit, "audit_id", event_id)
        elif event_type == "claim_acquired":
            claim = payload["claim"]
            _require_artifact(state, claim["task"])
            if claim["holder_actor_id"] != actor_id:
                raise ReducerError("claim holder must be the signed actor")
            task_key = _identity_key(claim["task"])
            governed = state["states"].get(task_key)
            if governed is None or governed["current_state"] in {"accepted", "closed", "retired", "superseded", "deprecated"}:
                raise ReducerError("claim requires a governed, non-terminal state object")
            active = [item for item in state["claims"].values() if item["status"] == "active" and _identity_key(item["record"]["task"]) == task_key]
            if active:
                raise ReducerError("task already has an active claim; expiry must be explicitly recorded")
            expected_fence = state["claim_fences"].get(task_key, 0) + 1
            if claim["fencing_token"] != expected_fence or not (_utc(claim["acquired_at"]) <= _utc(at) < _utc(claim["expires_at"])):
                raise ReducerError("claim fencing token or lease interval is invalid")
            if claim["claim_id"] in state["claims"]:
                raise ReducerError("claim_id already exists")
            state["claims"][claim["claim_id"]] = {"event_id": event_id, "record": deepcopy(claim), "status": "active"}
            state["claim_fences"][task_key] = expected_fence
        elif event_type in {"claim_renewed", "claim_expired", "claim_released"}:
            claim = state["claims"].get(payload["claim_id"])
            if claim is None or claim["status"] != "active":
                raise ReducerError("claim is not active")
            record = claim["record"]
            if record["lease_token"] != payload["lease_token"] or record["fencing_token"] != payload["fencing_token"]:
                raise ReducerError("claim lease or fencing token does not match")
            if event_type != "claim_expired" and record["holder_actor_id"] != actor_id:
                raise ReducerError("only the claim holder may renew or release a claim")
            if event_type == "claim_renewed":
                if _utc(at) < _utc(record["acquired_at"]) or _utc(at) >= _utc(record["expires_at"]) or _utc(payload["expires_at"]) <= _utc(record["expires_at"]):
                    raise ReducerError("only an unexpired claim may be renewed to a later expiry")
                record["expires_at"] = payload["expires_at"]
            elif event_type == "claim_expired":
                if _utc(at) < _utc(record["expires_at"]) or _utc(payload["expired_at"]) < _utc(record["expires_at"]) or _utc(payload["expired_at"]) > _utc(at):
                    raise ReducerError("claim cannot expire before its signed expiry")
                claim["status"] = "expired"
            else:
                if _utc(payload["released_at"]) > _utc(record["expires_at"]):
                    raise ReducerError("expired claim must be explicitly expired, not released")
                claim["status"] = "released"
        elif event_type == "state_object_registered":
            item = payload["state_object"]
            _require_artifact(state, item["object"])
            key = _identity_key(item["object"])
            expected_type = {"greenfield": "context-package", "brownfield": "context-package", "task": "task", "contract": "contract"}[item["kind"]]
            if state["artifacts"][key]["artifact_type"] != expected_type:
                raise ReducerError("state object kind is incompatible with its governed artifact type")
            expected_initial = "captured" if item["kind"] in {"greenfield", "brownfield"} else "draft"
            if key in state["states"] or item["initial_state"] != expected_initial:
                raise ReducerError("state object already exists or has invalid initial state")
            state["states"][key] = {**deepcopy(item), "current_state": expected_initial, "recovery_origin": None, "history": []}
        elif event_type == "state_transitioned":
            transition = payload["transition"]
            try:
                validate_transition(state, transition, at=at, current_event_id=event_id)
            except GateError as exc:
                raise ReducerError(str(exc)) from exc
            key = _identity_key(transition["object"])
            item = state["states"][key]
            old_state, new_state = transition["old_state"], transition["new_state"]
            if old_state not in {"blocked", "failed", "stale", "deprecated"} and new_state in {"blocked", "failed", "stale", "deprecated"}:
                item["recovery_origin"] = old_state
            elif old_state in {"blocked", "failed", "stale", "deprecated"} and new_state not in {"blocked", "failed", "stale", "deprecated"}:
                item["recovery_origin"] = None
            item["current_state"] = new_state
            item["history"].append({"event_id": event_id, "at": at, "transition": deepcopy(transition)})
        elif event_type == "trace_node_recorded":
            node = payload["node"]
            _require_artifact(state, node["node"])
            key = _identity_key(node["node"])
            if state["artifacts"][key]["artifact_type"] not in TRACE_ARTIFACT_TYPES[node["node_type"]]:
                raise ReducerError("trace node type is incompatible with its governed artifact type")
            if key in state["trace_nodes"]:
                raise ReducerError("trace node already exists")
            state["trace_nodes"][key] = deepcopy(node)
        elif event_type == "trace_edge_recorded":
            edge = payload["edge"]
            from_key, to_key = _identity_key(edge["from"]), _identity_key(edge["to"])
            if from_key not in state["trace_nodes"] or to_key not in state["trace_nodes"]:
                raise ReducerError("trace edge endpoints must exist")
            if state["trace_nodes"][from_key]["node"] != edge["from"] or state["trace_nodes"][to_key]["node"] != edge["to"]:
                raise ReducerError("trace edge endpoint identity digest differs from its node")
            if edge["edge_id"] in state["trace_edges"]:
                raise ReducerError("trace edge ID already exists")
            relation = edge["relation"]
            matrix = RELATION_MATRIX[relation]
            pair = (state["trace_nodes"][from_key]["node_type"], state["trace_nodes"][to_key]["node_type"])
            if matrix is not None and pair not in matrix:
                raise ReducerError(f"illegal trace relation endpoints: {relation} {pair[0]}->{pair[1]}")
            state["trace_edges"][edge["edge_id"]] = deepcopy(edge)
        elif event_type == "provider_profile_observed":
            profile = payload["profile"]
            if _utc(profile["observed_at"]) > _utc(at):
                raise ReducerError("provider observed_at cannot be in the future of its signed event")
            profile_key = f"{profile['profile_id']}@{profile['version']}"
            if profile_key in state["provider_profiles"]:
                raise ReducerError("provider profile identity already exists")
            state["provider_profiles"][profile_key] = {"event_id": event_id, "record": deepcopy(profile), "digest": record_digest(profile)}
        elif event_type == "legacy_imported":
            migration = payload["migration"]
            if _utc(migration["imported_at"]) > _utc(at):
                raise ReducerError("migration imported_at cannot be in the future of its signed event")
            if migration["migration_id"] in state["migrations"]:
                raise ReducerError("migration ID already exists")
            state["migrations"][migration["migration_id"]] = {"event_id": event_id, "record": deepcopy(migration)}
        else:
            raise ReducerError(f"reducer does not implement operation type: {event_type}")
    state["seen_operation_ids"].append(operation["operation_id"])
    return state


def apply_operations(
    old_state: Mapping[str, Any],
    operations: list[Mapping[str, Any]],
    **context: Any,
) -> dict[str, Any]:
    if not operations:
        raise ReducerError("transaction must contain at least one operation")
    state = deepcopy(old_state)
    for index, operation in enumerate(operations):
        if index and operation["type"] == "trust_policy_initialized":
            raise ReducerError("trust initialization may appear only as the genesis operation")
        state = apply_operation(state, operation, genesis=context.get("genesis", False) and index == 0, **{key: value for key, value in context.items() if key != "genesis"})
    return state

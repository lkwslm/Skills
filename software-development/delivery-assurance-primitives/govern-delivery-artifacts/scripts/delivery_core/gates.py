"""Lifecycle policy and exact typed gate-reference resolution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .authority import digest_bytes
from .canonical import canonical_json_bytes
from .traceability import TraceabilityError, validate_completion_closure


class GateError(ValueError):
    """A lifecycle transition is not justified by its governed records."""


NORMAL_TRANSITIONS = {
    "greenfield": [("captured", "baselined"), ("baselined", "planned"), ("planned", "executing"), ("executing", "verified"), ("verified", "closed")],
    "brownfield": [("captured", "baselined"), ("baselined", "planned"), ("planned", "executing"), ("executing", "implementation_accepted"), ("implementation_accepted", "release_ready"), ("release_ready", "releasing"), ("releasing", "released"), ("released", "production_validated"), ("production_validated", "closed")],
    "task": [("draft", "approved"), ("approved", "implementing"), ("implementing", "verifying"), ("verifying", "accepted")],
    "contract": [("draft", "reviewed"), ("reviewed", "frozen"), ("frozen", "superseded"), ("frozen", "retired")],
}
EXCEPTIONAL = {"blocked", "failed", "stale", "deprecated"}

# Policy owns these requirements.  A caller cannot weaken them in an operation.
GATE_POLICY = {
    "captured->baselined": {"audit"},
    "baselined->planned": {"approval", "audit"},
    "planned->executing": {"approval"},
    "executing->verified": {"evidence", "audit"},
    "verified->closed": {"audit"},
    "executing->implementation_accepted": {"evidence", "audit"},
    "implementation_accepted->release_ready": {"approval", "audit"},
    "release_ready->releasing": {"approval"},
    "releasing->released": {"evidence", "audit"},
    "released->production_validated": {"evidence", "audit"},
    "production_validated->closed": {"audit"},
    "draft->approved": {"approval"},
    "approved->implementing": {"approval"},
    "implementing->verifying": {"evidence"},
    "verifying->accepted": {"evidence", "audit"},
    "draft->reviewed": {"audit"},
    "reviewed->frozen": {"approval", "audit"},
    "frozen->superseded": {"approval"},
    "frozen->retired": {"approval"},
}


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise GateError(f"timestamp must be UTC: {value}")
    return parsed


def record_digest(record: Mapping[str, Any]) -> dict[str, str]:
    return digest_bytes(canonical_json_bytes(record), "raw-v1")


def _required_result(ref_type: str, target_state: str) -> set[str]:
    if target_state == "failed":
        return {"FAIL"}
    if target_state in {"blocked", "stale"}:
        return {"BLOCKED"}
    if ref_type == "approval":
        return {"APPROVED"}
    return {"PASS"}


def validate_transition(
    state: Mapping[str, Any],
    transition: Mapping[str, Any],
    *,
    at: str,
    current_event_id: str,
) -> None:
    key = f"{transition['object']['artifact_id']}@{transition['object']['version']}"
    state_object = state.get("states", {}).get(key)
    if state_object is None:
        raise GateError(f"state object does not exist: {key}")
    if state_object["object"]["digest"] != transition["object"]["digest"]:
        raise GateError("transition object digest does not match the governed state object")
    old_state, new_state = transition["old_state"], transition["new_state"]
    if state_object["current_state"] != old_state:
        raise GateError(f"transition old_state is stale: expected {state_object['current_state']}")
    kind = state_object["kind"]
    normal = (old_state, new_state) in NORMAL_TRANSITIONS[kind]
    if not normal and new_state not in EXCEPTIONAL:
        origin = state_object.get("recovery_origin")
        successors = {target for source, target in NORMAL_TRANSITIONS[kind] if source == origin}
        if old_state not in EXCEPTIONAL or new_state not in ({origin} | successors):
            raise GateError(f"illegal {kind} transition {old_state}->{new_state}")
    required = GATE_POLICY.get(f"{old_state}->{new_state}", set()) if normal else ({"audit"} if new_state in EXCEPTIONAL else {"audit"})
    refs = transition["gate_refs"]
    if {item["ref_type"] for item in refs} != required:
        raise GateError(f"transition requires exactly gate types {sorted(required)}")
    transition_time = _parse_utc(at)
    records_by_type = {
        "approval": state.get("approvals", {}),
        "evidence": state.get("evidence", {}),
        "audit": state.get("audits", {}),
    }
    gate_identities: dict[str, list[dict[str, Any]]] = {"approval": [], "evidence": [], "audit": []}
    for reference in refs:
        ref_type = reference["ref_type"]
        index_key = f"{reference['record_id']}@{reference['record_version']}"
        entry = records_by_type[ref_type].get(index_key)
        if entry is None:
            raise GateError(f"gate record does not exist: {ref_type}:{index_key}")
        if entry["event_id"] != reference["event_id"]:
            raise GateError(f"gate event binding mismatch: {index_key}")
        if entry["event_id"] == current_event_id:
            raise GateError(f"gate record must come from a prior signed event: {index_key}")
        record = entry["record"]
        if record_digest(record) != reference["digest"]:
            raise GateError(f"gate record digest mismatch: {index_key}")
        if record["subject"] != transition["object"]:
            raise GateError(f"gate subject/version/digest mismatch: {index_key}")
        for field in ("run_id", "attempt_id", "scope", "environment"):
            if record[field] != transition[field]:
                raise GateError(f"gate {field} mismatch: {index_key}")
        if record.get("target_commit") not in (None, transition["target_commit"]):
            raise GateError(f"gate target_commit mismatch: {index_key}")
        result = record.get("decision") if ref_type == "approval" else record.get("result", record.get("overall"))
        if result not in _required_result(ref_type, new_state):
            raise GateError(f"gate result {result} cannot justify {new_state}: {index_key}")
        if ref_type == "approval":
            if _parse_utc(record["issued_at"]) > transition_time or _parse_utc(record["expires_at"]) <= transition_time:
                raise GateError(f"approval is not valid at transition time: {index_key}")
        gate_identities[ref_type].append({
            "artifact_id": reference["record_id"],
            "version": reference["record_version"],
            "digest": reference["digest"],
        })
        if ref_type == "audit":
            for clause in record["clauses"]:
                for evidence_ref in clause["evidence_refs"]:
                    gate_identities["evidence"].append({
                        "artifact_id": evidence_ref["record_id"],
                        "version": evidence_ref["record_version"],
                        "digest": evidence_ref["digest"],
                    })
    run = state.get("runs", {}).get(transition["run_id"])
    attempt = state.get("attempts", {}).get(transition["attempt_id"])
    if run is None or attempt is None or attempt["record"]["run_id"] != transition["run_id"]:
        raise GateError("transition run/attempt does not resolve")
    if run["record"]["target_commit"] != transition["target_commit"] or attempt["record"]["target_commit"] != transition["target_commit"]:
        raise GateError("transition target commit differs from run or attempt")
    if new_state in {"verified", "closed", "accepted", "release_ready", "released", "production_validated"}:
        suite = run["record"]["suite"]
        try:
            validate_completion_closure(
                state, suite, transition["object"], run["record"]["inputs"],
                gate_identities["evidence"], gate_identities["audit"],
            )
        except TraceabilityError as exc:
            raise GateError(str(exc)) from exc

#!/usr/bin/env python3
"""Positive and fail-closed tests for the delivery domain model."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from delivery_core.authority import (  # noqa: E402
    AuthorityError,
    digest_bytes,
    resolve_authority,
)
from delivery_core.crypto import (  # noqa: E402
    private_key_pem,
    public_key_fingerprint,
    public_key_pem,
)
from delivery_core.events import CAPABILITIES  # noqa: E402
from delivery_core.gates import GateError, record_digest, validate_transition  # noqa: E402
from delivery_core.ledger import Revision, build_signed_event  # noqa: E402
from delivery_core.permissions import PermissionDenied, authorize_operation  # noqa: E402
from delivery_core.reducer import ReducerError, apply_operation, empty_state  # noqa: E402
from delivery_core.service import commit, initialize  # noqa: E402
from delivery_core.traceability import (  # noqa: E402
    TraceabilityError,
    validate_completion_closure,
)
from delivery_core.transaction import commit_event  # noqa: E402


NOW = "2026-07-13T01:00:00Z"
COMMIT = "a" * 40
ACTOR_FINGERPRINT = "sha256:" + "1" * 64


def identity(artifact_id: str, version: str = "1", digest=None) -> dict:
    return {
        "artifact_id": artifact_id,
        "version": version,
        "digest": digest or digest_bytes(artifact_id.encode("utf-8")),
    }


def blob_authority(digest: dict) -> dict:
    return {"schema_version": "1.0", "kind": "delivery_blob", "digest": digest}


def artifact(
    artifact_id: str,
    artifact_type: str,
    *,
    version: str = "1",
    digest=None,
    derived_from=None,
) -> dict:
    material = digest or digest_bytes((artifact_id + "@" + version).encode("utf-8"))
    authority = blob_authority(material) if artifact_type in {"evidence", "audit", "migration"} else {
        "schema_version": "1.0", "kind": "git", "repository_uri": "https://example.invalid/repo.git",
        "commit": COMMIT, "path": "src/" + artifact_id.lower() + ".json",
    }
    return {
        "schema_version": "1.0",
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "version": version,
        "digest": material,
        "authority": authority,
        "derived_from": list(derived_from or []),
        "status": "active",
        "created_at": "2026-07-13T00:00:00Z",
    }


def actor(*, revoked_at_sequence=None, fingerprint: str = ACTOR_FINGERPRINT) -> dict:
    return {
        "actor_id": "actor-1",
        "public_key_pem": "-----BEGIN PUBLIC KEY-----\nunused\n",
        "key_fingerprint": fingerprint,
        "roles": ["delivery-controller"],
        "capabilities": list(CAPABILITIES),
        "path_scopes": ["src"],
        "environments": ["ci"],
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": None,
        "revoked_at_sequence": revoked_at_sequence,
    }


def trusted_state(*, revoked_at_sequence=None) -> dict:
    state = empty_state()
    state["trust_policy"] = {
        "schema_version": "1.0",
        "policy_id": "POLICY-1",
        "policy_version": "1",
        "ledger_id": "LEDGER-1",
        "root_key_fingerprint": ACTOR_FINGERPRINT,
        "actors": [actor(revoked_at_sequence=revoked_at_sequence)],
    }
    return state


def operation(operation_id: str, kind: str, payload: dict) -> dict:
    return {
        "schema_version": "1.0",
        "operation_id": operation_id,
        "type": kind,
        "payload": payload,
    }


def apply(state: dict, item: dict, *, sequence: int = 2, event_id: str = "EVENT-2") -> dict:
    return apply_operation(
        state,
        item,
        actor_id="actor-1",
        signer_fingerprint=ACTOR_FINGERPRINT,
        sequence=sequence,
        event_id=event_id,
        at=NOW,
    )


def evidence_record(subject: dict, *, result: str = "PASS") -> dict:
    log_digest = digest_bytes(b"test log")
    return {
        "schema_version": "1.0",
        "evidence_id": "EVID-1",
        "version": "1",
        "subject": deepcopy(subject),
        "run_id": "RUN-1",
        "attempt_id": "ATTEMPT-1",
        "target_commit": COMMIT,
        "scope": ["src"],
        "environment": "ci",
        "result": result,
        "log_authority": blob_authority(log_digest),
        "recorded_at": NOW,
    }


class DeliveryDomainTest(unittest.TestCase):
    def profile_operation(self) -> dict:
        observation_digest = digest_bytes(b"{}")
        return operation(
            "OP-PROFILE",
            "provider_profile_observed",
            {
                "profile": {
                    "schema_version": "1.0",
                    "profile_id": "PROFILE-1",
                    "version": "1",
                    "provider": "openspec",
                    "mode": "native",
                    "provider_version": "1.0",
                    "repository_uri": "https://example.invalid/repo.git",
                    "commit": COMMIT,
                    "id_mapping": {
                        "native-1": {
                            "delivery_id": "SPEC-1",
                            "native_id": "native-1",
                            "native_parent_id": None,
                            "artifact_type": "spec",
                            "authority_uri": "openspec/specs/example/spec.md",
                            "status": "ready",
                            "content_hash": "a" * 64,
                        }
                    },
                    "observation_authority": blob_authority(observation_digest),
                    "observed_at": NOW,
                }
            },
        )

    def test_unknown_revoked_and_wrongly_bound_actor_fail_closed(self) -> None:
        valid = apply(trusted_state(), self.profile_operation())
        self.assertIn("PROFILE-1@1", valid["provider_profiles"])

    def test_spec_integrator_can_record_only_provider_backed_spec_artifacts(self) -> None:
        state = trusted_state()
        state["trust_policy"]["root_key_fingerprint"] = "sha256:" + "f" * 64
        integrator = state["trust_policy"]["actors"][0]
        integrator["roles"] = ["spec-integrator"]
        integrator["capabilities"] = ["provider.write", "artifact.write"]
        integrator["path_scopes"] = ["openspec"]
        state = apply(state, self.profile_operation())
        profile = state["provider_profiles"]["PROFILE-1@1"]
        digest = {"algorithm": "sha256", "canonicalization": "raw-v1", "value": "a" * 64}
        provider_artifact = artifact("SPEC-1", "spec", digest=digest)
        provider_artifact["authority"] = {
            "schema_version": "1.0", "kind": "provider", "profile_id": "PROFILE-1",
            "profile_version": "1", "profile_digest": profile["digest"], "native_id": "native-1",
            "artifact_kind": "spec", "repository_uri": "https://example.invalid/repo.git",
            "commit": COMMIT, "path": "openspec/specs/example/spec.md",
        }
        recorded = apply(
            state,
            operation("OP-PROVIDER-ARTIFACT", "artifact_registered", {"artifact": provider_artifact}),
            sequence=3,
            event_id="EVENT-3",
        )
        self.assertEqual(recorded["current_versions"]["SPEC-1"], "1")

        git_artifact = artifact("SPEC-2", "spec")
        git_artifact["authority"]["path"] = "openspec/spec-2.md"
        with self.assertRaisesRegex(ReducerError, "role cannot write artifact type spec"):
            apply(
                state,
                operation("OP-GIT-SPEC", "artifact_registered", {"artifact": git_artifact}),
                sequence=3,
                event_id="EVENT-3",
            )

    def test_role_separation_allows_record_artifacts_but_blocks_conflicted_auditors_and_approvers(self) -> None:
        state = trusted_state()
        state["trust_policy"]["root_key_fingerprint"] = "sha256:" + "f" * 64
        verifier = state["trust_policy"]["actors"][0]
        verifier["roles"] = ["verifier"]
        verifier["capabilities"] = ["artifact.write", "evidence.write", "audit.write"]
        audit_op = {"type": "audit_recorded", "payload": {"audit": {"scope": ["src"], "environment": "ci"}}}
        authorize_operation(
            state, audit_op, actor_id="actor-1", signer_fingerprint=ACTOR_FINGERPRINT,
            sequence=2, at=NOW,
        )
        verifier["capabilities"] = ["claim.write"]
        authorize_operation(
            state, {"type": "claim_acquired", "payload": {}}, actor_id="actor-1",
            signer_fingerprint=ACTOR_FINGERPRINT, sequence=2, at=NOW,
        )
        verifier["roles"] = ["implementer"]
        verifier["capabilities"] = ["claim.write", "state.write", "evidence.write"]
        authorize_operation(
            state, {"type": "state_object_registered", "payload": {}}, actor_id="actor-1",
            signer_fingerprint=ACTOR_FINGERPRINT, sequence=2, at=NOW,
        )
        evidence_op = {"type": "evidence_recorded", "payload": {"evidence": {"scope": ["src"], "environment": "ci"}}}
        authorize_operation(
            state, evidence_op, actor_id="actor-1", signer_fingerprint=ACTOR_FINGERPRINT,
            sequence=2, at=NOW,
        )
        verifier["capabilities"] = ["artifact.write", "evidence.write", "audit.write"]
        verifier["roles"] = ["verifier", "implementer"]
        with self.assertRaisesRegex(PermissionDenied, "separation of duties"):
            authorize_operation(
                state, audit_op, actor_id="actor-1", signer_fingerprint=ACTOR_FINGERPRINT,
                sequence=2, at=NOW,
            )
        verifier["roles"] = ["human-approver"]
        verifier["capabilities"] = ["approval.write", "artifact.write"]
        approval_op = {"type": "approval_recorded", "payload": {"approval": {"scope": ["src"], "environment": "ci"}}}
        with self.assertRaisesRegex(PermissionDenied, "separation of duties"):
            authorize_operation(
                state, approval_op, actor_id="actor-1", signer_fingerprint=ACTOR_FINGERPRINT,
                sequence=2, at=NOW,
            )

        with self.assertRaisesRegex(ReducerError, "not uniquely trusted"):
            apply_operation(
                trusted_state(),
                self.profile_operation(),
                actor_id="unknown",
                signer_fingerprint=ACTOR_FINGERPRINT,
                sequence=2,
                event_id="EVENT-UNKNOWN",
                at=NOW,
            )
        with self.assertRaisesRegex(ReducerError, "revoked"):
            apply(trusted_state(revoked_at_sequence=2), self.profile_operation())
        with self.assertRaisesRegex(ReducerError, "signature key is not bound"):
            apply_operation(
                trusted_state(),
                self.profile_operation(),
                actor_id="actor-1",
                signer_fingerprint="sha256:" + "2" * 64,
                sequence=2,
                event_id="EVENT-WRONG-KEY",
                at=NOW,
            )

    def test_fact_extractor_and_spec_author_can_register_but_not_transition_state(self) -> None:
        for role in ("fact-extractor", "spec-author"):
            with self.subTest(role=role):
                state = trusted_state()
                state["trust_policy"]["root_key_fingerprint"] = "sha256:" + "f" * 64
                actor_value = state["trust_policy"]["actors"][0]
                actor_value["roles"] = [role]
                actor_value["capabilities"] = ["state.write"]
                authorize_operation(
                    state,
                    {"type": "state_object_registered", "payload": {}},
                    actor_id="actor-1", signer_fingerprint=ACTOR_FINGERPRINT,
                    sequence=2, at=NOW,
                )
                with self.assertRaisesRegex(PermissionDenied, "role does not own"):
                    authorize_operation(
                        state,
                        {"type": "state_transitioned", "payload": {}},
                        actor_id="actor-1", signer_fingerprint=ACTOR_FINGERPRINT,
                        sequence=2, at=NOW,
                    )

    def test_service_rejects_a_real_ed25519_key_not_bound_to_actor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            root_key = Ed25519PrivateKey.generate()
            attacker_key = Ed25519PrivateKey.generate()
            root_private = Path(temporary) / "root.pem"
            attacker_private = Path(temporary) / "attacker.pem"
            trust_path = Path(temporary) / "trust.json"
            root_private.write_bytes(private_key_pem(root_key))
            attacker_private.write_bytes(private_key_pem(attacker_key))
            public_pem = public_key_pem(root_key.public_key())
            fingerprint = public_key_fingerprint(public_pem)
            trust_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "ledger_id": "LEDGER-SERVICE",
                        "current_root_fingerprint": fingerprint,
                        "keys": [
                            {
                                "fingerprint": fingerprint,
                                "public_key_pem": public_pem.decode("utf-8"),
                                "valid_from_sequence": 1,
                                "valid_through_sequence": None,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            root_actor = actor(fingerprint=fingerprint)
            root_actor["public_key_pem"] = public_pem.decode("utf-8")
            policy = {
                "schema_version": "1.0",
                "policy_id": "POLICY-SERVICE",
                "policy_version": "1",
                "ledger_id": "LEDGER-SERVICE",
                "root_key_fingerprint": fingerprint,
                "actors": [root_actor],
            }
            current = datetime.now(timezone.utc)
            initialized_at = (current - timedelta(seconds=2)).isoformat(timespec="seconds").replace("+00:00", "Z")
            committed_at = (current - timedelta(seconds=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
            revision = initialize(
                root,
                trust_path,
                policy,
                root_private,
                actor_id="actor-1",
                event_id="EVENT-1",
                operation_id="OP-INIT",
                at=initialized_at,
            )
            with self.assertRaisesRegex(ValueError, "signature key is not bound"):
                commit(
                    root,
                    trust_path,
                    revision,
                    [self.profile_operation()],
                    attacker_private,
                    actor_id="actor-1",
                    event_id="EVENT-2",
                    at=committed_at,
                )

    def approval_gate(self) -> tuple[dict, dict, dict]:
        subject = identity("DELIVERY-1")
        state = empty_state()
        key = "DELIVERY-1@1"
        state["states"][key] = {
            "schema_version": "1.0",
            "object": deepcopy(subject),
            "kind": "greenfield",
            "initial_state": "captured",
            "current_state": "planned",
            "recovery_origin": None,
            "history": [],
        }
        state["runs"]["RUN-1"] = {
            "event_id": "EVENT-RUN",
            "record": {
                "schema_version": "1.0",
                "run_id": "RUN-1",
                "suite": "greenfield",
                "target_commit": COMMIT,
                "inputs": [deepcopy(subject)],
                "started_at": "2026-07-13T00:00:00Z",
            },
        }
        state["attempts"]["ATTEMPT-1"] = {
            "event_id": "EVENT-ATTEMPT",
            "record": {
                "schema_version": "1.0",
                "attempt_id": "ATTEMPT-1",
                "run_id": "RUN-1",
                "sequence": 1,
                "target_commit": COMMIT,
                "input_digests": [deepcopy(subject["digest"])],
                "started_at": "2026-07-13T00:01:00Z",
            },
            "completion": None,
        }
        approval = {
            "schema_version": "1.0",
            "approval_id": "APP-1",
            "version": "1",
            "subject": deepcopy(subject),
            "run_id": "RUN-1",
            "attempt_id": "ATTEMPT-1",
            "base_commit": COMMIT,
            "target_commit": COMMIT,
            "scope": ["src"],
            "environment": "ci",
            "decision": "APPROVED",
            "issued_at": "2026-07-13T00:30:00Z",
            "expires_at": "2026-07-13T02:00:00Z",
            "nonce": "approval-nonce-1",
        }
        state["approvals"]["APP-1@1"] = {
            "event_id": "EVENT-APPROVAL",
            "record": approval,
        }
        transition = {
            "schema_version": "1.0",
            "transition_id": "TRANSITION-1",
            "object": deepcopy(subject),
            "old_state": "planned",
            "new_state": "executing",
            "run_id": "RUN-1",
            "attempt_id": "ATTEMPT-1",
            "target_commit": COMMIT,
            "scope": ["src"],
            "environment": "ci",
            "gate_refs": [
                {
                    "ref_type": "approval",
                    "event_id": "EVENT-APPROVAL",
                    "record_id": "APP-1",
                    "record_version": "1",
                    "digest": record_digest(approval),
                }
            ],
        }
        return state, approval, transition

    def test_approval_gate_accepts_exact_binding_and_rejects_expiry(self) -> None:
        state, _, transition = self.approval_gate()
        validate_transition(state, transition, at=NOW, current_event_id="EVENT-TRANSITION")
        with self.assertRaisesRegex(GateError, "not valid"):
            validate_transition(state, transition, at="2026-07-13T02:00:00Z", current_event_id="EVENT-TRANSITION")

    def test_approval_gate_rejects_scope_object_version_digest_run_attempt_mismatch(self) -> None:
        mutations = {
            "scope": lambda approval: approval.update(scope=["src/other"]),
            "object": lambda approval: approval.update(subject=identity("DELIVERY-OTHER")),
            "version": lambda approval: approval["subject"].update(version="2"),
            "digest": lambda approval: approval["subject"].update(
                digest=digest_bytes(b"other subject")
            ),
            "run": lambda approval: approval.update(run_id="RUN-OTHER"),
            "attempt": lambda approval: approval.update(attempt_id="ATTEMPT-OTHER"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                state, approval, transition = self.approval_gate()
                mutate(approval)
                transition["gate_refs"][0]["digest"] = record_digest(approval)
                with self.assertRaises(GateError):
                    validate_transition(state, transition, at=NOW, current_event_id="EVENT-TRANSITION")

    def test_fail_audit_cannot_advance_a_normal_state(self) -> None:
        state, _, transition = self.approval_gate()
        subject = transition["object"]
        state["states"]["DELIVERY-1@1"]["current_state"] = "executing"
        evidence = evidence_record(subject)
        audit = {
            "schema_version": "1.0",
            "audit_id": "AUDIT-1",
            "version": "1",
            "subject": deepcopy(subject),
            "run_id": "RUN-1",
            "attempt_id": "ATTEMPT-1",
            "target_commit": COMMIT,
            "scope": ["src"],
            "environment": "ci",
            "policy_version": "1",
            "input_digests": [deepcopy(subject["digest"])],
            "clauses": [
                {
                    "clause_id": "CLAUSE-1",
                    "result": "FAIL",
                    "evidence_refs": [],
                }
            ],
            "overall": "FAIL",
            "recorded_at": NOW,
        }
        state["evidence"]["EVID-1@1"] = {
            "event_id": "EVENT-EVIDENCE",
            "record": evidence,
        }
        state["audits"]["AUDIT-1@1"] = {
            "event_id": "EVENT-AUDIT",
            "record": audit,
        }
        transition.update(old_state="executing", new_state="verified")
        transition["gate_refs"] = [
            {
                "ref_type": "evidence",
                "event_id": "EVENT-EVIDENCE",
                "record_id": "EVID-1",
                "record_version": "1",
                "digest": record_digest(evidence),
            },
            {
                "ref_type": "audit",
                "event_id": "EVENT-AUDIT",
                "record_id": "AUDIT-1",
                "record_version": "1",
                "digest": record_digest(audit),
            },
        ]
        with self.assertRaisesRegex(GateError, "cannot justify verified"):
            validate_transition(state, transition, at=NOW, current_event_id="EVENT-TRANSITION")

    def test_audit_overall_cannot_contradict_clause_results(self) -> None:
        state = trusted_state()
        subject = identity("TASK-1")
        state["artifacts"]["TASK-1@1"] = artifact(
            "TASK-1", "task", digest=subject["digest"]
        )
        state["current_versions"]["TASK-1"] = "1"
        evidence = evidence_record(subject)
        state["evidence"]["EVID-1@1"] = {
            "event_id": "EVENT-EVIDENCE",
            "record": evidence,
        }
        evidence_ref = {
            "ref_type": "evidence",
            "event_id": "EVENT-EVIDENCE",
            "record_id": "EVID-1",
            "record_version": "1",
            "digest": record_digest(evidence),
        }
        audit = {
            "schema_version": "1.0",
            "audit_id": "AUDIT-1",
            "version": "1",
            "subject": deepcopy(subject),
            "run_id": "RUN-1",
            "attempt_id": "ATTEMPT-1",
            "target_commit": COMMIT,
            "scope": ["src"],
            "environment": "ci",
            "policy_version": "1",
            "input_digests": [deepcopy(subject["digest"])],
            "clauses": [
                {
                    "clause_id": "CLAUSE-1",
                    "result": "PASS",
                    "evidence_refs": [evidence_ref],
                }
            ],
            "overall": "FAIL",
            "recorded_at": NOW,
        }
        with self.assertRaisesRegex(ReducerError, "overall must be derived"):
            apply(
                state,
                operation("OP-AUDIT", "audit_recorded", {"audit": audit}),
                event_id="EVENT-AUDIT",
            )

    def test_claim_requires_explicit_expiry_and_monotonic_fencing(self) -> None:
        state = trusted_state()
        task_identity = identity("TASK-1")
        state["artifacts"]["TASK-1@1"] = artifact(
            "TASK-1", "task", digest=task_identity["digest"]
        )
        state["current_versions"]["TASK-1"] = "1"
        state["states"]["TASK-1@1"] = {
            "schema_version": "1.0", "object": deepcopy(task_identity), "kind": "task",
            "initial_state": "draft", "current_state": "approved", "recovery_origin": None, "history": [],
        }
        first_claim = {
            "schema_version": "1.0",
            "claim_id": "CLAIM-1",
            "task": deepcopy(task_identity),
            "holder_actor_id": "actor-1",
            "lease_token": "1" * 64,
            "fencing_token": 1,
            "acquired_at": "2026-07-13T00:00:00Z",
            "expires_at": "2026-07-13T01:30:00Z",
        }
        state = apply(
            state,
            operation("OP-CLAIM-1", "claim_acquired", {"claim": first_claim}),
        )
        second_claim = deepcopy(first_claim)
        second_claim.update(
            claim_id="CLAIM-2",
            lease_token="2" * 64,
            fencing_token=2,
            acquired_at="2026-07-13T01:30:01Z",
            expires_at="2026-07-13T02:00:00Z",
        )
        with self.assertRaisesRegex(ReducerError, "explicitly recorded"):
            apply_operation(
                state,
                operation("OP-CLAIM-EARLY", "claim_acquired", {"claim": second_claim}),
                actor_id="actor-1",
                signer_fingerprint=ACTOR_FINGERPRINT,
                sequence=3,
                event_id="EVENT-EARLY",
                at="2026-07-13T01:30:01Z",
            )
        state = apply_operation(
            state,
            operation(
                "OP-EXPIRE",
                "claim_expired",
                {
                    "claim_id": "CLAIM-1",
                    "lease_token": "1" * 64,
                    "fencing_token": 1,
                    "expired_at": "2026-07-13T01:30:00Z",
                },
            ),
            actor_id="actor-1",
            signer_fingerprint=ACTOR_FINGERPRINT,
            sequence=3,
            event_id="EVENT-3",
            at="2026-07-13T01:30:00Z",
        )
        state = apply_operation(
            state,
            operation("OP-CLAIM-2", "claim_acquired", {"claim": second_claim}),
            actor_id="actor-1",
            signer_fingerprint=ACTOR_FINGERPRINT,
            sequence=4,
            event_id="EVENT-4",
            at="2026-07-13T01:30:01Z",
        )
        self.assertEqual(state["claims"]["CLAIM-2"]["status"], "active")
        self.assertEqual(state["claim_fences"]["TASK-1@1"], 2)
        with self.assertRaisesRegex(ReducerError, "fencing token does not match"):
            apply_operation(
                state,
                operation(
                    "OP-STALE-FENCE",
                    "claim_renewed",
                    {
                        "claim_id": "CLAIM-2",
                        "lease_token": "2" * 64,
                        "fencing_token": 1,
                        "expires_at": "2026-07-13T03:00:00Z",
                    },
                ),
                actor_id="actor-1",
                signer_fingerprint=ACTOR_FINGERPRINT,
                sequence=5,
                event_id="EVENT-5",
                at="2026-07-13T01:30:00Z",
            )

    def trace_state(self) -> tuple[dict, dict[str, dict]]:
        state = trusted_state()
        kinds = {
            "REQ-1": "requirement",
            "SPEC-1": "spec",
            "TASK-1": "task",
            "IMPL-1": "implementation",
            "TEST-1": "test",
            "EVID-1": "evidence",
            "AUDIT-1": "audit",
        }
        identities = {name: identity(name) for name in kinds}
        for name, node_type in kinds.items():
            state["artifacts"][name + "@1"] = artifact(
                name, node_type, digest=identities[name]["digest"]
            )
            state["current_versions"][name] = "1"
            state["trace_nodes"][name + "@1"] = {
                "schema_version": "1.0",
                "node": deepcopy(identities[name]),
                "node_type": node_type,
            }
        return state, identities

    def test_trace_relation_matrix_rejects_wrong_endpoints(self) -> None:
        state, nodes = self.trace_state()
        valid_edge = {
            "schema_version": "1.0",
            "edge_id": "EDGE-VALID",
            "from": nodes["REQ-1"],
            "to": nodes["SPEC-1"],
            "relation": "specifies",
        }
        state = apply(
            state,
            operation("OP-EDGE-VALID", "trace_edge_recorded", {"edge": valid_edge}),
        )
        self.assertIn("EDGE-VALID", state["trace_edges"])
        invalid_edge = deepcopy(valid_edge)
        invalid_edge.update(
            edge_id="EDGE-INVALID",
            **{"from": nodes["SPEC-1"], "to": nodes["REQ-1"]},
        )
        with self.assertRaisesRegex(ReducerError, "illegal trace relation endpoints"):
            apply(
                state,
                operation(
                    "OP-EDGE-INVALID", "trace_edge_recorded", {"edge": invalid_edge}
                ),
                sequence=3,
            )

    @staticmethod
    def add_edge(state: dict, edge_id: str, source: dict, target: dict, relation: str) -> None:
        state["trace_edges"][edge_id] = {
            "schema_version": "1.0",
            "edge_id": edge_id,
            "from": deepcopy(source),
            "to": deepcopy(target),
            "relation": relation,
        }

    def test_full_trace_closure_with_task_and_test_is_accepted(self) -> None:
        state, node = self.trace_state()
        self.add_edge(state, "E1", node["REQ-1"], node["SPEC-1"], "specifies")
        self.add_edge(state, "E2", node["SPEC-1"], node["TASK-1"], "derives")
        self.add_edge(state, "E3", node["TASK-1"], node["IMPL-1"], "implements")
        self.add_edge(state, "E4", node["IMPL-1"], node["TEST-1"], "derives")
        self.add_edge(state, "E5", node["TEST-1"], node["EVID-1"], "verifies")
        self.add_edge(state, "E6", node["EVID-1"], node["AUDIT-1"], "audits")
        validate_completion_closure(state, "greenfield", node["TASK-1"], [node["TASK-1"]], [node["EVID-1"]], [node["AUDIT-1"]])

    def test_shortcut_trace_closure_without_task_or_test_is_rejected(self) -> None:
        state, node = self.trace_state()
        self.add_edge(state, "E1", node["REQ-1"], node["SPEC-1"], "specifies")
        self.add_edge(state, "E2", node["SPEC-1"], node["IMPL-1"], "implements")
        self.add_edge(state, "E3", node["IMPL-1"], node["EVID-1"], "verifies")
        self.add_edge(state, "E4", node["EVID-1"], node["AUDIT-1"], "audits")
        with self.assertRaises(TraceabilityError):
            validate_completion_closure(state, "greenfield", node["TASK-1"], [node["TASK-1"]], [node["EVID-1"]], [node["AUDIT-1"]])

    def test_supersede_marks_transitive_dependents_stale(self) -> None:
        state = trusted_state()
        source_v1 = artifact("SOURCE-1", "source", version="1")
        source_identity = identity("SOURCE-1", digest=source_v1["digest"])
        spec = artifact("SPEC-1", "spec", derived_from=[source_identity])
        spec_identity = identity("SPEC-1", digest=spec["digest"])
        test = artifact("TEST-1", "test", derived_from=[spec_identity])
        for item in (source_v1, spec, test):
            state["artifacts"][item["artifact_id"] + "@" + item["version"]] = item
            state["current_versions"][item["artifact_id"]] = item["version"]
        source_v2 = artifact("SOURCE-1", "source", version="2")
        state = apply(
            state,
            operation(
                "OP-SUPERSEDE",
                "artifact_superseded",
                {
                    "artifact_id": "SOURCE-1",
                    "previous_version": "1",
                    "artifact": source_v2,
                },
            ),
        )
        self.assertEqual(state["artifacts"]["SOURCE-1@1"]["status"], "superseded")
        self.assertEqual(state["artifacts"]["SPEC-1@1"]["status"], "stale")
        self.assertEqual(state["artifacts"]["TEST-1@1"]["status"], "stale")
        self.assertEqual(state["current_versions"]["SOURCE-1"], "2")

    def test_delivery_blob_resolves_exact_digest_and_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            delivery = Path(temporary) / ".delivery"
            key = Ed25519PrivateKey.generate()
            public = key.public_key()
            content = b"immutable test log\n"
            digest = digest_bytes(content)
            event = build_signed_event(
                sequence=1,
                previous_event_hash=Revision.genesis().event_hash,
                event_id="EVENT-BLOB",
                event_type="test_blob_recorded",
                occurred_at=NOW,
                actor_id="actor-1",
                payload={"schema_version": "1.0"},
                private_key=key,
            )
            revision = commit_event(
                delivery,
                expected_revision=Revision.genesis(),
                event=event,
                key_resolver=lambda _: public,
                views={"blobs/sha256/" + digest["value"]: content},
            )
            authority = blob_authority(digest)
            self.assertEqual(
                resolve_authority(
                    authority, repository_map={}, delivery_root=delivery
                ),
                content,
            )
            generation = next((delivery / "generations").iterdir())
            blob = generation / "views/blobs/sha256" / digest["value"]
            blob.write_bytes(b"forged")
            with self.assertRaisesRegex(AuthorityError, "digest mismatch"):
                resolve_authority(
                    authority, repository_map={}, delivery_root=delivery
                )
            self.assertEqual(revision.sequence, 1)


if __name__ == "__main__":
    unittest.main()

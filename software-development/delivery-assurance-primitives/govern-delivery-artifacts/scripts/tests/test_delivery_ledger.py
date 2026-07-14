"""End-to-end security and migration tests for the single delivery ledger."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
CLI = SCRIPTS / "deliveryctl.py"
sys.path.insert(0, str(SCRIPTS))

from delivery_core.authority import digest_bytes  # noqa: E402
from delivery_core.canonical import canonical_json_bytes, loads_strict  # noqa: E402
from delivery_core.events import CAPABILITIES  # noqa: E402
from delivery_core.gates import record_digest  # noqa: E402
from delivery_core.ledger import Revision, build_signed_event  # noqa: E402
from delivery_core.service import replay  # noqa: E402
from delivery_core.transaction import commit_event  # noqa: E402


GIT = Path(shutil.which("git") or "").resolve(strict=True)
if GIT.parent.name.lower() == "cmd":
    GIT = (GIT.parent.parent / "mingw64" / "bin" / "git.exe").resolve(strict=True)
_GIT_RUNTIME_TEMP = tempfile.TemporaryDirectory()
GIT_SOURCE = GIT
GIT_ROOT = Path(_GIT_RUNTIME_TEMP.name)
shutil.copy2(GIT_SOURCE, GIT_ROOT / GIT_SOURCE.name)
for dependency in GIT_SOURCE.parent.glob("*.dll"):
    shutil.copy2(dependency, GIT_ROOT / dependency.name)
GIT = GIT_ROOT / GIT_SOURCE.name
GIT_SHA256 = hashlib.sha256(GIT.read_bytes()).hexdigest()
_GIT_MANIFEST_TEMP = tempfile.TemporaryDirectory()
GIT_MANIFEST = Path(_GIT_MANIFEST_TEMP.name) / "git-runtime.json"
GIT_FILES = {
    path.relative_to(GIT_ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in GIT_ROOT.rglob("*") if path.is_file() and not path.is_symlink()
}
GIT_MANIFEST.write_text(json.dumps({"schema_version": "1.0", "root": str(GIT_ROOT), "files": GIT_FILES}, sort_keys=True, separators=(",", ":")), encoding="utf-8")
GIT_MANIFEST_SHA256 = hashlib.sha256(GIT_MANIFEST.read_bytes()).hexdigest()


def run_cli(*args: object) -> subprocess.CompletedProcess[str]:
    values = list(map(str, args))
    if values and values[0] in {"commit", "validate", "recover", "authorize-diff"} and "--git-executable" not in values:
        values.extend(["--git-executable", str(GIT), "--git-sha256", GIT_SHA256, "--git-manifest", str(GIT_MANIFEST), "--git-manifest-sha256", GIT_MANIFEST_SHA256])
    return subprocess.run([sys.executable, str(CLI), *values], text=True, capture_output=True, check=False)


class DeliveryLedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.private = Path(self.temp.name) / "root.pem"
        self.public = Path(self.temp.name) / "root.pub.pem"
        self.trust = Path(self.temp.name) / "trust.json"
        self.clock = datetime.now(timezone.utc) - timedelta(minutes=4)
        self.event_minute = 0
        result = run_cli("bootstrap-trust", "--ledger-id", "LEDGER-TEST", "--private-key", self.private, "--public-key", self.public, "--trust-root", self.trust)
        self.assertEqual(result.returncode, 0, result.stderr)
        trust = json.loads(self.trust.read_text(encoding="utf-8"))
        self.policy = Path(self.temp.name) / "policy.json"
        self.policy.write_text(json.dumps({
            "schema_version": "1.0",
            "policy_id": "POLICY-1",
            "policy_version": "1",
            "ledger_id": "LEDGER-TEST",
            "root_key_fingerprint": trust["current_root_fingerprint"],
            "actors": [{
                "actor_id": "root",
                "public_key_pem": self.public.read_text(encoding="utf-8"),
                "key_fingerprint": trust["current_root_fingerprint"],
                "roles": ["root-controller"],
                "capabilities": CAPABILITIES,
                "path_scopes": ["specs", "src"],
                "environments": ["ci", "prod"],
                "valid_from": "2020-01-01T00:00:00Z",
                "valid_until": None,
                "revoked_at_sequence": None,
            }],
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def at(self, minutes: int) -> str:
        return (self.clock + timedelta(minutes=minutes)).isoformat(timespec="seconds").replace("+00:00", "Z")

    def init(self) -> str:
        result = run_cli(
            "init", "--root", self.root, "--trust-root", self.trust,
            "--root-signing-key", self.private, "--policy", self.policy,
            "--actor-id", "root", "--event-id", "EVENT-1", "--operation-id", "OP-1",
            "--at", self.at(0),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)["revision"]

    def write_operations(self, name: str, operations: list[dict]) -> Path:
        path = Path(self.temp.name) / name
        path.write_text(json.dumps(operations), encoding="utf-8")
        return path

    def git_authority(self) -> tuple[str, str, dict, dict]:
        subprocess.run(["git", "init", str(self.root)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Test"], check=True)
        (self.root / "specs").mkdir()
        body = b"task body\n"
        (self.root / "specs" / "task.md").write_bytes(body)
        subprocess.run(["git", "-C", str(self.root), "add", "specs/task.md"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-m", "task"], check=True, capture_output=True)
        uri = "https://example.invalid/delivery-test.git"
        subprocess.run(["git", "-C", str(self.root), "remote", "add", "origin", uri], check=True)
        commit = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
        digest = digest_bytes(body, "raw-v1")
        authority = {"schema_version": "1.0", "kind": "git", "repository_uri": uri, "commit": commit, "path": "specs/task.md"}
        return uri, commit, digest, authority

    def commit(self, revision: str, operations: Path, event_id: str, *extra: object) -> subprocess.CompletedProcess[str]:
        self.event_minute += 1
        return run_cli(
            "commit", "--root", self.root, "--trust-root", self.trust,
            "--expected-revision", revision, "--actor-id", "root", "--signing-key", self.private,
            "--event-id", event_id, "--at", self.at(self.event_minute), "--operations", operations,
            *extra,
        )

    def test_bootstrap_init_validate_and_direct_mutation_detection(self) -> None:
        revision = self.init()
        valid = run_cli("validate", "--root", self.root, "--trust-root", self.trust, "--expected-head", revision)
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        (self.root / ".delivery" / "approvals.json").write_text("{}", encoding="utf-8")
        blocked = run_cli("validate", "--root", self.root, "--trust-root", self.trust, "--expected-head", revision)
        self.assertEqual(blocked.returncode, 1)
        self.assertIn("unversioned delivery records", blocked.stdout)

    def test_registration_recomputes_authority_and_fake_digest_never_commits(self) -> None:
        uri, _, digest, authority = self.git_authority()
        revision = self.init()
        fake = dict(digest)
        fake["value"] = "0" * 64
        operation = self.write_operations("fake.json", [{
            "schema_version": "1.0", "operation_id": "OP-FAKE", "type": "artifact_registered",
            "payload": {"artifact": {
                "schema_version": "1.0", "artifact_id": "TASK-1", "artifact_type": "task", "version": "1",
                "digest": fake, "authority": authority, "derived_from": [], "status": "active", "created_at": "2026-01-01T00:01:00Z",
            }},
        }])
        result = self.commit(revision, operation, "EVENT-FAKE", "--repository-map", f"{uri}={self.root}")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual((self.root / ".delivery" / "HEAD.json").read_text(encoding="utf-8").count("\n"), 0)
        head = json.loads((self.root / ".delivery" / "HEAD.json").read_text(encoding="utf-8"))
        self.assertEqual(head["sequence"], 1)

    def test_provider_artifact_is_bound_to_signed_native_observation_blob(self) -> None:
        uri, _, digest, _ = self.git_authority()
        commit_id = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True, capture_output=True, check=True,
        ).stdout.strip()
        mapping = {
            "native-task": {
                "delivery_id": "TASK-1", "native_id": "native-task", "native_parent_id": "change-1",
                "artifact_type": "task", "authority_uri": "specs/task.md", "status": "ready",
                "content_hash": digest["value"],
            }
        }
        observed = {
            "schema_version": "1.0", "profile_id": "PROFILE-openspec", "profile_hash": "",
            "provider": "openspec", "mode": "native", "adapter_version": "1.0", "version": "1.2.3",
            "version_source": "C:/tools/openspec", "artifact_root": "openspec", "configuration": "openspec/config.yaml",
            "authorities": {"task": {"uri": "specs/task.md", "writer": "openspec"}},
            "id_mapping": mapping, "capabilities": ["change-status"],
            "command_entrypoints": {"status": "openspec status --json"},
            "runtime": {
                "executable": "openspec", "resolved_path": "C:/tools/openspec",
                "sha256": "2" * 64,
                "version_args": ["--version"], "observed_version": "1.2.3",
                "manifest": "C:/tools/openspec.runtime.json", "manifest_sha256": "3" * 64,
            },
            "observations": {"status": "1" * 64},
            "trust": {"level": "trusted", "reasons": ["native CLI and persisted state agree"]},
        }
        observed["profile_hash"] = digest_bytes(
            canonical_json_bytes({key: value for key, value in observed.items() if key != "profile_hash"}), "raw-v1",
        )["value"]
        observation_path = Path(self.temp.name) / "provider-profile.json"
        observation_path.write_bytes(canonical_json_bytes(observed))
        observation_digest = digest_bytes(observation_path.read_bytes(), "raw-v1")
        profile = {
            "schema_version": "1.0", "profile_id": "PROFILE-openspec", "version": "1",
            "provider": "openspec", "mode": "native", "provider_version": "1.2.3",
            "repository_uri": uri, "commit": commit_id, "id_mapping": mapping,
            "observation_authority": {
                "schema_version": "1.0", "kind": "delivery_blob", "digest": observation_digest,
            },
            "observed_at": "2026-01-01T00:01:00Z",
        }
        provider_authority = {
            "schema_version": "1.0", "kind": "provider", "profile_id": "PROFILE-openspec",
            "profile_version": "1", "profile_digest": record_digest(profile), "native_id": "native-task",
            "artifact_kind": "task", "repository_uri": uri, "commit": commit_id, "path": "specs/task.md",
        }
        operations = self.write_operations("provider.json", [
            {
                "schema_version": "1.0", "operation_id": "OP-PROFILE", "type": "provider_profile_observed",
                "payload": {"profile": profile},
            },
            {
                "schema_version": "1.0", "operation_id": "OP-PROVIDER-ART", "type": "artifact_registered",
                "payload": {"artifact": {
                    "schema_version": "1.0", "artifact_id": "TASK-1", "artifact_type": "task", "version": "1",
                    "digest": digest, "authority": provider_authority, "derived_from": [], "status": "active",
                    "created_at": "2026-01-01T00:01:00Z",
                }},
            },
        ])
        revision = self.init()
        committed = self.commit(
            revision, operations, "EVENT-PROVIDER", "--blob", observation_path,
            "--repository-map", f"{uri}={self.root}",
        )
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        head = json.loads(committed.stdout)["revision"]
        valid = run_cli(
            "validate", "--root", self.root, "--trust-root", self.trust, "--expected-head", head,
            "--repository-map", f"{uri}={self.root}",
        )
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        bad_profile = dict(profile)
        bad_profile["version"] = "2"
        bad_profile["provider_version"] = "9.9.9"
        bad = self.write_operations("bad-provider.json", [{
            "schema_version": "1.0", "operation_id": "OP-BAD-PROFILE", "type": "provider_profile_observed",
            "payload": {"profile": bad_profile},
        }])
        rejected = self.commit(head, bad, "EVENT-BAD-PROVIDER", "--repository-map", f"{uri}={self.root}")
        self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
        self.assertIn("provider observation differs", rejected.stdout)

    def test_two_process_claim_race_has_one_fenced_winner(self) -> None:
        uri, _, digest, authority = self.git_authority()
        revision = self.init()
        artifact_op = self.write_operations("artifact.json", [{
            "schema_version": "1.0", "operation_id": "OP-ART", "type": "artifact_registered",
            "payload": {"artifact": {
                "schema_version": "1.0", "artifact_id": "TASK-1", "artifact_type": "task", "version": "1",
                "digest": digest, "authority": authority, "derived_from": [], "status": "active", "created_at": "2026-01-01T00:01:00Z",
            }},
        }, {
            "schema_version": "1.0", "operation_id": "OP-STATE", "type": "state_object_registered",
            "payload": {"state_object": {
                "schema_version": "1.0", "object": {"artifact_id": "TASK-1", "version": "1", "digest": digest},
                "kind": "task", "initial_state": "draft",
            }},
        }])
        registered = self.commit(revision, artifact_op, "EVENT-2", "--repository-map", f"{uri}={self.root}")
        self.assertEqual(registered.returncode, 0, registered.stdout + registered.stderr)
        revision2 = json.loads(registered.stdout)["revision"]
        paths = []
        for index in (1, 2):
            paths.append(self.write_operations(f"claim-{index}.json", [{
                "schema_version": "1.0", "operation_id": f"OP-CLAIM-{index}", "type": "claim_acquired",
                "payload": {"claim": {
                    "schema_version": "1.0", "claim_id": f"CLAIM-{index}",
                    "task": {"artifact_id": "TASK-1", "version": "1", "digest": digest},
                    "holder_actor_id": "root", "lease_token": str(index) * 64, "fencing_token": 1,
                    "acquired_at": self.at(1), "expires_at": self.at(60),
                }},
            }]))
        commands = []
        for index, path in enumerate(paths, 1):
            commands.append([
                sys.executable, str(CLI), "commit", "--root", str(self.root), "--trust-root", str(self.trust),
                "--expected-revision", revision2, "--actor-id", "root", "--signing-key", str(self.private),
                "--event-id", f"EVENT-CLAIM-{index}", "--at", self.at(2), "--operations", str(path),
                "--repository-map", f"{uri}={self.root}",
                "--git-executable", str(GIT), "--git-sha256", GIT_SHA256,
                "--git-manifest", str(GIT_MANIFEST), "--git-manifest-sha256", GIT_MANIFEST_SHA256,
            ])
        processes = [subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for command in commands]
        results = [process.communicate() + (process.returncode,) for process in processes]
        self.assertEqual(sorted(item[2] for item in results), [0, 1], results)
        winner = next(json.loads(item[0])["revision"] for item in results if item[2] == 0)
        valid = run_cli("validate", "--root", self.root, "--trust-root", self.trust, "--expected-head", winner, "--repository-map", f"{uri}={self.root}")
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

    def test_authorize_diff_requires_exact_signed_run_approval_and_fenced_claim(self) -> None:
        uri, base, digest, authority = self.git_authority()
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "src/app.py"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-m", "implementation"], check=True, capture_output=True)
        target = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True, capture_output=True, check=True,
        ).stdout.strip()
        revision = self.init()
        subject = {"artifact_id": "TASK-1", "version": "1", "digest": digest}
        operations = self.write_operations("authorized.json", [
            {
                "schema_version": "1.0", "operation_id": "OP-ART", "type": "artifact_registered",
                "payload": {"artifact": {
                    "schema_version": "1.0", "artifact_id": "TASK-1", "artifact_type": "task", "version": "1",
                    "digest": digest, "authority": authority, "derived_from": [], "status": "active",
                    "created_at": "2026-01-01T00:01:00Z",
                }},
            },
            {
                "schema_version": "1.0", "operation_id": "OP-RUN", "type": "run_started",
                "payload": {"run": {
                    "schema_version": "1.0", "run_id": "RUN-1", "suite": "greenfield",
                    "target_commit": target, "inputs": [subject], "started_at": self.at(0),
                }},
            },
            {
                "schema_version": "1.0", "operation_id": "OP-STATE", "type": "state_object_registered",
                "payload": {"state_object": {
                    "schema_version": "1.0", "object": subject, "kind": "task", "initial_state": "draft",
                }},
            },
            {
                "schema_version": "1.0", "operation_id": "OP-ATTEMPT", "type": "attempt_started",
                "payload": {"attempt": {
                    "schema_version": "1.0", "attempt_id": "ATTEMPT-1", "run_id": "RUN-1", "sequence": 1,
                    "target_commit": target, "input_digests": [digest], "started_at": self.at(0),
                }},
            },
            {
                "schema_version": "1.0", "operation_id": "OP-APPROVAL", "type": "approval_recorded",
                "payload": {"approval": {
                    "schema_version": "1.0", "approval_id": "APP-1", "version": "1", "subject": subject,
                    "run_id": "RUN-1", "attempt_id": "ATTEMPT-1", "base_commit": base, "target_commit": target,
                    "scope": ["src"], "environment": "ci", "decision": "APPROVED",
                    "issued_at": self.at(0), "expires_at": self.at(60), "nonce": "N-1",
                }},
            },
            {
                "schema_version": "1.0", "operation_id": "OP-CLAIM", "type": "claim_acquired",
                "payload": {"claim": {
                    "schema_version": "1.0", "claim_id": "CLAIM-1", "task": subject,
                    "holder_actor_id": "root", "lease_token": "a" * 64, "fencing_token": 1,
                    "acquired_at": self.at(0), "expires_at": self.at(60),
                }},
            },
        ])
        committed = self.commit(
            revision, operations, "EVENT-AUTH",
            "--repository-map", f"{uri}={self.root}",
        )
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        head = json.loads(committed.stdout)["revision"]
        common = (
            "authorize-diff", "--root", self.root, "--trust-root", self.trust, "--expected-head", head,
            "--repository-uri", uri, "--repository-map", f"{uri}={self.root}", "--base", base,
            "--target", target, "--actor-id", "root", "--claim-id", "CLAIM-1", "--lease-token", "a" * 64,
            "--fencing-token", 1, "--run-id", "RUN-1", "--attempt-id", "ATTEMPT-1", "--environment", "ci",
            "--at", self.at(4),
        )
        allowed = run_cli(*common)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertEqual(json.loads(allowed.stdout)["changed"], ["src/app.py"])
        stale_fence = list(common)
        stale_fence[stale_fence.index("--fencing-token") + 1] = 2
        blocked = run_cli(*stale_fence)
        self.assertEqual(blocked.returncode, 1, blocked.stdout + blocked.stderr)

    def test_recovery_rejects_signed_but_semantically_invalid_prepared_event(self) -> None:
        revision_text = self.init()
        revision = Revision.parse(revision_text)
        current = replay(self.root, self.trust, revision)
        operation = {
            "schema_version": "1.0", "operation_id": "OP-BAD-CLAIM", "type": "claim_acquired",
            "payload": {"claim": {
                "schema_version": "1.0", "claim_id": "CLAIM-BAD",
                "task": {
                    "artifact_id": "TASK-MISSING", "version": "1",
                    "digest": {"algorithm": "sha256", "canonicalization": "raw-v1", "value": "0" * 64},
                },
                "holder_actor_id": "root", "lease_token": "b" * 64, "fencing_token": 1,
                "acquired_at": self.at(1), "expires_at": self.at(60),
            }},
        }
        event = build_signed_event(
            sequence=2, previous_event_hash=revision.event_hash, event_id="EVENT-PREPARED",
            event_type="delivery_transaction", occurred_at=self.at(1), actor_id="root",
            payload={"operations": [operation]}, private_key=self.private,
        )
        public_key = self.public.read_bytes()
        with self.assertRaises(RuntimeError):
            commit_event(
                self.root / ".delivery", expected_revision=revision, event=event,
                key_resolver=lambda _: public_key, views={"state.json": current.state},
                fault_injector=lambda point: (_ for _ in ()).throw(RuntimeError("crash"))
                if point == "after_generation_install" else None,
            )
        recovered = run_cli(
            "recover", "--root", self.root, "--trust-root", self.trust, "--expected-revision", revision_text,
        )
        self.assertEqual(recovered.returncode, 1, recovered.stdout + recovered.stderr)
        self.assertIn("artifact identity does not resolve", recovered.stdout)
        head = loads_strict((self.root / ".delivery" / "HEAD.json").read_bytes())
        self.assertEqual(head["sequence"], 1)

    def test_unknown_schema_is_input_error_and_unsigned_files_have_no_authority(self) -> None:
        revision = self.init()
        bad = self.write_operations("bad.json", [{"schema_version": "0", "operation_id": "BAD", "type": "run_started", "payload": {}}])
        result = self.commit(revision, bad, "EVENT-BAD")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        unsigned = self.root / ".delivery" / "approvals.json"
        unsigned.write_text(json.dumps({"approvals": [{"decision": "APPROVED"}]}), encoding="utf-8")
        validate = run_cli("validate", "--root", self.root, "--trust-root", self.trust, "--expected-head", revision)
        self.assertEqual(validate.returncode, 1)

    def test_specflow_migration_is_one_shot_and_legacy_approval_is_untrusted(self) -> None:
        legacy = self.root / ".specflow"
        legacy.mkdir()
        (legacy / "approvals.json").write_text(json.dumps({"approvals": [{"approval_id": "APP-OLD", "decision": "APPROVED"}]}), encoding="utf-8")
        result = run_cli(
            "migrate-specflow", "--root", self.root, "--trust-root", self.trust,
            "--root-signing-key", self.private, "--policy", self.policy, "--actor-id", "root",
            "--event-id", "EVENT-MIGRATE", "--operation-id", "OP-GENESIS", "--migration-id", "MIG-1",
            "--migration-operation-id", "OP-MIGRATE", "--at", self.at(0),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        revision = json.loads(result.stdout)["revision"]
        self.assertFalse(legacy.exists())
        state = json.loads(next((self.root / ".delivery" / "generations").glob("*/views/state.json")).read_text(encoding="utf-8"))
        self.assertIn("APP-OLD", state["migrations"]["MIG-1"]["record"]["untrusted_record_ids"])
        self.assertEqual(state["approvals"], {})
        valid = run_cli("validate", "--root", self.root, "--trust-root", self.trust, "--expected-head", revision)
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

    def test_unversioned_delivery_migration_has_atomic_cutover(self) -> None:
        legacy = self.root / ".delivery"
        legacy.mkdir()
        (legacy / "state.json").write_text(json.dumps({"objects": [{"object_id": "OLD"}]}), encoding="utf-8")
        result = run_cli(
            "migrate-delivery", "--root", self.root, "--trust-root", self.trust,
            "--root-signing-key", self.private, "--policy", self.policy, "--actor-id", "root",
            "--event-id", "EVENT-MIGRATE", "--operation-id", "OP-GENESIS", "--migration-id", "MIG-D",
            "--migration-operation-id", "OP-MIGRATE", "--at", self.at(0),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((legacy / "HEAD.json").is_file())
        self.assertFalse((self.root / ".delivery-legacy-migration").exists())
        revision = json.loads(result.stdout)["revision"]
        valid = run_cli("validate", "--root", self.root, "--trust-root", self.trust, "--expected-head", revision)
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for the trusted delivery ledger and transaction storage core."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from delivery_core.canonical import (  # noqa: E402
    CanonicalizationError,
    canonical_json_bytes,
    canonicalize,
    loads_strict,
)
from delivery_core.crypto import (  # noqa: E402
    SignatureError,
    private_key_pem,
    public_key_fingerprint,
    public_key_pem,
    sign,
    verify,
)
from delivery_core.ledger import (  # noqa: E402
    LedgerError,
    Revision,
    build_signed_event,
    load_committed_events,
    read_head,
    validate_chain,
)
from delivery_core.schema import SchemaRegistry, SchemaValidationError  # noqa: E402
from delivery_core.transaction import (  # noqa: E402
    LockUnavailable,
    RecoveryRequired,
    RepositoryLock,
    RevisionConflict,
    SimulatedCrash,
    TransactionError,
    commit_event,
    inspect_store,
    recover_transaction,
)


class DeliveryCoreStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key = Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()
        self.resolver = lambda event: self.public_key

    def event(self, parent: Revision, number: int = 1):
        return build_signed_event(
            sequence=parent.sequence + 1,
            previous_event_hash=parent.event_hash,
            event_id="EVENT-{}".format(number),
            event_type="test_recorded",
            occurred_at="2026-07-13T12:00:{:02d}Z".format(number),
            actor_id="ACTOR-1",
            payload={"schema_version": "1.0", "value": number},
            private_key=self.private_key,
        )

    def test_delivery_json_v1_is_deterministic_and_rejects_ambiguity(self) -> None:
        left = {"z": "e\u0301", "a": [1, True, None]}
        right = {"a": [1, True, None], "z": "\u00e9"}
        self.assertEqual(canonical_json_bytes(left), canonical_json_bytes(right))
        self.assertEqual(
            canonicalize("a\r\nb\rc", "utf8-nfc-lf-v1"), b"a\nb\nc"
        )
        self.assertEqual(canonicalize(b"raw", "raw-v1"), b"raw")
        with self.assertRaises(CanonicalizationError):
            loads_strict('{"a":1,"a":2}')
        with self.assertRaises(CanonicalizationError):
            loads_strict('{"value":1.5}')
        with self.assertRaises(CanonicalizationError):
            canonical_json_bytes({"value": 1.5})
        with self.assertRaises(CanonicalizationError):
            canonical_json_bytes({"e\u0301": 1, "\u00e9": 2})
        with self.assertRaises(CanonicalizationError):
            canonicalize(b"x", "unknown-v1")

    def test_ed25519_pem_fingerprint_and_signature(self) -> None:
        private_pem = private_key_pem(self.private_key)
        public_pem = public_key_pem(self.public_key)
        signature = sign(private_pem, b"message")
        verify(public_pem, b"message", signature)
        self.assertTrue(public_key_fingerprint(public_pem).startswith("sha256:"))
        with self.assertRaises(SignatureError):
            verify(public_pem, b"changed", signature)
        with self.assertRaises(SignatureError):
            verify(public_pem, b"message", signature + "=")

    def test_missing_crypto_dependency_is_an_explicit_environment_error(self) -> None:
        command = (
            "import sys; sys.path.insert(0, {!r}); "
            "\ntry:\n import delivery_core.crypto\n"
            "except RuntimeError as exc:\n print(str(exc)); raise SystemExit(0)\n"
            "raise SystemExit(1)"
        ).format(str(SCRIPTS))
        result = subprocess.run(
            [sys.executable, "-S", "-c", command],
            text=True,
            capture_output=True,
            check=False,
            env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("required dependency unavailable: cryptography", result.stdout)

    def test_schema_registry_requires_explicit_version_and_exact_schema(self) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["schema_version", "name"],
            "additionalProperties": False,
            "properties": {
                "schema_version": {"const": "1.0"},
                "name": {"type": "string", "minLength": 1},
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shared = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "shared.schema.json",
                "type": "string",
                "minLength": 1,
            }
            schema["properties"]["name"] = {"$ref": "shared.schema.json"}
            (root / "shared.schema.json").write_bytes(canonical_json_bytes(shared))
            (root / "record.schema.json").write_bytes(canonical_json_bytes(schema))
            registry = SchemaRegistry(root)
            registry.validate("record", {"schema_version": "1.0", "name": "ok"})
            with self.assertRaises(SchemaValidationError):
                registry.validate("record", {"schema_version": "0", "name": "old"})
            with self.assertRaises(SchemaValidationError):
                registry.validate(
                    "record",
                    {"schema_version": "1.0", "name": "ok", "extra": True},
                )

    def test_signed_hash_chain_detects_content_key_and_head_tampering(self) -> None:
        first = self.event(Revision.genesis(), 1)
        first_revision = Revision(1, first["event_hash"])
        second = self.event(first_revision, 2)
        head = Revision(2, second["event_hash"])
        validate_chain([first, second], self.resolver, expected_head=head)

        tampered = json.loads(json.dumps(second))
        tampered["payload"]["value"] = 99
        with self.assertRaises(LedgerError):
            validate_chain([first, tampered], self.resolver, expected_head=head)

        other_public = Ed25519PrivateKey.generate().public_key()
        with self.assertRaises(LedgerError):
            validate_chain([first], lambda event: other_public, expected_head=first_revision)

        with self.assertRaises(LedgerError):
            validate_chain([first], self.resolver, expected_head=head)

    def test_commit_uses_expected_head_and_atomic_generation_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            delivery = Path(temporary) / ".delivery"
            genesis = Revision.genesis()
            first = self.event(genesis, 1)
            first_revision = commit_event(
                delivery,
                expected_revision=genesis,
                event=first,
                key_resolver=self.resolver,
                views={"state.json": {"schema_version": "1.0", "state": "captured"}},
            )
            self.assertEqual(read_head(delivery), first_revision)
            generation = delivery / "generations" / (
                "{:020d}-{}".format(first_revision.sequence, first_revision.event_hash)
            )
            self.assertTrue((generation / "event.json").is_file())
            self.assertTrue((generation / "views/state.json").is_file())
            self.assertTrue((generation / "manifest.json").is_file())
            inspect_store(
                delivery,
                expected_revision=first_revision,
                key_resolver=self.resolver,
            )

            second = self.event(first_revision, 2)
            with self.assertRaises(RevisionConflict):
                commit_event(
                    delivery,
                    expected_revision=genesis,
                    event=second,
                    key_resolver=self.resolver,
                )
            second_revision = commit_event(
                delivery,
                expected_revision=first_revision,
                event=second,
                key_resolver=self.resolver,
            )
            events = load_committed_events(delivery, second_revision)
            self.assertEqual(len(events), 2)
            validate_chain(events, self.resolver, expected_head=second_revision)

    def test_repository_lock_fails_closed_for_concurrent_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / ".delivery/.lock"
            with RepositoryLock(lock_path):
                with self.assertRaises(LockUnavailable):
                    with RepositoryLock(lock_path):
                        self.fail("second lock acquisition unexpectedly succeeded")

    def test_crash_after_generation_install_requires_explicit_roll_forward(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            delivery = Path(temporary) / ".delivery"
            genesis = Revision.genesis()
            event = self.event(genesis, 1)

            def crash(stage: str) -> None:
                if stage == "after_generation_install":
                    raise SimulatedCrash(stage)

            with self.assertRaises(SimulatedCrash):
                commit_event(
                    delivery,
                    expected_revision=genesis,
                    event=event,
                    key_resolver=self.resolver,
                    fault_injector=crash,
                )
            self.assertEqual(read_head(delivery), genesis)
            with self.assertRaises(RecoveryRequired):
                inspect_store(
                    delivery,
                    expected_revision=genesis,
                    key_resolver=self.resolver,
                )
            recovered = recover_transaction(
                delivery,
                expected_revision=genesis,
                key_resolver=self.resolver,
            )
            self.assertEqual(recovered, Revision(1, event["event_hash"]))
            inspect_store(
                delivery,
                expected_revision=recovered,
                key_resolver=self.resolver,
            )

    def test_crash_after_staging_requires_explicit_roll_forward(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            delivery = Path(temporary) / ".delivery"
            genesis = Revision.genesis()
            event = self.event(genesis, 1)

            def crash(stage: str) -> None:
                if stage == "after_stage_fsync":
                    raise SimulatedCrash(stage)

            with self.assertRaises(SimulatedCrash):
                commit_event(
                    delivery,
                    expected_revision=genesis,
                    event=event,
                    key_resolver=self.resolver,
                    fault_injector=crash,
                )
            with self.assertRaises(RecoveryRequired):
                inspect_store(
                    delivery,
                    expected_revision=genesis,
                    key_resolver=self.resolver,
                )
            recovered = recover_transaction(
                delivery,
                expected_revision=genesis,
                key_resolver=self.resolver,
            )
            self.assertEqual(recovered.event_hash, event["event_hash"])

    def test_corrupt_or_ambiguous_orphan_cannot_be_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            delivery = Path(temporary) / ".delivery"
            transactions = delivery / ".transactions"
            transactions.mkdir(parents=True)
            (transactions / "partial").mkdir()
            with self.assertRaises(RecoveryRequired):
                recover_transaction(
                    delivery,
                    expected_revision=Revision.genesis(),
                    key_resolver=self.resolver,
                )
            (transactions / "second").mkdir()
            with self.assertRaises(RecoveryRequired):
                recover_transaction(
                    delivery,
                    expected_revision=Revision.genesis(),
                    key_resolver=self.resolver,
                )

    def test_committed_manifest_or_event_tampering_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            delivery = Path(temporary) / ".delivery"
            genesis = Revision.genesis()
            event = self.event(genesis, 1)
            revision = commit_event(
                delivery,
                expected_revision=genesis,
                event=event,
                key_resolver=self.resolver,
                views={"registry.json": {"schema_version": "1.0", "items": []}},
            )
            generation = next((delivery / "generations").iterdir())
            view = generation / "views/registry.json"
            view.write_text('{"items":["forged"],"schema_version":"1.0"}', encoding="utf-8")
            with self.assertRaises(RecoveryRequired):
                inspect_store(
                    delivery,
                    expected_revision=revision,
                    key_resolver=self.resolver,
                )

    def test_view_path_traversal_is_rejected_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            delivery = Path(temporary) / ".delivery"
            genesis = Revision.genesis()
            with self.assertRaises(TransactionError):
                commit_event(
                    delivery,
                    expected_revision=genesis,
                    event=self.event(genesis, 1),
                    key_resolver=self.resolver,
                    views={"../outside.json": {}},
                )
            self.assertFalse((Path(temporary) / "outside.json").exists())


if __name__ == "__main__":
    unittest.main()

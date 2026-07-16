"""Focused reconciliation tests for provider observations."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from delivery_core.provider import (  # noqa: E402
    ProviderSyncConflict,
    ProviderSyncError,
    build_provider_operations,
)
from delivery_core.reducer import empty_state  # noqa: E402


def mapping(
    delivery_id: str,
    native_id: str,
    *,
    parent: str | None = None,
    artifact_type: str = "spec",
    path: str | None = None,
    canonicalization: str = "raw-v1",
) -> dict:
    return {
        "delivery_id": delivery_id,
        "native_id": native_id,
        "native_parent_id": parent,
        "artifact_type": artifact_type,
        "authority_uri": path or f"openspec/{native_id}.md",
        "status": "ready",
        "content_hash": "a" * 64,
        "content_canonicalization": canonicalization,
    }


def observation(mappings: dict, *, root: str = "openspec") -> dict:
    observed = {
        "schema_version": "1.0",
        "profile_id": "PROFILE-openspec",
        "profile_hash": "",
        "provider": "openspec",
        "mode": "native",
        "version": "1.2.3",
        "artifact_root": root,
        "id_mapping": mappings,
    }
    observed["profile_hash"] = hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return observed


def build(state: dict, observed: dict):
    return build_provider_operations(
        state,
        observed,
        repository_uri="https://example.invalid/repo.git",
        commit="c" * 40,
        at="2026-01-01T00:00:00Z",
        operation_id_prefix="OP-PROVIDER",
    )


class ProviderBridgeTest(unittest.TestCase):
    def test_parent_graph_is_deterministic_and_records_exact_dependency(self) -> None:
        observed = observation({
            "native:child": mapping("SPEC-CHILD", "child", parent="root"),
            "native:root": mapping("SPEC-ROOT", "root"),
        })
        operations, _, counts = build(empty_state(), observed)
        artifacts = {
            item["payload"]["artifact"]["artifact_id"]: item["payload"]["artifact"]
            for item in operations if item["type"] == "artifact_registered"
        }
        self.assertEqual(counts["registered"], 2)
        self.assertEqual(artifacts["SPEC-CHILD"]["derived_from"], [{
            "artifact_id": "SPEC-ROOT",
            "version": artifacts["SPEC-ROOT"]["version"],
            "digest": artifacts["SPEC-ROOT"]["digest"],
        }])

    def test_invalid_provider_graph_and_identity_inputs_fail_closed(self) -> None:
        cases = {
            "unsafe root": observation({"native": mapping("SPEC-1", "one")}, root="../openspec"),
            "escaped path": observation({"native": mapping("SPEC-1", "one", path="specs/one.md")}),
            "duplicate delivery ID": observation({
                "native:one": mapping("SPEC-1", "one"),
                "native:two": mapping("SPEC-1", "two"),
            }),
            "unsupported canonicalization": observation({
                "native": mapping("SPEC-1", "one", canonicalization="unsupported-v1"),
            }),
            "unsupported artifact type": observation({
                "native": mapping("SPEC-1", "one", artifact_type="unknown"),
            }),
            "cycle": observation({
                "native:one": mapping("SPEC-1", "one", parent="two"),
                "native:two": mapping("SPEC-2", "two", parent="one"),
            }),
            "ambiguous parent": observation({
                "native:one": mapping("SPEC-1", "same"),
                "native:two": mapping("SPEC-2", "same"),
                "native:child": mapping("SPEC-3", "child", parent="same"),
            }),
        }
        for name, observed in cases.items():
            with self.subTest(name=name), self.assertRaises(ProviderSyncError):
                build(empty_state(), observed)

    def test_provider_cannot_take_over_an_existing_git_artifact(self) -> None:
        state = empty_state()
        state["current_versions"]["SPEC-1"] = "1"
        state["artifacts"]["SPEC-1@1"] = {
            "artifact_id": "SPEC-1",
            "version": "1",
            "authority": {"kind": "git"},
        }
        with self.assertRaisesRegex(ProviderSyncConflict, "take over"):
            build(state, observation({"native": mapping("SPEC-1", "one")}))

    def test_empty_observation_deprecates_every_active_artifact_for_profile(self) -> None:
        first_operations, _, _ = build(
            empty_state(), observation({"native": mapping("SPEC-1", "one")}),
        )
        profile = first_operations[0]["payload"]["profile"]
        artifact = first_operations[1]["payload"]["artifact"]
        state = empty_state()
        state["provider_profiles"][f"{profile['profile_id']}@{profile['version']}"] = {
            "event_id": "EVENT-1", "record": profile, "digest": artifact["authority"]["profile_digest"],
        }
        state["current_versions"]["SPEC-1"] = artifact["version"]
        state["artifacts"][f"SPEC-1@{artifact['version']}"] = artifact
        operations, _, counts = build(state, observation({}))
        self.assertEqual(counts["deprecated"], 1)
        self.assertEqual(operations[-1]["payload"]["artifact"]["status"], "deprecated")

    def test_deep_mapping_graph_remains_linear_in_output_size(self) -> None:
        mappings = {}
        for index in range(2_000):
            parent = None if index == 0 else f"spec-{index - 1}"
            mappings[f"native:{index}"] = mapping(
                f"SPEC-{index}", f"spec-{index}", parent=parent,
            )
        operations, _, counts = build(empty_state(), observation(mappings))
        self.assertEqual(counts["registered"], 2_000)
        self.assertEqual(len(operations), 2_001)
        last = operations[-1]["payload"]["artifact"]
        self.assertEqual(last["derived_from"][0]["artifact_id"], "SPEC-1998")

    def test_deterministic_artifact_version_collision_is_rejected(self) -> None:
        observed = observation({"native": mapping("SPEC-1", "one")})
        operations, _, _ = build(empty_state(), observed)
        artifact = deepcopy(operations[1]["payload"]["artifact"])
        state = empty_state()
        state["artifacts"][f"SPEC-1@{artifact['version']}"] = artifact
        with self.assertRaisesRegex(ProviderSyncConflict, "version collides"):
            build(state, observed)


if __name__ == "__main__":
    unittest.main()

"""Repository-wide structural tests for every bundled Skill."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def skill_documents() -> list[Path]:
    return sorted((ROOT / "software-development").glob("**/SKILL.md"))


def frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise AssertionError(f"missing YAML frontmatter: {path}")
    return yaml.safe_load(parts[1]), parts[2].strip()


class SkillRepositoryTest(unittest.TestCase):
    def test_all_skills_have_unique_folder_bound_metadata_and_nonempty_bodies(self) -> None:
        documents = skill_documents()
        self.assertGreater(len(documents), 0)
        names: list[str] = []
        for path in documents:
            with self.subTest(skill=path.parent.name):
                metadata, body = frontmatter(path)
                self.assertEqual(set(metadata), {"name", "description"})
                self.assertRegex(metadata["name"], NAME)
                self.assertEqual(metadata["name"], path.parent.name)
                self.assertIsInstance(metadata["description"], str)
                self.assertTrue(metadata["description"].strip())
                self.assertTrue(body)
                self.assertLessEqual(len(body.splitlines()), 500)
                names.append(metadata["name"])
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 21)

    def test_skill_local_markdown_links_resolve(self) -> None:
        for path in skill_documents():
            for target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
                target = target.strip().strip("<>").split("#", 1)[0]
                if not target or target.startswith("/") or re.match(r"^[a-z][a-z0-9+.-]*://", target):
                    continue
                with self.subTest(skill=path.parent.name, target=target):
                    self.assertTrue((path.parent / target).resolve().exists())

    def test_agents_metadata_matches_each_skill(self) -> None:
        for path in skill_documents():
            metadata_path = path.parent / "agents" / "openai.yaml"
            with self.subTest(skill=path.parent.name):
                self.assertTrue(metadata_path.is_file())
                value = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
                self.assertEqual(set(value), {"interface"})
                interface = value["interface"]
                self.assertEqual(
                    set(interface), {"display_name", "short_description", "default_prompt"},
                )
                self.assertTrue(all(isinstance(item, str) and item.strip() for item in interface.values()))
                self.assertIn("$" + path.parent.name, interface["default_prompt"])

    def test_self_hosted_delivery_locator_and_sidecar_are_publishable(self) -> None:
        descriptor = json.loads((ROOT / ".delivery-project.json").read_text(encoding="utf-8"))
        self.assertEqual(descriptor["schema_version"], "1.0")
        self.assertEqual(descriptor["provider"], "openspec")
        self.assertEqual(descriptor["ledger_id"], "LEDGER-SKILLS")
        self.assertIn("not a trust anchor", descriptor["warning"])
        self.assertTrue((ROOT / descriptor["deliveryctl"]).is_file())
        for name in ("trust_root", "checkpoint", "policy", "git_executable", "git_manifest"):
            value = Path(descriptor["external_anchor"][name])
            self.assertFalse(value.is_absolute())
            self.assertNotIn("..", value.parts)

        delivery = ROOT / ".delivery"
        head = json.loads((delivery / "HEAD.json").read_text(encoding="utf-8"))
        self.assertEqual(set(head), {"schema_version", "sequence", "event_hash", "generation", "manifest_hash"})
        self.assertGreaterEqual(head["sequence"], 1)
        generation = delivery / "generations" / head["generation"]
        self.assertTrue(generation.is_dir())
        manifest_path = generation / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), head["manifest_hash"])
        manifest = json.loads(manifest_bytes)
        self.assertEqual(manifest["generation"], head["generation"])
        for relative, expected in manifest["files"].items():
            candidate = generation / Path(relative)
            self.assertTrue(candidate.is_file())
            self.assertEqual(hashlib.sha256(candidate.read_bytes()).hexdigest(), expected)

        forbidden = list(ROOT.rglob("*.pem"))
        forbidden.extend(path for name in ("trust-root.json", "policy.json") for path in ROOT.rglob(name))
        self.assertEqual(forbidden, [])

    def test_self_hosted_openspec_change_decomposes_repository_work(self) -> None:
        config = yaml.safe_load((ROOT / "openspec" / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(config["schema"], "spec-driven")
        change = ROOT / "openspec" / "changes" / "self-host-delivery-progress"
        self.assertTrue((change / ".openspec.yaml").is_file())
        for name in ("proposal.md", "design.md", "tasks.md"):
            self.assertTrue((change / name).is_file())
        self.assertEqual(len(list((change / "specs").glob("*/spec.md"))), 3)
        tasks = re.findall(
            r"^- \[[ xX]\] ([A-Za-z0-9][A-Za-z0-9._-]*)\s+.+$",
            (change / "tasks.md").read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
        self.assertEqual(tasks, ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1"])


if __name__ == "__main__":
    unittest.main()

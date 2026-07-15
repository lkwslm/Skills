#!/usr/bin/env python3
"""Tests for strict, read-only Spec provider adapters."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from jsonschema import Draft202012Validator


SCRIPT = Path(__file__).resolve().parents[1] / "detect_spec_tool.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROFILE_SCHEMA = json.loads((SCRIPT.parents[1] / "assets" / "spec-tool-profile.schema.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(SCRIPT.parent))
from spec_providers.base import ProviderAdapter, ProviderError  # noqa: E402


def validate_schema(value: dict, schema: dict) -> list[str]:
    return [error.message for error in Draft202012Validator(schema).iter_errors(value)]


def run_repo(repo: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT), "--repo", str(repo), "--json"]
    if env and env.get("TEST_PROVIDER_CLI"):
        command.extend([
            "--provider-cli", env["TEST_PROVIDER_CLI"],
            "--provider-cli-sha256", env["TEST_PROVIDER_CLI_SHA256"],
            "--provider-cli-manifest", env["TEST_PROVIDER_MANIFEST"],
            "--provider-cli-manifest-sha256", env["TEST_PROVIDER_MANIFEST_SHA256"],
        ])
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def error_code(result: subprocess.CompletedProcess[str]) -> str:
    return json.loads(result.stdout)["errors"][0]["code"]


def fake_provider_cli(directory: Path, provider: str, fixture: Path, *, invalid_json: bool = False, version: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if provider == "openspec":
        executable_name = "openspec"
        version = version or "1.2.3"
        status_var = "FAKE_OPENSPEC_STATUS"
        instructions_var = "FAKE_OPENSPEC_INSTRUCTIONS"
        env[status_var] = str(fixture / "cli" / ("invalid.json" if invalid_json else "status.json"))
        env[instructions_var] = str(fixture / "cli" / "instructions.json")
        if invalid_json:
            (fixture / "cli" / "invalid.json").write_text("not-json", encoding="utf-8")
        if os.name == "nt":
            executable = directory / f"{executable_name}.exe"
            source = directory / f"{executable_name}.rs"
            source.write_text(f'''use std::env; use std::fs; fn main() {{ let a: Vec<String> = env::args().collect(); if a.get(1).map(String::as_str)==Some("--version") {{ println!("OpenSpec {version}"); return; }} let path = if a.get(1).map(String::as_str)==Some("status") {{ {json.dumps(env[status_var])} }} else if a.get(1).map(String::as_str)==Some("instructions") {{ {json.dumps(env[instructions_var])} }} else {{ std::process::exit(9) }}; print!("{{}}", fs::read_to_string(path).unwrap()); }}''', encoding="utf-8")
            subprocess.run(["rustc", str(source), "-O", "-o", str(executable)], check=True, capture_output=True)
        else:
            executable = directory / executable_name
            source = directory / f"{executable_name}.rs"
            source.write_text(f'''use std::env; use std::fs; fn main() {{ let a: Vec<String> = env::args().collect(); if a.get(1).map(String::as_str)==Some("--version") {{ println!("OpenSpec {version}"); return; }} let path = if a.get(1).map(String::as_str)==Some("status") {{ {json.dumps(env[status_var])} }} else if a.get(1).map(String::as_str)==Some("instructions") {{ {json.dumps(env[instructions_var])} }} else {{ std::process::exit(9) }}; print!("{{}}", fs::read_to_string(path).unwrap()); }}''', encoding="utf-8")
            subprocess.run(["rustc", str(source), "-O", "-o", str(executable)], check=True, capture_output=True)
    else:
        executable_name = "specify"
        version = version or "0.9.0"
        status_var = "FAKE_SPECKIT_STATUS"
        integration_status_var = "FAKE_SPECKIT_INTEGRATION_STATUS"
        env[status_var] = str(fixture / "cli" / ("invalid.json" if invalid_json else "status.json"))
        env[integration_status_var] = str(fixture / "cli" / ("invalid.json" if invalid_json else "integration-status.json"))
        if invalid_json:
            (fixture / "cli" / "invalid.json").write_text("not-json", encoding="utf-8")
        if os.name == "nt":
            executable = directory / f"{executable_name}.exe"
            source = directory / f"{executable_name}.rs"
            source.write_text(f'''use std::env; use std::fs; fn main() {{ let a: Vec<String> = env::args().collect(); let path = match a.get(1).map(String::as_str) {{ Some("version") => {{ println!("specify {version}"); return; }}, Some("integration") => {json.dumps(env[integration_status_var])}, Some("workflow") => {json.dumps(env[status_var])}, _ => std::process::exit(9) }}; print!("{{}}", fs::read_to_string(path).unwrap()); }}''', encoding="utf-8")
            subprocess.run(["rustc", str(source), "-O", "-o", str(executable)], check=True, capture_output=True)
        else:
            executable = directory / executable_name
            source = directory / f"{executable_name}.rs"
            source.write_text(f'''use std::env; use std::fs; fn main() {{ let a: Vec<String> = env::args().collect(); let path = match a.get(1).map(String::as_str) {{ Some("version") => {{ println!("specify {version}"); return; }}, Some("integration") => {json.dumps(env[integration_status_var])}, Some("workflow") => {json.dumps(env[status_var])}, _ => std::process::exit(9) }}; print!("{{}}", fs::read_to_string(path).unwrap()); }}''', encoding="utf-8")
            subprocess.run(["rustc", str(source), "-O", "-o", str(executable)], check=True, capture_output=True)
    env["PATH"] = str(directory) + os.pathsep + env.get("PATH", "")
    env["TEST_PROVIDER_CLI"] = str(executable.resolve())
    env["TEST_PROVIDER_CLI_SHA256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
    manifest = directory.parent / (directory.name + ".runtime.json")
    files = {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.rglob("*") if path.is_file()}
    manifest.write_text(json.dumps({"schema_version": "1.0", "root": str(directory.resolve()), "files": files}, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    env["TEST_PROVIDER_MANIFEST"] = str(manifest.resolve())
    env["TEST_PROVIDER_MANIFEST_SHA256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return env


class DetectSpecToolTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Job Object regression")
    def test_descendant_holding_output_pipe_cannot_bypass_timeout(self) -> None:
        class Adapter(ProviderAdapter):
            provider = "openspec"
            executable_name = "openspec"
            version_args = ("--version",)

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as manifest_directory, tempfile.TemporaryDirectory() as repo_directory:
            root = Path(directory)
            source = root / "holder.rs"
            executable = root / "holder.exe"
            source.write_text('use std::process::Command; fn main(){ Command::new("cmd.exe").args(["/c","ping -n 31 127.0.0.1 >nul"]).spawn().unwrap(); println!("1.2.3"); }', encoding="utf-8")
            subprocess.run(["rustc", str(source), "-O", "-o", str(executable)], check=True, capture_output=True)
            files = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}
            manifest = Path(manifest_directory) / "runtime.json"
            manifest.write_text(json.dumps({"schema_version": "1.0", "root": str(root), "files": files}, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            adapter = Adapter(Path(repo_directory), executable, files["holder.exe"], manifest, hashlib.sha256(manifest.read_bytes()).hexdigest())
            started = time.monotonic()
            with self.assertRaisesRegex(ProviderError, "descendant processes"):
                adapter.run_text(("--version",))
            self.assertLess(time.monotonic() - started, 12.0)

    def test_help(self) -> None:
        self.assertEqual(subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True).returncode, 0)

    def test_native_openspec_uses_yaml_metadata_and_machine_state(self) -> None:
        fixture = FIXTURES / "native-openspec"
        with tempfile.TemporaryDirectory() as directory:
            result = run_repo(fixture, fake_provider_cli(Path(directory), "openspec", fixture))
        self.assertEqual(result.returncode, 0, result.stderr)
        profile = json.loads(result.stdout)["profile"]
        self.assertEqual((profile["provider"], profile["mode"]), ("openspec", "native"))
        self.assertEqual(profile["configuration"], "openspec/config.yaml")
        self.assertTrue(profile["id_mapping"])
        self.assertNotIn("openspec:change:add-login:tasks", profile["id_mapping"])
        self.assertIn("artifact-state:add-login:tasks", profile["observations"])
        self.assertTrue(all("*" not in item["authority_uri"] for item in profile["id_mapping"].values()))
        self.assertEqual(
            profile["id_mapping"]["openspec:change:add-login:proposal"]["content_canonicalization"],
            "raw-v1",
        )
        self.assertEqual(len(profile["id_mapping"]["openspec:change:add-login:proposal"]["content_hash"]), 64)
        self.assertIn("status:add-login", profile["observations"])
        self.assertIn("instructions:add-login", profile["observations"])
        self.assertEqual(validate_schema(profile, PROFILE_SCHEMA), [])

    def test_openspec_checkbox_tasks_have_stable_individual_identities(self) -> None:
        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as cli_dir:
            repo = Path(repo_dir)
            shutil.copytree(FIXTURES / "native-openspec", repo, dirs_exist_ok=True)
            tasks = repo / "openspec" / "changes" / "add-login" / "tasks.md"
            tasks.write_text("## 1. Delivery\n\n- [ ] 1.1 Add status command\n- [x] 1.2 Add recovery test\n", encoding="utf-8")
            status_path = repo / "cli" / "status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["artifacts"][-1] = {"id": "tasks", "outputPath": "tasks.md", "status": "done"}
            status_path.write_text(json.dumps(status), encoding="utf-8")
            environment = fake_provider_cli(Path(cli_dir), "openspec", repo)
            first = run_repo(repo, environment)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            first_profile = json.loads(first.stdout)["profile"]
            first_task = first_profile["id_mapping"]["openspec:change:add-login:task:1.1"]
            second_task = first_profile["id_mapping"]["openspec:change:add-login:task:1.2"]
            self.assertEqual(first_task["status"], "ready")
            self.assertEqual(second_task["status"], "done")
            self.assertEqual(first_task["content_selector"]["task_id"], "1.1")
            self.assertEqual(first_task["content_canonicalization"], "utf8-nfc-lf-v1")
            self.assertEqual(validate_schema(first_profile, PROFILE_SCHEMA), [])

            tasks.write_text("## 1. Delivery\n\n- [x] 1.1 Add status command\n- [x] 1.2 Add recovery test\n", encoding="utf-8")
            second = run_repo(repo, environment)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            changed = json.loads(second.stdout)["profile"]["id_mapping"]["openspec:change:add-login:task:1.1"]
            self.assertEqual(changed["status"], "done")
            self.assertEqual(changed["content_hash"], first_task["content_hash"])

    def test_native_speckit_reads_all_persisted_run_files(self) -> None:
        fixture = FIXTURES / "native-speckit"
        with tempfile.TemporaryDirectory() as directory:
            result = run_repo(fixture, fake_provider_cli(Path(directory), "spec-kit", fixture))
        self.assertEqual(result.returncode, 0, result.stderr)
        profile = json.loads(result.stdout)["profile"]
        self.assertEqual((profile["provider"], profile["mode"]), ("spec-kit", "native"))
        self.assertTrue(profile["id_mapping"])
        task = profile["id_mapping"]["spec-kit:run:run-001:task"]
        spec = profile["id_mapping"]["spec-kit:run:run-001:spec"]
        self.assertEqual(task["status"], "paused")
        self.assertEqual(task["native_parent_id"], spec["native_id"])
        self.assertEqual(spec["artifact_type"], "spec")
        self.assertEqual(task["authority_uri"], spec["authority_uri"])
        self.assertEqual(
            task["content_canonicalization"],
            "delivery-json-v1",
        )
        self.assertEqual(len(task["content_hash"]), 64)
        self.assertIn("state:run-001", profile["observations"])
        self.assertIn("inputs:run-001", profile["observations"])
        self.assertIn("log:run-001", profile["observations"])
        self.assertIn("cli-integration-status", profile["observations"])
        self.assertEqual(validate_schema(profile, PROFILE_SCHEMA), [])

    def test_empty_native_state_is_a_valid_observation_for_deprecation(self) -> None:
        cases = (
            ("openspec", "native-openspec", Path("openspec/changes/add-login")),
            ("spec-kit", "native-speckit", Path(".specify/workflows/runs/run-001")),
        )
        for provider, fixture_name, active_path in cases:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as cli_dir:
                repo = Path(repo_dir)
                shutil.copytree(FIXTURES / fixture_name, repo, dirs_exist_ok=True)
                shutil.rmtree(repo / active_path)
                result = run_repo(repo, fake_provider_cli(Path(cli_dir), provider, repo))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                profile = json.loads(result.stdout)["profile"]
                self.assertEqual(profile["id_mapping"], {})
                self.assertEqual(validate_schema(profile, PROFILE_SCHEMA), [])

    def test_no_provider_is_blocked_without_fallback(self) -> None:
        result = run_repo(FIXTURES / "no-provider")
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertIsNone(payload["profile"])
        self.assertEqual(error_code(result), "PROVIDER_NOT_ADOPTED")

    def test_obsolete_config_json_is_not_adoption_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "openspec").mkdir()
            (repo / "openspec" / "config.json").write_text("{}", encoding="utf-8")
            result = run_repo(repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(error_code(result), "PROVIDER_NOT_ADOPTED")

    def test_multiple_adopted_providers_are_blocked(self) -> None:
        result = run_repo(FIXTURES / "conflict")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(error_code(result), "PROVIDER_CONFLICT")
        self.assertEqual(json.loads(result.stdout)["candidates"], ["openspec", "spec-kit"])

    def test_missing_cli_is_environment_failure_for_each_provider(self) -> None:
        empty_path = os.environ.copy()
        empty_path["PATH"] = ""
        for fixture in ("native-openspec", "native-speckit"):
            with self.subTest(fixture=fixture):
                result = run_repo(FIXTURES / fixture, empty_path)
                self.assertEqual(result.returncode, 3)
                self.assertEqual(error_code(result), "PROVIDER_CLI_UNPINNED")
                self.assertIsNone(json.loads(result.stdout)["profile"])

    def test_invalid_cli_json_is_blocked_for_each_provider(self) -> None:
        for provider, fixture_name in (("openspec", "native-openspec"), ("spec-kit", "native-speckit")):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as cli_dir:
                fixture = Path(temp) / "repo"
                shutil.copytree(FIXTURES / fixture_name, fixture)
                result = run_repo(fixture, fake_provider_cli(Path(cli_dir), provider, fixture, invalid_json=True))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(error_code(result), "PROVIDER_CLI_OUTPUT_INVALID")

    def test_incomplete_openspec_layout_is_blocked(self) -> None:
        fixture = FIXTURES / "incomplete-openspec"
        with tempfile.TemporaryDirectory() as directory:
            result = run_repo(fixture, fake_provider_cli(Path(directory), "openspec", fixture))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(error_code(result), "PROVIDER_LAYOUT_INVALID")

    def test_openspec_change_requires_native_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as cli_dir:
            repo = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "native-openspec", repo)
            (repo / "openspec/changes/add-login/.openspec.yaml").unlink()
            result = run_repo(repo, fake_provider_cli(Path(cli_dir), "openspec", repo))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(error_code(result), "PROVIDER_LAYOUT_INVALID")

    def test_openspec_status_identity_mismatch_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as cli_dir:
            repo = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "native-openspec", repo)
            status_path = repo / "cli/status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["changeName"] = "another-change"
            status_path.write_text(json.dumps(status), encoding="utf-8")
            result = run_repo(repo, fake_provider_cli(Path(cli_dir), "openspec", repo))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(error_code(result), "PROVIDER_CLI_OUTPUT_INVALID")

    def test_openspec_instructions_require_official_state_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as cli_dir:
            repo = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "native-openspec", repo)
            instructions_path = repo / "cli/instructions.json"
            instructions = json.loads(instructions_path.read_text(encoding="utf-8"))
            instructions.pop("state")
            instructions_path.write_text(json.dumps(instructions), encoding="utf-8")
            result = run_repo(repo, fake_provider_cli(Path(cli_dir), "openspec", repo))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(error_code(result), "PROVIDER_CLI_OUTPUT_INVALID")

    def test_speckit_missing_run_component_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as cli_dir:
            repo = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "native-speckit", repo)
            (repo / ".specify/workflows/runs/run-001/log.jsonl").unlink()
            result = run_repo(repo, fake_provider_cli(Path(cli_dir), "spec-kit", repo))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(error_code(result), "PROVIDER_LAYOUT_INVALID")

    def test_speckit_cli_and_disk_state_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as cli_dir:
            repo = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "native-speckit", repo)
            status_path = repo / "cli/status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["status"] = "completed"
            status_path.write_text(json.dumps(status), encoding="utf-8")
            result = run_repo(repo, fake_provider_cli(Path(cli_dir), "spec-kit", repo))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(error_code(result), "PROVIDER_CLI_OUTPUT_INVALID")

    def test_speckit_integration_status_and_disk_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as cli_dir:
            repo = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "native-speckit", repo)
            status_path = repo / "cli/integration-status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["default_integration"] = "claude"
            status_path.write_text(json.dumps(status), encoding="utf-8")
            result = run_repo(repo, fake_provider_cli(Path(cli_dir), "spec-kit", repo))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(error_code(result), "PROVIDER_CLI_OUTPUT_INVALID")

    def test_invalid_repository_is_input_error(self) -> None:
        result = run_repo(FIXTURES / "missing")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(error_code(result), "REPOSITORY_INVALID")

    def test_duplicate_provider_keys_are_rejected_for_json_and_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as cli_dir:
            repo = Path(temp) / "speckit"
            shutil.copytree(FIXTURES / "native-speckit", repo)
            (repo / ".specify/integration.json").write_text(
                '{"default_integration":"codex","default_integration":"claude",'
                '"installed_integrations":["codex"],"integration_settings":{},"integration_state_schema":"1"}',
                encoding="utf-8",
            )
            result = run_repo(repo, fake_provider_cli(Path(cli_dir), "spec-kit", repo))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(error_code(result), "PROVIDER_DATA_INVALID")
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as cli_dir:
            repo = Path(temp) / "openspec"
            shutil.copytree(FIXTURES / "native-openspec", repo)
            (repo / "openspec/config.yaml").write_text("schema: spec-driven\nschema: duplicate\n", encoding="utf-8")
            result = run_repo(repo, fake_provider_cli(Path(cli_dir), "openspec", repo))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(error_code(result), "PROVIDER_DATA_INVALID")


if __name__ == "__main__":
    unittest.main()

"""Behavioral installer checks using explicit temporary targets only."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import tomlkit

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("team_setup", ROOT / "scripts/setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="team installer ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / "Codex home with spaces"
        self.models = ROOT / "team.toml"

    def action(self, action="install", models=None):
        with contextlib.redirect_stdout(io.StringIO()):
            setup.run(action, self.home, models or self.models)

    def put(self, relative, content):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def snapshot(self):
        return {p.relative_to(self.home).as_posix(): p.read_bytes() for p in self.home.rglob("*") if p.is_file()} if self.home.exists() else {}

    def config(self):
        return tomlkit.parse((self.home / "config.toml").read_text()).unwrap()

    def conflict(self, action="install"):
        before = self.snapshot()
        with self.assertRaises(setup.InstallError):
            self.action(action)
        self.assertEqual(before, self.snapshot())

    def custom(self, mutate):
        document = tomlkit.parse(self.models.read_text())
        mutate(document)
        path = self.base / "custom models.toml"
        path.write_text(tomlkit.dumps(document))
        return path

    def test_fresh_lifecycle_read_only_plan_and_idempotency(self):
        self.action("plan")
        self.assertFalse(self.home.exists())
        self.action()
        self.assertEqual(set(self.snapshot()), {*setup.FILES, "config.toml", "AGENTS.md", setup.STATE})
        self.assertEqual(self.config()["agents"]["max_concurrent_threads_per_session"], 3)
        self.assertEqual(self.config()["agents"]["default_subagent_reasoning_effort"], "medium")
        if os.name == "posix":
            self.assertEqual((self.home / ".dev-team-state").stat().st_mode & 0o777, 0o700)
            self.assertEqual((self.home / setup.STATE).stat().st_mode & 0o777, 0o600)
        before = self.snapshot()
        stamps = {str(p): p.stat().st_mtime_ns for p in self.home.rglob("*") if p.is_file()}
        self.action()
        self.action("plan")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(stamps, {str(p): p.stat().st_mtime_ns for p in self.home.rglob("*") if p.is_file()})
        self.action("check")
        self.action("uninstall")
        self.assertEqual(self.snapshot(), {})

    def test_existing_comments_settings_legacy_limit_and_instructions_survive(self):
        config = '# Personal preferences\nmodel = "before" # chosen manually\nmodel_reasoning_effort = "low"\npermission_mode = "ask"\n\n[agents] # personal preferences\nenabled = false\nmax_threads = 8 # legacy limit\nextra = "keep"\n\n[projects."/work"]\ntrust_level = "trusted"\n'
        instructions = "# My instructions\n\nPreserve this line.\n"
        self.put("config.toml", config)
        self.put("AGENTS.md", instructions)
        self.action()
        installed = (self.home / "config.toml").read_text()
        for content in ("# Personal preferences", "# personal preferences", 'permission_mode = "ask"'):
            self.assertIn(content, installed)
        self.assertNotIn("max_threads =", installed)
        self.assertTrue((self.home / "AGENTS.md").read_text().startswith(instructions))
        self.action("uninstall")
        restored = (self.home / "config.toml").read_text()
        self.assertEqual(tomlkit.parse(restored).unwrap(), tomlkit.parse(config).unwrap())
        self.assertIn('# chosen manually', restored)
        self.assertIn('max_threads = 8 # legacy limit', restored)
        self.assertEqual((self.home / "AGENTS.md").read_text(), instructions)

    def test_later_unrelated_changes_survive_update_and_uninstall(self):
        self.put("config.toml", 'model = "original"\n[agents]\nextra = 1\n')
        self.put("AGENTS.md", "My original instructions")
        self.action()
        document = tomlkit.parse((self.home / "config.toml").read_text())
        document["agents"]["extra"] = 99
        document["new_setting"] = "later"
        self.put("config.toml", tomlkit.dumps(document))
        with (self.home / "AGENTS.md").open("a") as stream:
            stream.write("\n\nLater instruction.\n")
        self.action()
        self.action(models=self.custom(lambda d: d["orchestrator"].update(model="custom-model")))
        self.action("uninstall")
        self.assertEqual(self.config()["model"], "original")
        self.assertEqual(self.config()["agents"]["extra"], 99)
        self.assertEqual(self.config()["new_setting"], "later")
        self.assertEqual((self.home / "AGENTS.md").read_text(), "My original instructions\n\nLater instruction.\n")

    def test_custom_models_and_generated_table(self):
        def customize(d):
            d["orchestrator"]["model"] = "alternate-orchestrator"
            d["roles"]["dev_worker"]["model"] = "alternate-worker"
            d["roles"]["dev_worker"]["model_reasoning_effort"] = "low"
            d["delegation"]["max_concurrent_threads_per_session"] = 7
        self.action(models=self.custom(customize))
        self.assertEqual(self.config()["model"], "alternate-orchestrator")
        self.assertEqual(self.config()["agents"]["default_subagent_model"], "alternate-worker")
        self.assertEqual(self.config()["agents"]["default_subagent_reasoning_effort"], "low")
        worker = tomlkit.parse((self.home / "agents/dev_worker.toml").read_text())
        self.assertEqual(worker["model"], "alternate-worker")
        self.assertEqual(worker["model_reasoning_effort"], "low")
        orchestration = (self.home / "dev-team/orchestration.md").read_text()
        self.assertIn("alternate-worker", orchestration)
        self.assertIn("alternate-orchestrator", orchestration)
        self.assertNotIn("{{", orchestration)
        self.assertIn(str(self.home), (self.home / "AGENTS.md").read_text())

    def test_unmanaged_file_and_marker_collisions_fail_before_writes(self):
        for relative in setup.FILES:
            with self.subTest(relative=relative):
                self.put(relative, "Do not replace")
                self.conflict()
                (self.home / relative).unlink()
        self.put("AGENTS.md", f"Before\n{setup.BEGIN}\nold\n{setup.END}\n")
        self.conflict()

    def test_all_managed_files_detect_local_edits_and_missing_files(self):
        self.action()
        for relative in setup.FILES:
            with self.subTest(relative=relative):
                original = (self.home / relative).read_text()
                self.put(relative, original + "\nLocal edit\n")
                for action in ("plan", "install", "check", "uninstall"):
                    self.conflict(action)
                self.put(relative, original)
        (self.home / setup.FILES[0]).unlink()
        self.conflict("check")

    def test_managed_config_and_block_edits_are_conflicts(self):
        self.action()
        original = (self.home / "config.toml").read_text()
        for key, replacement in [("model", "another-model"), ("agents.enabled", False),
                                 ("agents.max_concurrent_threads_per_session", 15),
                                 ("agents.default_subagent_reasoning_effort", "low"), ("agents.max_threads", 3)]:
            with self.subTest(key=key):
                document = tomlkit.parse(original)
                setup.assign(document, key, replacement)
                self.put("config.toml", tomlkit.dumps(document))
                self.conflict()
                self.conflict("uninstall")
        self.put("config.toml", original)
        self.put("AGENTS.md", (self.home / "AGENTS.md").read_text().replace("standing request", "local request"))
        self.conflict("check")

    def test_malformed_toml_and_scalar_agents_rejected(self):
        for content in ('model = [', 'agents = "scalar"\n', '[[agents]]\nx = 1\n'):
            with self.subTest(content=content):
                self.put("config.toml", content)
                self.conflict()

    def test_invalid_malicious_model_settings_rejected_without_writes(self):
        mutations = [lambda d: d["orchestrator"].update(model="$(touch /tmp/bad)"),
                     lambda d: d["orchestrator"].update(model="injected\ntext"),
                     lambda d: d["orchestrator"].update(model_reasoning_effort="invalid"),
                     lambda d: d["delegation"].update(max_concurrent_threads_per_session=True),
                     lambda d: d["delegation"].update(max_concurrent_threads_per_session=0),
                     lambda d: d["roles"].pop("dev_worker"), lambda d: d.update(unexpected="field")]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                with self.assertRaises(setup.InstallError):
                    self.action(models=self.custom(mutate))
                self.assertFalse(self.home.exists())
        malformed = self.base / "bad.toml"
        malformed.write_text("[broken")
        with self.assertRaises(setup.InstallError):
            self.action(models=malformed)
        self.assertFalse(self.home.exists())

    def test_invalid_state_paths_format_and_baseline_are_rejected(self):
        self.action()
        original = (self.home / setup.STATE).read_text()
        mutations = [lambda d: d["files"].update({"../../escape": "bad"}), lambda d: d.update(version=2),
                     lambda d: d.update(separator="arbitrary"),
                     lambda d: d["baseline"].update(model='value = "x"\nother = "bad"'),
                     lambda d: d["values"].update({"agents.enabled": "true"}), lambda d: d.update(block="not a block")]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                state = json.loads(original)
                mutate(state)
                self.put(setup.STATE, json.dumps(state))
                self.conflict("uninstall")
        self.put(setup.STATE, "{broken")
        self.conflict()

    def test_symlink_destinations_and_parents_rejected(self):
        external = self.base / "outside"
        external.mkdir()
        original = external / "config.toml"
        original.write_text('model = "external"\n')
        self.home.mkdir()
        for relative, destination in [("config.toml", original), ("agents", external), (".dev-team-state", external)]:
            with self.subTest(relative=relative):
                link = self.home / relative
                link.symlink_to(destination)
                with self.assertRaises(setup.InstallError):
                    self.action()
                self.assertEqual(original.read_text(), 'model = "external"\n')
                link.unlink()
        shutil.rmtree(self.home)
        self.home.symlink_to(external)
        with self.assertRaises(setup.InstallError):
            self.action()

    def test_uninstall_keeps_later_unrelated_files_and_config_table(self):
        self.action()
        self.put("agents/personal.toml", 'name = "personal"\n')
        self.put("dev-team/personal.md", "Keep this document")
        document = tomlkit.parse((self.home / "config.toml").read_text())
        document["agents"]["personal"] = 123
        self.put("config.toml", tomlkit.dumps(document))
        self.action("uninstall")
        self.assertEqual(set(self.snapshot()), {"agents/personal.toml", "dev-team/personal.md", "config.toml"})
        self.assertEqual(self.config(), {"agents": {"personal": 123}})

    def test_rollback_restores_original_files_on_caught_failure(self):
        self.put("config.toml", '# Keep\nmodel = "original"\n')
        self.put("AGENTS.md", "Original instructions")
        before = self.snapshot()
        config_mode = (self.home / "config.toml").stat().st_mode & 0o777
        real_replace = os.replace
        failed = False
        def replace(source, target):
            nonlocal failed
            if Path(target).name == "AGENTS.md" and not failed:
                failed = True
                raise OSError("simulated commit failure")
            return real_replace(source, target)
        with mock.patch.object(setup.os, "replace", side_effect=replace):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.action()
        self.assertTrue(failed)
        self.assertEqual(before, self.snapshot())
        if os.name == "posix":
            self.assertEqual((self.home / "config.toml").stat().st_mode & 0o777, config_mode)
        self.assertFalse((self.home / ".dev-team-state").exists())

    def test_copied_source_and_target_paths_with_spaces_then_source_moves(self):
        source = self.base / "source checkout with spaces"
        shutil.copytree(ROOT, source)
        command = [sys.executable, str(source / "scripts/setup.py"), "--codex-home", str(self.home)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.home.exists())
        for action in ("install", "install", "check"):
            result = subprocess.run(command + [action], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        relocated = self.base / "moved checkout"
        source.rename(relocated)
        for relative in (*setup.FILES, "AGENTS.md"):
            self.assertNotIn(str(source), (self.home / relative).read_text())
        for action in ("check", "uninstall"):
            result = subprocess.run([sys.executable, str(relocated / "scripts/setup.py"), action,
                                     "--codex-home", str(self.home)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_existing_configuration_lifecycle(self):
        original_config = '# Personal settings\nmodel = "old-model"\n[agents]\nmax_threads = 9\nunrelated = true\n'
        original_instructions = "Existing guidance\n"
        self.put("config.toml", original_config)
        self.put("AGENTS.md", original_instructions)
        before = self.snapshot()
        for action in ("plan", "install", "install", "check", "uninstall"):
            result = subprocess.run([sys.executable, str(ROOT / "scripts/setup.py"), action,
                                     "--codex-home", str(self.home)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if action == "plan":
                self.assertEqual(before, self.snapshot())
        self.assertEqual(self.config(), tomlkit.parse(original_config).unwrap())
        self.assertEqual((self.home / "AGENTS.md").read_text(), original_instructions)

    def test_empty_agent_table_preserves_user_body_and_header_comments(self):
        for comment in ("body", "header"):
            with self.subTest(comment=comment):
                self.action()
                text = (self.home / "config.toml").read_text()
                if comment == "body":
                    text += "# Keep my agent guidance\n"
                else:
                    text = text.replace("[agents]", "[agents] # Keep my agent guidance")
                self.put("config.toml", text)
                self.action("uninstall")
                self.assertEqual(self.config(), {"agents": {}})
                self.assertIn("# Keep my agent guidance", (self.home / "config.toml").read_text())
                shutil.rmtree(self.home)

    def test_concurrent_input_changes_abort_before_install_or_uninstall_writes(self):
        for action in ("install", "uninstall"):
            for relative in (*setup.FILES, "config.toml", "AGENTS.md", setup.STATE):
                with self.subTest(action=action, relative=relative):
                    self.action()
                    before = self.snapshot()
                    updated = before[relative] + b"\nConcurrent save\n"
                    real_apply = setup.apply
                    def save_then_apply(home, changes, expected):
                        (home / relative).write_bytes(updated)
                        return real_apply(home, changes, expected)
                    with mock.patch.object(setup, "apply", side_effect=save_then_apply):
                        with self.assertRaisesRegex(setup.InstallError, "Target changed during preparation"):
                            self.action(action)
                    before[relative] = updated
                    self.assertEqual(self.snapshot(), before)
                    shutil.rmtree(self.home)

    def test_concurrent_unrelated_save_while_preparing_output_is_preserved(self):
        for relative in ("config.toml", "AGENTS.md"):
            with self.subTest(relative=relative):
                self.put("config.toml", 'unrelated = "original"\n')
                self.put("AGENTS.md", "Original guidance\n")
                before = self.snapshot()
                updated = before[relative] + b"# Concurrent unrelated save\n"
                real_desired = setup.desired
                def prepare_then_save(home, models):
                    output = real_desired(home, models)
                    (home / relative).write_bytes(updated)
                    return output
                with mock.patch.object(setup, "desired", side_effect=prepare_then_save):
                    with self.assertRaisesRegex(setup.InstallError, "Target changed during preparation"):
                        self.action()
                before[relative] = updated
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.home / ".dev-team-state").exists())
                shutil.rmtree(self.home)

    def test_concurrent_change_during_staging_is_detected_and_staging_cleaned(self):
        self.put("config.toml", 'unrelated = "original"\n')
        before = self.snapshot()
        updated = before["config.toml"] + b"# Concurrent save while staging\n"
        real_mkstemp = tempfile.mkstemp
        def stage_and_save(*args, **kwargs):
            result = real_mkstemp(*args, **kwargs)
            (self.home / "config.toml").write_bytes(updated)
            return result
        with mock.patch.object(setup.tempfile, "mkstemp", side_effect=stage_and_save):
            with self.assertRaisesRegex(setup.InstallError, "Target changed during preparation"):
                self.action()
        before["config.toml"] = updated
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.home / ".dev-team-state").exists())

    def test_concurrent_save_during_commit_rolls_back_other_writes(self):
        self.put("config.toml", 'unrelated = "original"\n')
        before = self.snapshot()
        updated = before["config.toml"] + b"# Concurrent save during commit\n"
        real_replace = os.replace
        saved = False
        def replace_and_save(source, target):
            nonlocal saved
            result = real_replace(source, target)
            if not saved:
                saved = True
                (self.home / "config.toml").write_bytes(updated)
            return result
        with mock.patch.object(setup.os, "replace", side_effect=replace_and_save):
            with self.assertRaisesRegex(setup.InstallError, "Target changed during preparation"):
                self.action()
        before["config.toml"] = updated
        self.assertEqual(self.snapshot(), before)

    def test_rollback_never_overwrites_a_newer_save_in_committed_file(self):
        real_replace = os.replace
        changed_path = "dev-team/software-development.md"
        updated = b"Concurrent document save\n"
        def fail_after_save(source, target):
            if Path(target).name == "AGENTS.md":
                (self.home / changed_path).write_bytes(updated)
                raise OSError("simulated commit failure after another save")
            return real_replace(source, target)
        with mock.patch.object(setup.os, "replace", side_effect=fail_after_save):
            with self.assertRaisesRegex(setup.InstallError, "manual recovery may be needed"):
                self.action()
        self.assertEqual(self.snapshot(), {changed_path: updated})

    def test_check_and_uninstall_need_no_source_assets_or_model_settings(self):
        self.action()
        with mock.patch.object(setup, "ROOT", self.base / "absent source"):
            self.action("check", models=self.base / "absent models.toml")
            self.action("uninstall", models=self.base / "absent models.toml")


if __name__ == "__main__":
    unittest.main()

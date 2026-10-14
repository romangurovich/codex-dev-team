#!/usr/bin/env python3
"""Install a self-contained Codex development team without replacing user settings."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import tomlkit

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("dev_explorer", "dev_worker", "dev_verifier", "dev_reviewer", "dev_deep_worker")
DOCS = ("software-development.md", "orchestration.md")
FILES = tuple(f"agents/{role}.toml" for role in ROLES) + tuple(f"dev-team/{doc}" for doc in DOCS)
BEGIN = "<!-- codex-dev-team:begin -->"
END = "<!-- codex-dev-team:end -->"
STATE = ".dev-team-state/state.json"
KEYS = ("model", "model_reasoning_effort", "agents.enabled", "agents.max_concurrent_threads_per_session",
        "agents.default_subagent_model", "agents.default_subagent_reasoning_effort", "agents.max_threads")
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}


class InstallError(Exception):
    """An invalid input or a conflict prevented installation."""


def parse_toml(text: str, label: str):
    try:
        return tomlkit.parse(text)
    except Exception as exc:
        raise InstallError(f"Invalid TOML in {label}: {exc}") from exc


def read(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise InstallError(f"Expected a regular file: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InstallError(f"Cannot read {path}: {exc}") from exc


def safe_path(home: Path, relative: str) -> Path:
    path = home / relative
    if home.is_symlink():
        raise InstallError(f"Symlink destination is unsupported: {home}")
    if home.exists() and not home.is_dir():
        raise InstallError(f"Expected a directory: {home}")
    current = home
    for component in Path(relative).parts:
        current = current / component
        if current.is_symlink():
            raise InstallError(f"Symlink destination is unsupported: {current}")
        if current != path and current.exists() and not current.is_dir():
            raise InstallError(f"Expected a directory: {current}")
    return path


def settings(path: Path):
    document = parse_toml(read(path) or "", str(path)).unwrap()
    if set(document) != {"orchestrator", "delegation", "roles"}:
        raise InstallError("Model settings must contain exactly orchestrator, delegation, and roles")
    if not isinstance(document["roles"], dict) or set(document["roles"]) != set(ROLES):
        raise InstallError("Model settings must define every supported role exactly once")
    for name, entry in [("orchestrator", document["orchestrator"]), *document["roles"].items()]:
        if not isinstance(entry, dict) or set(entry) != {"model", "model_reasoning_effort"}:
            raise InstallError(f"Invalid model settings for {name}")
        model = entry["model"]
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model):
            raise InstallError(f"Invalid model name for {name}")
        if not isinstance(entry["model_reasoning_effort"], str) or entry["model_reasoning_effort"] not in EFFORTS:
            raise InstallError(f"Invalid reasoning effort for {name}")
    delegation = document["delegation"]
    if not isinstance(delegation, dict) or set(delegation) != {"max_concurrent_threads_per_session"}:
        raise InstallError("Invalid delegation settings")
    cap = delegation["max_concurrent_threads_per_session"]
    if type(cap) is not int or cap < 1:
        raise InstallError("max_concurrent_threads_per_session must be a positive integer")
    return document


def desired(home: Path, models: Path):
    config = settings(models)
    cap = config["delegation"]["max_concurrent_threads_per_session"]
    table = "| Role | Model | Reasoning effort |\n| --- | --- | --- |\n"
    table += "\n".join(f"| {name} | {entry['model']} | {entry['model_reasoning_effort']} |"
                       for name, entry in [("orchestrator", config["orchestrator"]), *config["roles"].items()])

    def render(path):
        content = read(path)
        if content is None:
            raise InstallError(f"Missing source asset: {path}")
        for token, value in {"CODEX_HOME": str(home), "MODEL_TABLE": table, "MAX_SUBAGENTS": str(cap)}.items():
            content = content.replace("{{" + token + "}}", value)
        if "{{" in content or BEGIN in content or END in content:
            raise InstallError(f"Unexpected marker or placeholder in {path}")
        return content

    files = {f"dev-team/{name}": render(ROOT / "assets" / name) for name in DOCS}
    for role in ROLES:
        template = parse_toml(read(ROOT / "agents" / f"{role}.toml") or "", role)
        if set(template) != {"name", "description", "developer_instructions"} or template["name"] != role:
            raise InstallError(f"Invalid role template: {role}")
        if any(not isinstance(template[key], str) or not template[key].strip() for key in template):
            raise InstallError(f"Role template fields must be nonempty strings: {role}")
        # Render instruction placeholders before TOML serialization, so paths are escaped correctly.
        instructions = str(template["developer_instructions"])
        for token, value in {"CODEX_HOME": str(home), "MODEL_TABLE": table, "MAX_SUBAGENTS": str(cap)}.items():
            instructions = instructions.replace("{{" + token + "}}", value)
        if "{{" in instructions:
            raise InstallError(f"Unexpected role placeholder: {role}")
        template["developer_instructions"] = instructions
        for key, value in config["roles"][role].items():
            template[key] = value
        files[f"agents/{role}.toml"] = tomlkit.dumps(template)
    block = BEGIN + "\n" + render(ROOT / "assets" / "AGENTS.block.md").rstrip() + "\n" + END
    values = {"model": config["orchestrator"]["model"],
              "model_reasoning_effort": config["orchestrator"]["model_reasoning_effort"],
              "agents.enabled": True, "agents.max_concurrent_threads_per_session": cap,
              "agents.default_subagent_model": config["roles"]["dev_worker"]["model"],
              "agents.default_subagent_reasoning_effort": config["roles"]["dev_worker"]["model_reasoning_effort"],
              "agents.max_threads": None}
    return files, block, values


def config_item(document, key):
    parts = key.split(".")
    container = document
    if len(parts) == 2:
        container = document.get("agents", {})
        if not hasattr(container, "items"):
            raise InstallError("config.toml agents must be a table")
    return container.get(parts[-1])


def fragment(item):
    if item is None:
        return None
    document = tomlkit.document()
    document["value"] = item
    return tomlkit.dumps(document)


def assign(document, key, value, original=False):
    parts = key.split(".")
    container = document
    if len(parts) == 2:
        if "agents" not in document:
            if value is None:
                return
            document["agents"] = tomlkit.table()
        container = document["agents"]
    if value is None:
        container.pop(parts[-1], None)
    else:
        container[parts[-1]] = parse_toml(value, "saved config value")["value"] if original else value


def split_block(text):
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise InstallError("AGENTS.md has duplicate or unmatched managed markers")
    if BEGIN not in text:
        return None
    start, end = text.index(BEGIN), text.index(END) + len(END)
    if start >= text.index(END):
        raise InstallError("AGENTS.md markers are out of order")
    return start, end, text[start:end]


def validate_values(values):
    if not isinstance(values, dict) or set(values) != set(KEYS):
        raise InstallError("Invalid managed config state")
    for key in ("model", "agents.default_subagent_model"):
        if not isinstance(values[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", values[key]):
            raise InstallError("Invalid saved model")
    for key in ("model_reasoning_effort", "agents.default_subagent_reasoning_effort"):
        if not isinstance(values[key], str) or values[key] not in EFFORTS:
            raise InstallError("Invalid saved reasoning effort")
    if values["agents.enabled"] is not True or values["agents.max_threads"] is not None:
        raise InstallError("Invalid saved agent settings")
    cap = values["agents.max_concurrent_threads_per_session"]
    if type(cap) is not int or cap < 1:
        raise InstallError("Invalid saved concurrency")


def load_state(home):
    raw = read(safe_path(home, STATE))
    if raw is None:
        directory = home / ".dev-team-state"
        if directory.exists():
            raise InstallError("State directory exists without installation state")
        return None
    try:
        state = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise InstallError(f"Invalid installation state: {exc}") from exc
    required = {"version", "files", "block", "separator", "values", "baseline", "agents_table_existed", "config_existed", "instructions_existed"}
    if not isinstance(state, dict) or set(state) != required or type(state["version"]) is not int or state["version"] != 1:
        raise InstallError("Unsupported installation state format")
    if not isinstance(state["files"], dict) or set(state["files"]) != set(FILES):
        raise InstallError("Invalid installation state paths")
    if any(not isinstance(value, str) for value in state["files"].values()):
        raise InstallError("Invalid saved file content")
    if not isinstance(state["block"], str) or split_block(state["block"]) != (0, len(state["block"]), state["block"]):
        raise InstallError("Invalid saved instructions block")
    if state["separator"] not in ("", "\n", "\n\n"):
        raise InstallError("Invalid saved instructions separator")
    if any(type(state[key]) is not bool for key in ("agents_table_existed", "config_existed", "instructions_existed")):
        raise InstallError("Invalid saved file baseline")
    validate_values(state["values"])
    if not isinstance(state["baseline"], dict) or set(state["baseline"]) != set(KEYS):
        raise InstallError("Invalid saved config baseline")
    for value in state["baseline"].values():
        if value is not None and (not isinstance(value, str) or set(parse_toml(value, "state baseline")) != {"value"}):
            raise InstallError("Invalid saved config fragment")
    for role in ROLES:
        parse_toml(state["files"][f"agents/{role}.toml"], "saved role")
    return state


def verify(home, state, document, instructions):
    for relative, expected in state["files"].items():
        if read(safe_path(home, relative)) != expected:
            raise InstallError(f"Managed file changed or missing: {relative}")
    block = split_block(instructions)
    if block is None or block[2] != state["block"]:
        raise InstallError("Managed AGENTS.md block changed or missing")
    for key, expected in state["values"].items():
        actual = config_item(document, key)
        actual = actual.unwrap() if hasattr(actual, "unwrap") else actual
        if type(actual) is not type(expected) or actual != expected:
            raise InstallError(f"Managed config value changed: {key}")


def input_bytes(home, relative):
    path = safe_path(home, relative)
    if not path.exists():
        return None
    if not path.is_file():
        raise InstallError(f"Expected a regular file: {path}")
    return path.read_bytes()


def assert_inputs(home, expected):
    for relative, original in expected.items():
        if input_bytes(home, relative) != original:
            raise InstallError(f"Target changed during preparation: {relative}; retry with the updated files")


def apply(home, changes, expected):
    """Compare original inputs, stage replacements, and roll back caught failures.

    Individual compare/replace operations cannot exclude a simultaneous writer.
    Recheck after staging and before each mutation to keep that window small.
    """
    assert_inputs(home, expected)
    originals, modes, staged, created_dirs = {}, {}, {}, []
    try:
        for relative, content in changes.items():
            path = safe_path(home, relative)
            originals[path] = expected[relative]
            modes[path] = path.stat().st_mode & 0o777 if path.exists() else None
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir(mode=0o700 if directory.name == ".dev-team-state" else 0o755)
                created_dirs.append(directory)
            if content is not None:
                descriptor, temporary = tempfile.mkstemp(prefix=".dev-team-", dir=path.parent)
                staged[path] = Path(temporary)
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                mode = modes[path] if modes[path] is not None else (0o600 if relative == STATE else 0o644)
                os.chmod(temporary, mode)
        assert_inputs(home, expected)
        committed = []
        pending = dict(expected)
        try:
            for relative, content in changes.items():
                assert_inputs(home, pending)
                path = safe_path(home, relative)
                if content is None:
                    if path.exists():
                        path.unlink()
                else:
                    os.replace(staged[path], path)
                committed.append((relative, path, content))
                pending.pop(relative)
            assert_inputs(home, pending)
        except Exception as exc:
            concurrent = []
            for relative, path, content in reversed(committed):
                installed = content.encode("utf-8") if content is not None else None
                if input_bytes(home, relative) != installed:
                    concurrent.append(relative)
                    continue  # Preserve a later save even if it prevents a full rollback.
                original = originals[path]
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    descriptor, temporary = tempfile.mkstemp(prefix=".dev-team-rollback-", dir=path.parent)
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(original)
                    os.chmod(temporary, modes[path])
                    os.replace(temporary, path)
            if concurrent:
                raise InstallError("Rollback preserved concurrently edited files; manual recovery may be needed: "
                                   + ", ".join(concurrent)) from exc
            raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass


def run(action, home, models):
    home = Path(os.path.abspath(home.expanduser()))
    expected = {relative: input_bytes(home, relative)
                for relative in (*FILES, "config.toml", "AGENTS.md", STATE)}
    state = load_state(home)
    config_text = read(home / "config.toml")
    document = parse_toml(config_text or "", "target config.toml")
    config_item(document, "agents.enabled")  # Reject a scalar agents setting even on first install.
    instructions_text = read(home / "AGENTS.md")
    instructions = instructions_text or ""
    current_block = split_block(instructions)
    if state:
        verify(home, state, document, instructions)
    elif action in ("check", "uninstall"):
        raise InstallError("No installation state found")
    if action == "check":
        print("Installation is intact.")
        return
    if action == "uninstall":
        for key, value in state["baseline"].items():
            assign(document, key, value, original=True)
        agents = document.get("agents")
        if not state["agents_table_existed"] and agents is not None and not agents:
            if not agents.as_string().strip() and not agents.trivia.comment.strip():
                document.pop("agents", None)
        start, end, _ = current_block
        separator = state["separator"]
        if separator and instructions[:start].endswith(separator):
            start -= len(separator)
        instructions = instructions[:start] + instructions[end:]
        config_result = tomlkit.dumps(document)
        changes = {relative: None for relative in FILES}
        changes["config.toml"] = config_result if state["config_existed"] or config_result.strip() else None
        changes["AGENTS.md"] = instructions if state["instructions_existed"] or instructions else None
        changes[STATE] = None
        apply(home, changes, expected)
        for directory in (home / ".dev-team-state", home / "dev-team", home / "agents"):
            try:
                directory.rmdir()
            except OSError:
                pass
        print("Uninstalled; original managed settings restored.")
        return
    files, block, values = desired(home, models)
    if not state:
        for relative in FILES:
            if (home / relative).exists():
                raise InstallError(f"Unmanaged destination already exists: {relative}")
        if current_block:
            raise InstallError("Unmanaged instructions block already exists")
        separator = "" if not instructions else ("\n" if instructions.endswith("\n") else "\n\n")
        state = {"version": 1, "baseline": {key: fragment(config_item(document, key)) for key in KEYS},
                 "agents_table_existed": "agents" in document, "config_existed": config_text is not None,
                 "instructions_existed": instructions_text is not None, "separator": separator}
        instructions += separator + block
    else:
        start, end, _ = current_block
        instructions = instructions[:start] + block + instructions[end:]
    for key, value in values.items():
        assign(document, key, value)
    state.update(files=files, block=block, values=values)
    changes = {**files, "config.toml": tomlkit.dumps(document), "AGENTS.md": instructions,
               STATE: json.dumps(state, indent=2, ensure_ascii=False) + "\n"}
    changed = [relative for relative, content in changes.items()
               if expected[relative] != content.encode("utf-8")]
    if action == "plan":
        print(f"Target: {home}\nAction: install\n" + ("Would write:\n" + "\n".join(f"  {name}" for name in changed) if changed else "Already up to date."))
    else:
        apply(home, {relative: changes[relative] for relative in changed}, expected)
        print("Installed." if changed else "Already up to date.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("plan", "install", "check", "uninstall"), default="plan")
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--models", type=Path, default=ROOT / "team.toml")
    args = parser.parse_args(argv)
    try:
        run(args.action, args.codex_home, args.models)
        return 0
    except (InstallError, OSError, ValueError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

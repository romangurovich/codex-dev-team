# Working on this repository

This project packages a personal Codex software-development workflow. Keep model
selection in `team.toml`, role instructions in `agents/`, and shared workflow
instructions in `assets/`. Installed files must be self-contained after the
source checkout moves or is removed.

For nontrivial implementation, delegate bounded work and use an independent
reviewer. Give writable paths one owner at a time. Keep review and verification
independent of implementation; repair actionable findings and rerun invalidated
checks before finishing.

Installer changes must preserve unrelated settings, comments, and instructions.
Validate all changes before writing. Test only with explicit temporary
`--codex-home` directories; never use the contributor's real Codex configuration.
Do not collect or commit credentials, personal configuration, local installation
state, or source-project/customer data. Model access and permission settings are
outside the installer's authority.

Run `python -m unittest discover -s tests -v` after changes. For installer changes,
also exercise plan, install, repeated install, check, and uninstall in a fresh
temporary directory and one containing existing configuration. Tests must prove
preservation and conflict behavior, not merely mirror output templates.

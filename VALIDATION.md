# Validation record

Validated on 2026-10-14 with macOS on ARM64, Python 3.13.12, and tomlkit 0.13.3.
Every installation target was an explicit temporary directory. No model calls or
real user configuration were required.

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -v` | 22 passed, zero skips |
| `python -m py_compile scripts/setup.py tests/test_setup.py` | Passed |
| Separate CLI lifecycle | 29 acceptance assertions passed |
| Focused uninstall/comment-preservation check | 9 assertions passed |
| Independent implementation review | No unresolved actionable findings |

The CLI checks exercised preview without writes, fresh and existing targets,
parseable role definitions, repeat-install idempotency, custom model updates,
self-contained installed references, and preservation through uninstall. The
suite also covers conflicting edits, concurrent saves during preparation and
commit, rollback, malformed state, symlink destinations, and a moved checkout.
Installer and test hashes remained unchanged during independent verification.

The verification-guidance update was also checked on 2026-10-14: all 22 tests
passed again with zero skips, all five agent TOML files parsed, and independent
review found no actionable issues. A separate temporary-target check passed 23
assertions while upgrading an installation of baseline `a0f66bf` to the revised
instructions, checking rendered content, preserved settings, repeat-install
idempotency, and uninstall restoration. Source hashes stayed fixed during that
check. These checks validate packaging and installation of the guidance; they do
not establish future agents' compliance with it.

The default-model update to GPT-6.1 Sol with extra-high reasoning passed the same
22-test suite with zero skips and 27 independent configuration/lifecycle checks.
Generated role pins and the orchestrator table matched `team.toml`; the installed
user configuration changed only its top-level model value. Interactive UI model
selection and backend model identity were not exercised by these checks.

A preliminary verification harness incorrectly required removal of an empty
`[agents]` table after uninstall. The accepted behavior retains that table when
needed to preserve a later user comment. The corrected check confirmed parseable
TOML, the preserved comment, and removal of all package-managed configuration and
files. This was a harness correction; application source did not change.

Verified source SHA-256:

```text
16cf0a09b1db4e5ed318ee8cf8a1512357a385b2581460064ed518259bf12e47  scripts/setup.py
eabdf709349e7fd7d128ace372f2528c2f484ba87b0ed4602cb8237c41e836f4  tests/test_setup.py
```

GitHub Actions is configured for Linux, macOS, and Windows with Python 3.11 and
3.13. That full matrix has not been executed for this initial package. Live Codex
role loading, backend model identity, and account entitlements are not established
by these installer checks. The README documents installation recovery limits.

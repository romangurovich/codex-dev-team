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

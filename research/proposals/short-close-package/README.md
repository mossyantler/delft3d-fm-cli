# Compatibility package preparation

`SHORT-CLOSE-COMPAT-PACK-I` composes the compatibility correction in a separate
candidate folder. It preserves the immutable pause checkpoint and accepted root.
The retained packager builds from the eedd base wheel with exactly two changed
modules and 189 unchanged payload files. No source-sink run profile, S07 or B14
command is included. Building a package does not authorize native execution.

Run `prepare.py` from the repository root with the application Python and a fresh
experiment destination, then use the copied `build_short_close.py --execute` with
that folder's `amendment.json`, the base wheel and wheelhouse recorded in
`preparation.json`, and a fresh child output folder. This requires retained local
wheel artifacts and Windows CPython 3.12.10.

Preparation verifies all 343 checkpoint entries, all 191 accepted root payloads
against the base wheel, and both proposed module hashes. The preparation freeze
includes the copied packager, its helper, metadata template and origin auditor.

Attempt `SHORT-CLOSE-COMPAT-PACK-I-20261105-01` failed because preparation omitted
`audit_install.py`. Its complete failed folder remains unchanged. Preparation
now includes the auditor, and attempt `SHORT-CLOSE-COMPAT-PACK-I-20261105-02`
uses a new folder. Test and package results are not additive. Independent wheel
verification, runner/reader composition and native regressions remain separate.

# Contributing

[中文版](CONTRIBUTING.zh-CN.md)

Contributions should preserve NCIt identifiers, raw relation direction, source provenance, and the distinction between existing nodes and unreviewed candidate entities.

Before proposing a change:

1. Do not add credentials, patient data, or proprietary documents.
2. Keep NCIt codes stable; do not replace them with display names as identifiers.
3. Preserve relationship direction in raw graph outputs.
4. Add evidence and source metadata for any incremental candidate node or relation.
5. Run `python .\scripts\validate_release.py` and Python syntax checks before opening a pull request.

For terminology updates, state the NCIt version, extraction date, root code, and the expected change in node or edge counts.

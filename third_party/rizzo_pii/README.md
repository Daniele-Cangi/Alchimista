# Rizzo-PII incorporated component

Alchimista incorporates only the text-only regex/checksum detector from
[Rizzo-PII](https://github.com/Rizzo-AI-Academy/rizzo-pii), not its PDF parser,
UI, desktop packaging, or PyMuPDF dependency.

- Upstream revision: `42d4a40ecfe31acbbe3e1d78cf4d79d38cd8c3f5`
- Source file: `src/app/detectors.py`
- Upstream source license: MIT
- Copyright: 2026 Simone Rizzo — Rizzo AI Academy
- Local copy: `third_party/rizzo_pii/detectors.py`

The original MIT notice is preserved in `LICENSE`. Changes to the detector
must be compared against the pinned upstream revision before updating this
snapshot. Alchimista does not include Rizzo's PyMuPDF-based PDF/UI layer, so
that dependency is not part of the default Alchimista image.

This notice records software provenance and is not legal advice.

# Rizzo-PII incorporated component

Alchimista incorporates only the text-only regex/checksum detector from
[Rizzo-PII](https://github.com/Rizzo-AI-Academy/rizzo-pii), not its PDF parser,
UI, desktop packaging, or PyMuPDF dependency.

- Upstream revision: `42d4a40ecfe31acbbe3e1d78cf4d79d38cd8c3f5`
- Upstream app release: `v2.0.0` (`aa7d13367766639666bca0b293956013b5ed782d`)
- Detector Git blob: `8f4b8bb061c3a6633e3b535001ec352611ccadcb`
- Source file: `src/app/detectors.py`
- Upstream source license: MIT
- Copyright: 2026 Simone Rizzo — Rizzo AI Academy
- Local copy: `third_party/rizzo_pii/detectors.py`

The pinned source revision is a descendant of the `v2.0.0` tag. The detector
blob is identical at the release tag and at the pinned revision; the intervening
commits concern packaging, documentation, and licensing. The original MIT
notice is preserved in `LICENSE`. Changes to the detector
must be compared against the pinned upstream revision before updating this
snapshot. Alchimista does not include Rizzo's PyMuPDF-based PDF/UI layer, so
that dependency is not part of the default Alchimista image.

This notice records software provenance and is not legal advice.

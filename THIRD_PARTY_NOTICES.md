# Third-party notices

This file records incorporated and optional third-party components. It is not
legal advice.

## Rizzo-PII text detector

Alchimista incorporates `src/app/detectors.py` from Rizzo-PII revision
`42d4a40ecfe31acbbe3e1d78cf4d79d38cd8c3f5`.

- Copyright (c) 2026 Simone Rizzo — Rizzo AI Academy
- License: MIT
- Preserved source and notice: `third_party/rizzo_pii/`
- Upstream: <https://github.com/Rizzo-AI-Academy/rizzo-pii>

The default Alchimista images do not incorporate Rizzo's UI, PDF layer,
PyMuPDF dependency, or model weights.

## Optional full Rizzo image

`compose.rizzo.yaml` can build the full upstream Rizzo service from the pinned
revision and model revision `v1.5.0`. That separately built image contains its
own dependency and model license boundary. The pinned upstream
`THIRD_PARTY_LICENSES.md` states that PyMuPDF is dual AGPL/commercial and
describes implications for distributed images/binaries containing it. Preserve
upstream notices when distributing that image.

Upstream also records model/training-data attribution and a missing license
declaration for one training dataset. Consult the pinned upstream notice before
redistributing the full image or model artifacts.

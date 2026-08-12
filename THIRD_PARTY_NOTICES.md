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

Alchimista images do not incorporate Rizzo's UI, PDF layer, PyMuPDF
dependency, or model weights.

## Managed full Rizzo model

The internal model runtime can download model revision `v1.5.0`, resolved to
commit `a1c3c83827eca22e9675e30c1111c4641caf5901`, into a local named volume.
The runtime image supplies CPU PyTorch/Transformers but does not contain the
model weights at build time and does not copy Rizzo's Flask UI or PyMuPDF
layer. Model files retain their own license and attribution boundary.

Upstream also records model/training-data attribution and a missing license
declaration for one training dataset. Consult the pinned upstream notice before
redistributing model artifacts. Preserve upstream notices with any such
distribution.

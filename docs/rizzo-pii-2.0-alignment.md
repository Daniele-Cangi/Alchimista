# Rizzo PII 2.0 alignment

This note records how Alchimista maps the upstream Rizzo PII `v2.0.0` release
onto its own privacy architecture. Application, detector source, and model are
separate version axes and must not be presented as one interchangeable number.

## Verified provenance

| Component | Version or revision used by Alchimista |
| --- | --- |
| Upstream application release | `v2.0.0` / `aa7d13367766639666bca0b293956013b5ed782d` |
| Incorporated detector source | `42d4a40ecfe31acbbe3e1d78cf4d79d38cd8c3f5` |
| Detector Git blob at both revisions | `8f4b8bb061c3a6633e3b535001ec352611ccadcb` |
| Full model | `rizzo-pii-0.3B@v1.5.0` |
| Immutable model commit | `a1c3c83827eca22e9675e30c1111c4641caf5901` |

The source revision is nine commits after the release tag. None changes
`src/app/detectors.py`; they concern upstream packaging, documentation, release
assets, model setup guidance, and licensing notices. There is therefore no
new regex/checksum implementation to import into Alchimista for this release.

## Feature adoption

| Rizzo PII 2.0 capability | Alchimista decision |
| --- | --- |
| Improved regex/checksum formats and faster overlap merge | Already incorporated in Lightweight and reused by Full. |
| Model `v1.5.0` | Already pinned to an immutable Hugging Face commit and covered by Full acceptance. |
| HTTP API | Reimplemented behind Alchimista's private, token-protected model boundary; the upstream open service is not exposed. |
| Reversible dictionary switch | Represented by workspace privacy policy and the encrypted privacy vault. Raw mappings never cross the service boundary. |
| Per-tag exclusion | Not imported. Under `STRICT`, detected PII must not be selectively left clear; a future governance policy would need explicit audit semantics. |
| PDF preview and redacted-PDF export | Not imported. Alchimista owns document ingestion and evidence views; adding a redacted export would be a separate product feature. |
| Desktop bundles and upstream UI | Not imported. Alchimista remains the localhost-first control plane. |
| PyMuPDF layer | Not imported, preserving the existing dependency and licensing boundary. |

## Operational rule

Future upgrades must compare the pinned detector blob, model revision, model
commit, output taxonomy, merge behavior, and license notices independently.
A new upstream application version alone is not sufficient reason to replace
the model or to change stored audit metadata. Any detector or model change must
pass unit tests, the self-hosted smoke suite, and Full Rizzo acceptance before
merge.

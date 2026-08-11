# Privacy architecture

This document describes implemented controls, not a legal certification or a
guarantee of PII detection accuracy.

## Trusted boundary

The local Compose network, PostgreSQL, mounted object volume, privacy service,
and local API callers are the configured trusted boundary. Any adapter that
sends text to an external model must call `prepare_external_text` before the
provider client.

```text
candidate external text
        |
        v
privacy policy + privacy service
        |
        +-- transformation fails --> block request
        |
        v
allowed original or pseudonymized text
        |
        v
external provider
```

The current active external-text path is Vertex text embedding. Vertex Vector
Search receives vectors and identifiers, not chunk text. The local SQL RAG
path does not call a remote LLM.

## Document order

```text
uploaded object
  -> trusted extraction
  -> document privacy analysis
  -> STRICT pseudonymization (when selected)
  -> chunking
  -> external egress protection (when applicable)
  -> embedding/index persistence
```

`protect_egress` retains original chunks inside the trusted deployment and
transforms text only when an external text provider is selected. `strict`
transforms the document before chunking, so normal retrieval storage receives
only placeholders.

## Placeholder properties

- placeholders are type-aware, for example `[EMAIL_1]`;
- repeated normalized values in one document reuse a placeholder;
- placeholders already present in input are reserved to prevent collision;
- reversible values are never returned in the API mapping;
- irreversible mode creates no vault mapping.

## Vault cryptography

`PRIVACY_VAULT_KEY` is URL-safe base64 for exactly 32 bytes. Values are
encrypted independently with AES-256-GCM and random 12-byte nonces. AAD binds
the tenant, document, placeholder, and key version. Value hashes are HMAC-SHA256
under the vault key, not unsalted plain hashes.

Rows record `key_version`. Rotation requires deploying the new version while
retaining a controlled way to decrypt/re-encrypt old rows; automated rotation
is remaining work.

## Failure behavior

Enabled privacy policies fail processing when:

- the privacy service is unavailable;
- the response is malformed;
- reversible mapping is requested while disabled;
- a vault key is corrupt, wrong, or of an unavailable version;
- an external payload cannot be transformed under `protect_egress` or
  `strict`.

Errors and audit metadata do not include the original value. Structured logs
redact known sensitive keys and formatted identifiers as a defense in depth.

## Audit evidence

`document_privacy` stores aggregate policy facts. Decision evidence combines
facts from context documents, omits privacy-enabled previews/source URIs, and
protects decision input/output before persistence. Mappings are not exported
with reports, bundles, or packages.

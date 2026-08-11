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

Each value in `PRIVACY_VAULT_KEYS_JSON` is URL-safe base64 for exactly 32
bytes. Values are encrypted independently with AES-256-GCM and random 12-byte
nonces. AAD binds the tenant, document, placeholder, and key version. Value
hashes are HMAC-SHA256 under the active vault key, not unsalted plain hashes.

`PRIVACY_VAULT_ACTIVE_KEY_VERSION` selects the key for new encryption. Rows
record `key_version`, and decryption resolves that version from the keyring.
The legacy `PRIVACY_VAULT_KEY` and `PRIVACY_VAULT_KEY_VERSION` pair remains a
backward-compatible one-key configuration.

The self-hosted Compose profile injects this key material only into
`privacy-service`. Processor, ingestion, RAG, dashboard, and database
containers receive no vault decryption keys.

The independent `RIZZO_MODEL_TOKEN` is scoped to `privacy-service` and the
unpublished `rizzo-model-service`. The dashboard reaches model controls only
through the privacy service and receives neither model token nor vault keys.

To rotate from `v1` to `v2`, deploy both keys and select `v2` as active:

```text
PRIVACY_VAULT_ACTIVE_KEY_VERSION=v2
PRIVACY_VAULT_KEYS_JSON={"v1":"<old-key>","v2":"<new-key>"}
```

New and subsequently refreshed mappings use `v2`; existing `v1` rows remain
restorable. Readiness fails if any stored version is absent from the keyring.
Bulk re-encryption is not implemented, so do not remove `v1` until a database
query confirms that no rows reference it.

## Vault lifecycle

`pii_vault.doc_id` has a foreign key to `documents.doc_id` with
`ON DELETE CASCADE`. When an authorized document deletion succeeds, its
reversible mappings are deleted in the same database transaction. Decision
context references may independently restrict document deletion; application
legal-hold policy remains responsible for authorizing the operation.
Persistent reversible pseudonymization therefore requires an existing
document with the same tenant and document identifier.

When `sql/schema.sql` upgrades a database created before this constraint, it
deletes already-orphaned vault rows and then adds the foreign key. Those rows
cannot have a valid document restoration owner and otherwise retain encrypted
PII indefinitely. Back up the database before applying any production schema
upgrade.

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

## Runtime policy and detector selection

`runtime_settings` is the authoritative workspace-scoped read model for the
active policy, detector, and reversible-mapping flag. Environment variables
are bootstrap defaults for a workspace without a row. Each change also writes
`runtime_settings_history`; it never updates historical `document_privacy`
evidence. Processor and decision ingestion resolve the setting for each new
operation. Full Rizzo cannot be selected until its internal readiness probe is
true, and it cannot be unloaded while any workspace still selects it.

Full model weights and their Alchimista SHA-256 manifest live on the
`rizzo-model-data` volume. The runtime downloads only the server-pinned model
and revision. Incomplete or modified artifacts produce `ERROR`; there is no
automatic Lightweight fallback that could falsely claim Full detection.

## Audit evidence

`document_privacy` stores aggregate policy facts. Decision evidence combines
facts from context documents, omits privacy-enabled previews/source URIs, and
protects decision input/output before persistence. Mappings are not exported
with reports, bundles, or packages.

# Alchimista

Alchimista is a self-hostable AI governance, document intelligence, RAG,
audit, and privacy infrastructure layer. It ingests evidence, builds a
tenant-scoped retrieval index, returns mandatory citations, and records AI
decision evidence with factual privacy metadata.

The baseline needs no GCP project, Auth0 tenant, external vector database,
object store, or paid service. GCP, Vertex, Pub/Sub, GCS, Cloud Run, and OIDC
remain optional adapters.

Alchimista implements technical controls. It does not certify GDPR, AI Act,
or other legal compliance, and its PII detectors are not guaranteed to find
every sensitive value.

## Self-hosted quickstart

Prerequisites: Docker Engine with Compose v2 and Python 3.11 or newer.

```bash
git clone https://github.com/Daniele-Cangi/Alchimista.git
cd Alchimista
python scripts/init_local_env.py
docker compose up --detach --build --wait
```

Open Alchimista at <http://127.0.0.1:8000>. Home, Documents, Ask, Privacy,
Audit, Governance, and System form one local application. Authentication and
service routing are handled server-side; normal browser use never asks for a
bearer token, tenant ID, or service URL. All published service ports bind
to loopback by default:

| Port | Service |
| --- | --- |
| `8000` | Alchimista product and local compatibility proxy |
| `8011` | ingestion, governance, decisions, and audit |
| `8012` | document processor |
| `8013` | RAG query API |
| `8014` | privacy API |
| `5432` | PostgreSQL |

The generated `.env` contains the local bearer token, admin key, internal
privacy/model tokens, audit signing key, PostgreSQL password, and a URL-safe 256-bit
privacy vault keyring. It is git-ignored. Treat it as secret material and back it
up if reversible mappings must survive host loss.

Verify the real vertical slice:

```bash
python scripts/self_hosted_smoke.py --verify-restart
```

Success ends with:

```text
SELF_HOSTED_SMOKE_OK
```

The smoke uses only synthetic identifiers. It verifies the localhost product
shell, persistent Documents view, interactive Ask evidence, ingest, privacy
detection, pseudonymization and restoration, protected persistence under
`STRICT`, SQL retrieval, citations, tenant isolation, AI decision evidence,
audit privacy metadata, encrypted vault content, vault cascade cleanup, and
persistence after a PostgreSQL restart.

Stop the stack without deleting persistent data:

```bash
docker compose down
```

Delete the named volumes only when you intentionally want to erase the local
database, stored documents, and privacy mappings:

```bash
docker compose down --volumes
```

### Minimal API example

Load `ALCHIMISTA_API_TOKEN` from `.env`, then upload a file:

```bash
curl -fsS -X POST http://127.0.0.1:8011/v1/ingest \
  -H "Authorization: Bearer ${ALCHIMISTA_API_TOKEN}" \
  -F tenant=default \
  -F doc_id=example-001 \
  -F file=@example.txt
```

Query it with citations:

```bash
curl -fsS -X POST http://127.0.0.1:8013/v1/query \
  -H "Authorization: Bearer ${ALCHIMISTA_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"tenant":"default","query":"What does the evidence say?","top_k":3,"doc_ids":["example-001"]}'
```

## Local runtime topology

```text
browser ──> dashboard ───┬──> ingestion ──direct HTTP──> processor
                         ├──> RAG                         │
                         └──> privacy-service <───────────┘
                                   │
                                   └──> Rizzo model runtime (idle by default)
                         services ─────> PostgreSQL

ingestion + processor ──> shared filesystem object volume
```

`schema-init` applies `sql/schema.sql` on every Compose start. PostgreSQL and
the object store use named volumes. The local queue adapter calls the existing
processor HTTP contract directly; no broker is added merely to imitate
Pub/Sub.

The local RAG baseline reuses the existing SQL embedding scan and deterministic
offline embedder. This is easy to start and proves retrieval/citation
correctness, but it is not a claim of production semantic quality. Vertex
embeddings and Vertex Vector Search remain optional.

## Runtime profiles

`ALCHIMISTA_PROFILE=local` is the self-hosted baseline:

- PostgreSQL;
- `local://` object URIs backed by the mounted filesystem volume;
- direct internal HTTP processing;
- SQL retrieval and offline deterministic embeddings;
- local bearer-token authentication.

`ALCHIMISTA_PROFILE=gcp` retains:

- GCS storage;
- Pub/Sub and its Google service-to-service authentication boundary;
- optional Vertex embeddings and Vector Search;
- Cloud Run deployment scripts and Terraform;
- provider-independent OIDC for human/API authentication.

The existing API response field names such as `gs_uri` are retained for
compatibility. In filesystem mode those fields can contain a `local://` URI.

## Authentication modes

Set `AUTH_MODE` to one of:

- `local`: validates a constant-time-compared bearer token from
  `LOCAL_AUTH_TOKEN` or `ALCHIMISTA_API_TOKEN`. `LOCAL_AUTH_TENANTS` limits its
  tenants; `*` is the single-admin default generated for a loopback deployment.
- `oidc`: validates issuer, audience, signature, time claims, principal, and
  tenant claims. It is provider-independent and can be configured for Auth0,
  Keycloak, Entra ID, Okta, or another standards-compliant provider.
- `disabled`: allowed only in explicit development, test, or CI environments.
  Startup fails if it is selected for `production` or `external`.

Pub/Sub push identity is still validated separately with Google's service
identity rules. It is not part of the general OIDC subsystem.

The product proxy uses `DASHBOARD_API_TOKEN` server-side so a loopback local
deployment does not expose the token to browser JavaScript. Bind and reverse
proxy choices remain the operator's security boundary. Every dashboard API
mutation also requires `X-Alchimista-Control: same-origin`; browser requests
with a cross-site fetch signal or an `Origin` outside
`DASHBOARD_ALLOWED_ORIGINS` are rejected before the dashboard adds internal
credentials. The built-in UI sends this header automatically. Non-browser
automation must add it explicitly. A reverse proxy on another origin must set
the exact allowed origin rather than disabling this check. Dashboard multipart
uploads are capped at 25 MiB by default; set `DASHBOARD_MAX_UPLOAD_BYTES` to a
different positive byte limit when the deployment requires it.

Workspace privacy configuration is persisted in PostgreSQL. Environment
variables bootstrap the first row only. Changing policy or detector affects
new processing deterministically; existing `document_privacy` rows retain the
policy and detector actually applied until an explicit reprocess.

## Privacy policies

Set `PRIVACY_POLICY` to:

| Policy | Detection | Retrieval/index storage | External model text |
| --- | --- | --- | --- |
| `off` | legacy regex entity extraction | original chunks and legacy raw `entities` values | unchanged |
| `detect` | Rizzo findings, hashes, and metadata | original chunks; no raw values in `entities` | unchanged |
| `protect_egress` | Rizzo findings and metadata | original chunks may remain inside the trusted deployment | pseudonymized before a configured external embedding call |
| `strict` | Rizzo findings and metadata | pseudonymized before chunking and embedding | only the protected representation |

All enabled privacy policies fail closed if the privacy service is unavailable
or returns a malformed response. Decision `input` and `output` fields are
pseudonymized irreversibly before entering audit evidence whenever privacy is
enabled. Context previews and source URIs are omitted from privacy-enabled
audit reports.

The raw uploaded object remains in the trusted raw object volume according to
the operator's retention policy. `STRICT` specifically prevents cleartext from
normal retrieval/index storage; it does not pretend the original upload never
existed.

Privacy endpoints:

```text
GET  /v1/privacy/health
GET  /v1/privacy/ready
GET  /v1/privacy/settings
PUT  /v1/privacy/settings
GET  /v1/privacy/model
POST /v1/privacy/model/{install|load|unload}
POST /v1/privacy/detect
POST /v1/privacy/pseudonymize
POST /v1/privacy/restore
```

Operational endpoints require `x-privacy-token` and are intended for the
private deployment network. API responses include detector name, version,
mode, and pinned source revision. They never return the raw placeholder map.

### PII persistence and vault

- `pii_findings` stores tenant/document scope, type, detector, confidence,
  offsets, type-aware placeholder, keyed value hash, and validation metadata.
- `pii_vault` stores AES-256-GCM ciphertext, a random 96-bit nonce, keyed hash,
  and key version. Additional authenticated data binds tenant, document,
  placeholder, and key version.
- `pii_vault.doc_id` references `documents.doc_id` with `ON DELETE CASCADE`, so
  document deletion cannot leave encrypted PII mappings orphaned. Schema
  upgrade removes pre-constraint orphan rows before adding the invariant.
- `document_privacy` records the applied policy and audit-safe aggregate facts.
- raw values are written to the legacy `entities` table only under `off`.

`PRIVACY_VAULT_KEYS_JSON` supplies a version-to-key keyring and
`PRIVACY_VAULT_ACTIVE_KEY_VERSION` selects the key for new ciphertext and
keyed hashes. Decryption selects the key recorded in each row. The legacy
single-key variables remain accepted for rolling upgrades. Readiness fails if
the database references an unavailable key version. The Compose deployment
injects vault key material only into `privacy-service`; other application
containers receive the internal privacy API URL and token, but no decryption
keys.

Automatic bulk re-encryption is not implemented. Keep an old key in the
keyring until no rows reference its version; removing it earlier deliberately
fails restoration closed.

See [docs/privacy.md](docs/privacy.md) for precise boundary behavior.

## Rizzo-PII integration and attribution

The lightweight privacy image incorporates only Rizzo-PII's text-only
regex/checksum detector. It does not copy the Rizzo UI, PDF parser, desktop
application, or PyMuPDF dependency.

- Upstream: `Rizzo-AI-Academy/rizzo-pii`
- Pinned source revision: `42d4a40ecfe31acbbe3e1d78cf4d79d38cd8c3f5`
- Model revision used by the managed full engine: `v1.5.0`
- Resolved immutable model commit: `a1c3c83827eca22e9675e30c1111c4641caf5901`
- Incorporated source license: MIT
- Original copyright and license: `third_party/rizzo_pii/`

The pinned upstream revision was rechecked before this integration. The normal
`compose.yaml` includes a dedicated, unexposed CPU model runtime. It starts
without weights and without loading the 0.3B model. From the Privacy page the
user can install, load, activate, switch back to Lightweight, and unload Full
Rizzo without Docker access.

Installation accepts no repository or revision from the browser. The service
downloads only the commit resolved from `rizzoaiacademy/rizzo-pii-0.3B@v1.5.0`, validates required
artifacts, writes a SHA-256 manifest, and atomically promotes the completed
download into the `rizzo-model-data` named volume. States are truthful:
`NOT_INSTALLED`, `DOWNLOADING`, `INSTALLED`, `LOADING`, `READY`, or `ERROR`.
After installation, loading and inference can operate offline. A restart
validates the manifest and returns to `INSTALLED`; weights are not downloaded
again. Full detector selection is rejected until the runtime is `READY`, and
privacy operations fail closed if an already-selected Full runtime becomes
unavailable.

The Full-Rizzo input dependencies live in
`services/rizzo_model_service/requirements.in`; the generated
`requirements.lock` fixes every transitive Linux/Python 3.11 CPU distribution
and its SHA-256 hashes. The container installs that lock with
`--require-hashes` from PyPI and the official PyTorch CPU index. Regenerate it
with `uv 0.12.3` by running
`python scripts/lock_rizzo_model_dependencies.py`. The privacy-to-model transport sends
overlapping windows of at most one million characters, preserves global
finding offsets, and merges overlap duplicates. Consequently a document below
the dashboard upload limit is not rejected merely because extracted text is
longer than the model service's single-request validation limit. Any failed
window fails the privacy operation; it does not trigger a silent Lightweight
fallback. On bootstrap the model runtime removes an orphaned `.partial`
download left by a hard stop before reporting installation state.

See [docs/full-rizzo-acceptance.md](docs/full-rizzo-acceptance.md) for the
browser-only install/load/activate/restart acceptance path.

Upstream documents PyMuPDF as dual AGPL/commercial and notes consequences for
images/binaries that contain it. Alchimista's managed text inference runtime
does not include PyMuPDF; document parsing remains in the processor. See
`THIRD_PARTY_NOTICES.md` and upstream's pinned `THIRD_PARTY_LICENSES.md`.

## Audit and governance evidence

AI decision metadata now includes audit-safe facts such as:

```json
{
  "privacy": {
    "privacy_policy": "strict",
    "pii_detected": 3,
    "pii_types": ["CREDITCARDNUMBER", "EMAIL", "IBAN"],
    "external_payload_pseudonymized": false,
    "mapping_exported": false,
    "privacy_engine": "rizzo-pii",
    "privacy_engine_version": "2.0.0-regex-snapshot",
    "privacy_engine_source_revision": "42d4a40ecfe31acbbe3e1d78cf4d79d38cd8c3f5"
  }
}
```

This proves which implemented transformation was recorded. It is not a legal
compliance certificate. Existing decision reports, signed exports, immutable
artifacts, retention policies, legal holds, and tenant scoping remain in place.

## Optional enterprise and cloud integrations

Use `.env.gcp.example` as the configuration map. Existing GCP deployment and
Terraform assets remain under `scripts/` and `infra/terraform/`.

- OIDC: set `AUTH_MODE=oidc`, issuer, audiences, algorithms, JWKS/discovery,
  and tenant claims.
- GCS: set `STORAGE_BACKEND=gcs` and the three bucket variables.
- Pub/Sub: set `QUEUE_BACKEND=pubsub`; configure push identity separately.
- Vertex: select `vertex_text_embedding` and/or
  `vertex_ai_vector_search` with the existing IDs.
- Cloud Run: `scripts/deploy_cloud_run_service.sh` now marks deployments with
  `ALCHIMISTA_PROFILE=gcp`.

Cloud workflows are manual/separate from the open-source baseline. The
baseline `ci` workflow needs no GCP or Auth0 secrets.

The obsolete Vercel catch-all and recovered placeholder API were removed:
they could render a serverless dashboard but could not reach a user's private
Compose services, so they were not a valid deployment of Alchimista. The
minimal `vercel.json` now only disables automatic Git deployments, preventing
the existing Vercel integration from publishing or failing previews for this
localhost-only product. It contains no build, route, or runtime configuration.
Optional GCP/Cloud Run adapters remain supported independently.

## CI and container publishing

`.github/workflows/ci.yml` runs unit/security tests and the full Compose smoke
under `STRICT`. `.github/workflows/publish-ghcr.yml` publishes six images only
on a version tag or manual dispatch:

```text
ghcr.io/daniele-cangi/alchimista-ingestion
ghcr.io/daniele-cangi/alchimista-processor
ghcr.io/daniele-cangi/alchimista-rag
ghcr.io/daniele-cangi/alchimista-dashboard
ghcr.io/daniele-cangi/alchimista-privacy
ghcr.io/daniele-cangi/alchimista-rizzo-model
```

Every publish includes a full commit-SHA tag and, for releases, the Git tag.
`latest` is not emitted. Defining the workflow does not mean images have
already been published.

## Repository map

- `compose.yaml`: supported local stack
- `services/shared`: runtime, auth, storage, queue, privacy, DB, embeddings,
  retrieval, and egress boundaries
- `services/privacy_service`: narrow privacy API and encrypted vault
- `services/rizzo_model_service`: idle/install/load/unload Full Rizzo runtime
- `services/ingestion_api_service`: ingest, decisions, audit, governance
- `services/document_processor_service`: extraction, privacy policy, chunking,
  embedding, indexing
- `services/rag_query_service`: SQL/Vertex retrieval and citations
- `services/dashboard_service`: local UI and API proxy
- `sql/schema.sql`: canonical schema and privacy tables
- `tests`: focused unit/security regressions
- `scripts/self_hosted_smoke.py`: end-to-end proof
- `infra/terraform`: optional GCP infrastructure

The pre-change implementation map and architectural decisions are in
[docs/architecture/phase-0-audit.md](docs/architecture/phase-0-audit.md).

## Current limitations

- The default Rizzo regex/checksum layer is precise for supported formatted
  identifiers but does not provide the full 22-class ML taxonomy. Install and
  activate Full Rizzo from Privacy when that tradeoff is appropriate.
- Pseudonymization can change retrieval semantics and entity relationships.
  `STRICT` therefore needs evaluation on each domain dataset.
- The SQL embedding scan intentionally prioritizes easy startup over scale.
- Local auth is a single-token model, not a user directory or identity
  platform.
- Vault key selection and backward decryption are versioned; bulk
  re-encryption and retirement automation are not implemented.
- OCR quality depends on host/document characteristics and is not covered by
  the synthetic text smoke.

## License

Alchimista is licensed under `AGPL-3.0-only`. See `LICENSE`, `NOTICE`,
`TERMS.md`, and `THIRD_PARTY_NOTICES.md`.

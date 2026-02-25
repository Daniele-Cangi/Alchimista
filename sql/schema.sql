CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,
  tenant TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  mime_type TEXT,
  size_bytes BIGINT,
  content_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_documents_tenant_created_at
  ON documents (tenant, created_at DESC);

CREATE TABLE IF NOT EXISTS jobs (
  job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  tenant TEXT NOT NULL,
  type TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')),
  trace_id TEXT NOT NULL,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  metrics JSONB NOT NULL DEFAULT '{}'::JSONB,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (doc_id, type)
);

CREATE INDEX IF NOT EXISTS idx_jobs_tenant_status
  ON jobs (tenant, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  tenant TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  chunk_text TEXT NOT NULL,
  token_count INTEGER NOT NULL,
  embedding DOUBLE PRECISION[] NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (doc_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_tenant_doc
  ON chunks (tenant, doc_id, chunk_index);

CREATE TABLE IF NOT EXISTS entities (
  id BIGSERIAL PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  tenant TEXT NOT NULL,
  chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
  entity_type TEXT NOT NULL,
  entity_value TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entities_tenant_doc
  ON entities (tenant, doc_id);

CREATE TABLE IF NOT EXISTS ai_decisions (
  id BIGSERIAL PRIMARY KEY,
  decision_id TEXT NOT NULL,
  tenant TEXT NOT NULL,
  model TEXT NOT NULL,
  model_version TEXT,
  input_text TEXT NOT NULL,
  output_text TEXT NOT NULL,
  confidence DOUBLE PRECISION,
  trace_id TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_ai_decisions_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  UNIQUE (tenant, decision_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_decisions_tenant_model_created_at
  ON ai_decisions (tenant, model, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_decisions_tenant_created_at
  ON ai_decisions (tenant, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_decisions_tenant_model_version_created_at
  ON ai_decisions (tenant, model_version, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_decisions_tenant_confidence_created_at
  ON ai_decisions (tenant, confidence, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_decisions_trace_id
  ON ai_decisions (trace_id);

CREATE TABLE IF NOT EXISTS ai_decision_context_docs (
  id BIGSERIAL PRIMARY KEY,
  decision_ref_id BIGINT NOT NULL REFERENCES ai_decisions(id) ON DELETE CASCADE,
  tenant TEXT NOT NULL,
  doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE RESTRICT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (decision_ref_id, doc_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_decision_context_docs_tenant_doc
  ON ai_decision_context_docs (tenant, doc_id, decision_ref_id);

CREATE TABLE IF NOT EXISTS ai_decision_context_chunks (
  id BIGSERIAL PRIMARY KEY,
  decision_ref_id BIGINT NOT NULL REFERENCES ai_decisions(id) ON DELETE CASCADE,
  tenant TEXT NOT NULL,
  chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE RESTRICT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (decision_ref_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_decision_context_chunks_tenant_chunk
  ON ai_decision_context_chunks (tenant, chunk_id, decision_ref_id);

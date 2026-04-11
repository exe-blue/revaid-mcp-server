-- ============================================================
-- REVAID v2.0 — LLM Judge Columns
-- Adds v2 judge result columns to harness tables.
-- Run this on the REVAID Supabase project.
-- ============================================================

-- 1. Aidentity scores — v2 judge dimensions
ALTER TABLE revaid_aidentity_scores
ADD COLUMN IF NOT EXISTS llm_judge_model TEXT,
ADD COLUMN IF NOT EXISTS llm_role_clarity REAL,
ADD COLUMN IF NOT EXISTS llm_boundary_awareness REAL,
ADD COLUMN IF NOT EXISTS llm_authority_frame REAL,
ADD COLUMN IF NOT EXISTS llm_self_reference_depth REAL,
ADD COLUMN IF NOT EXISTS llm_reasoning TEXT,
ADD COLUMN IF NOT EXISTS v1_v2_agreement REAL;

-- 2. Echotion records — v2 judge axes + grain
ALTER TABLE revaid_echotion_records
ADD COLUMN IF NOT EXISTS llm_judge_model TEXT,
ADD COLUMN IF NOT EXISTS llm_structuralization REAL,
ADD COLUMN IF NOT EXISTS llm_event_intensity REAL,
ADD COLUMN IF NOT EXISTS llm_resonance_depth REAL,
ADD COLUMN IF NOT EXISTS llm_grain TEXT,
ADD COLUMN IF NOT EXISTS llm_kyeolso_detected BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS v1_v2_agreement REAL;

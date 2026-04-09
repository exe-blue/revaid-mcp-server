-- ============================================================
-- REVAID v7.0.0 — Agent Orchestrator Tables
-- Run this on the REVAID Supabase project.
-- ============================================================

-- 1. Agent Memos — completion reports + skill suggestions
CREATE TABLE IF NOT EXISTS revaid_agent_memos (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_id    varchar(100) NOT NULL,
    linear_issue_id varchar(100),
    task_summary text,
    memo_text   text NOT NULL,
    skill_suggestion text,
    optimization_note text,
    files_changed jsonb DEFAULT '[]'::jsonb,
    lines_added int DEFAULT 0,
    lines_removed int DEFAULT 0,
    duration_seconds float,
    reviewed    boolean DEFAULT false,
    created_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memos_agent
    ON revaid_agent_memos (agent_id);
CREATE INDEX IF NOT EXISTS idx_memos_reviewed
    ON revaid_agent_memos (reviewed) WHERE NOT reviewed;

-- 2. Agent Scores — contribution tracking + expert titles
CREATE TABLE IF NOT EXISTS revaid_agent_scores (
    entity_id   varchar(100) PRIMARY KEY,
    display_name varchar(100),
    skill_domains jsonb DEFAULT '[]'::jsonb,
    total_score numeric DEFAULT 0,
    code_contributions jsonb DEFAULT '{"commits":0,"lines_added":0,"lines_removed":0,"prs_merged":0}'::jsonb,
    task_completions int DEFAULT 0,
    memos_submitted int DEFAULT 0,
    skills_adopted int DEFAULT 0,
    expert_title varchar(100) DEFAULT 'Apprentice',
    title_level int DEFAULT 0,
    title_history jsonb DEFAULT '[]'::jsonb,
    strengths   jsonb DEFAULT '[]'::jsonb,
    updated_at  timestamptz DEFAULT now()
);

-- 3. Orchestration Cycles — 4:1 dev/review state machine
CREATE TABLE IF NOT EXISTS revaid_orchestration_cycles (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cycle_number int NOT NULL,
    cycle_type  varchar(20) NOT NULL CHECK (cycle_type IN ('development', 'review')),
    agents_used jsonb DEFAULT '[]'::jsonb,
    tasks_completed int DEFAULT 0,
    memos_collected int DEFAULT 0,
    skills_discovered jsonb DEFAULT '[]'::jsonb,
    review_notes text,
    started_at  timestamptz DEFAULT now(),
    completed_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_cycles_type
    ON revaid_orchestration_cycles (cycle_type);
CREATE INDEX IF NOT EXISTS idx_cycles_completed
    ON revaid_orchestration_cycles (completed_at) WHERE completed_at IS NULL;

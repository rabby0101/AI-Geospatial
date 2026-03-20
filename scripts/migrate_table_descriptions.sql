-- Migration: Add rich metadata columns to metadata.table_descriptions
-- Run once before deploying the schema-driven system.
-- All new columns use NULL defaults so existing data is unaffected.

ALTER TABLE metadata.table_descriptions
  ADD COLUMN IF NOT EXISTS usage_hint      TEXT,
  ADD COLUMN IF NOT EXISTS key_columns     TEXT[],
  ADD COLUMN IF NOT EXISTS related_tables  TEXT[],
  ADD COLUMN IF NOT EXISTS analysis_patterns TEXT[],
  ADD COLUMN IF NOT EXISTS updated_at      TIMESTAMPTZ DEFAULT NOW();

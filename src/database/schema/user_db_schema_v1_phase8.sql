-- User Database Schema v1.0.0 - Phase 8
-- Rich Text JSON Storage for Quill Delta Format
-- Author: WIMI Development Team
-- Date: January 2026

-- ==============================================================================
-- PHASE 8: Rich Text JSON Storage
-- These columns are ADDITIVE - existing tables/columns remain unchanged
-- ==============================================================================

-- ==============================================================================
-- MODIFICATIONS TO EXISTING TABLES: question_entries
-- Add JSON columns to store Quill Delta format for rich text editing
-- ==============================================================================

-- Add explanation_json column to store Quill Delta JSON for explanations
-- Existing 'explanation' column stores plain text/HTML for display
-- ALTER TABLE question_entries ADD COLUMN explanation_json TEXT;

-- Add reflection_json column to store Quill Delta JSON for reflections
-- Existing 'reflection' column stores plain text/HTML for display
-- ALTER TABLE question_entries ADD COLUMN reflection_json TEXT;

-- Add notes_json column to store Quill Delta JSON for notes
-- Existing 'notes' column stores plain text/HTML for display
-- ALTER TABLE question_entries ADD COLUMN notes_json TEXT;

-- ==============================================================================
-- NOTES ON MIGRATION STRATEGY
-- ==============================================================================
--
-- The _json columns will be NULL for existing entries until:
-- 1. User edits the entry in the new rich text editor
-- 2. On save, the Quill Delta JSON is stored in the _json column
-- 3. The rendered HTML is stored in the existing column for display
--
-- On load:
-- - If _json column has data, use it to initialize Quill editor
-- - If _json column is NULL, initialize empty Quill and render existing HTML
--
-- This approach ensures:
-- - Backward compatibility with existing data
-- - Progressive migration as users edit entries
-- - No data loss during transition

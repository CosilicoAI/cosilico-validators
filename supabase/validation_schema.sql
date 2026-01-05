-- Supabase Schema for Validation Logging
-- Tracks RAC encoding validation against PE and TAXSIM oracles

-- =============================================================================
-- VALIDATION RUNS
-- Each encoding validation run creates a record here
-- =============================================================================
CREATE TABLE IF NOT EXISTS validation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- What was validated
    rac_version TEXT NOT NULL,  -- git commit hash of rac-us
    rac_path TEXT,  -- e.g., "statute/26/32" for EITC
    citation TEXT,  -- e.g., "26 USC § 32"

    -- Population info
    population TEXT DEFAULT 'cps_asec',  -- microdata source
    pop_year INT,  -- Population year (e.g., 2024)
    n_records INT,  -- Number of tax units/records

    -- Overall metrics
    overall_match_rate FLOAT,  -- % of record-variables within tolerance
    n_variables INT,  -- Number of variables compared

    -- Sources compared
    sources JSONB,  -- e.g., {"pe_year": 2024, "taxsim_year": 2023, "rac_version": "abc123"}

    -- Metadata
    sdk_session_id TEXT,  -- Link to SDK session if applicable
    notes TEXT
);

-- =============================================================================
-- VALIDATION RESULTS (per variable)
-- Detailed results for each variable in a validation run
-- =============================================================================
CREATE TABLE IF NOT EXISTS validation_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES validation_runs(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Variable info
    variable_name TEXT NOT NULL,  -- e.g., "eitc"
    rac_path TEXT,  -- e.g., "statute/26/32#eitc"

    -- Comparison metrics
    source_a TEXT NOT NULL,  -- e.g., "PolicyEngine"
    source_b TEXT NOT NULL,  -- e.g., "TAXSIM" or "Cosilico"

    n_records INT,
    n_matched INT,  -- Within tolerance
    match_rate FLOAT,

    mean_diff FLOAT,
    max_diff FLOAT,
    total_a FLOAT,  -- Aggregate sum from source A
    total_b FLOAT,  -- Aggregate sum from source B
    aggregate_diff_pct FLOAT,

    -- Tolerance used
    tolerance FLOAT DEFAULT 10.0
);

-- =============================================================================
-- VARIABLE MAPPING
-- Stores the mapping between RAC, PE, and TAXSIM variables
-- =============================================================================
CREATE TABLE IF NOT EXISTS variable_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    variable_name TEXT UNIQUE NOT NULL,
    rac_path TEXT,
    pe_var TEXT,
    taxsim_var TEXT,
    entity TEXT,  -- "person", "tax_unit", "household"
    description TEXT
);

-- =============================================================================
-- RECORD VALUES (optional, for detailed debugging)
-- Per-record values for a specific variable/run
-- Disabled by default due to size - enable with detailed=true
-- =============================================================================
CREATE TABLE IF NOT EXISTS validation_record_values (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID REFERENCES validation_runs(id) ON DELETE CASCADE,
    result_id UUID REFERENCES validation_results(id) ON DELETE CASCADE,

    record_id BIGINT NOT NULL,  -- tax_unit_id
    value_a FLOAT,
    value_b FLOAT,
    diff FLOAT,
    matched BOOLEAN
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_validation_runs_rac_version
    ON validation_runs(rac_version);
CREATE INDEX IF NOT EXISTS idx_validation_runs_rac_path
    ON validation_runs(rac_path);
CREATE INDEX IF NOT EXISTS idx_validation_results_run_id
    ON validation_results(run_id);
CREATE INDEX IF NOT EXISTS idx_validation_results_variable
    ON validation_results(variable_name);
CREATE INDEX IF NOT EXISTS idx_record_values_run_id
    ON validation_record_values(run_id);

-- =============================================================================
-- SUMMARY VIEW
-- Aggregate view of validation performance over time
-- =============================================================================
CREATE OR REPLACE VIEW validation_summary AS
SELECT
    rac_version,
    rac_path,
    citation,
    COUNT(*) as n_runs,
    AVG(overall_match_rate) as avg_match_rate,
    MAX(created_at) as last_run,
    SUM(n_records) as total_records
FROM validation_runs
GROUP BY rac_version, rac_path, citation
ORDER BY last_run DESC;

-- =============================================================================
-- ACCURACY BY VARIABLE VIEW
-- See which variables have the best/worst accuracy
-- =============================================================================
CREATE OR REPLACE VIEW variable_accuracy AS
SELECT
    variable_name,
    source_a,
    source_b,
    COUNT(*) as n_comparisons,
    AVG(match_rate) as avg_match_rate,
    AVG(aggregate_diff_pct) as avg_agg_diff_pct,
    MAX(max_diff) as worst_case_diff
FROM validation_results
GROUP BY variable_name, source_a, source_b
ORDER BY avg_match_rate;

"""
Supabase Logger for Validation Results

Logs validation runs and results to Supabase for tracking and dashboards.
"""

import os
import subprocess
from datetime import datetime
from typing import Optional
from dataclasses import asdict

from supabase import create_client, Client

from .oracle_comparison import ComparisonResult, compute_overall_accuracy


def get_supabase_client() -> Optional[Client]:
    """Get Supabase client from environment variables."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("Warning: SUPABASE_URL and SUPABASE_KEY not set, logging disabled")
        return None

    return create_client(url, key)


def get_rac_version() -> str:
    """Get current git commit hash of rac-us repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=os.environ.get("RAC_US_PATH", "/Users/maxghenis/CosilicoAI/rac-us")
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def log_validation_run(
    results: list[ComparisonResult],
    rac_path: Optional[str] = None,
    citation: Optional[str] = None,
    pe_year: int = 2024,
    taxsim_year: int = 2023,
    n_records: int = 0,
    sdk_session_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[str]:
    """
    Log a validation run and its results to Supabase.

    Returns the run_id if successful, None otherwise.
    """
    client = get_supabase_client()
    if not client:
        return None

    accuracy = compute_overall_accuracy(results)
    rac_version = get_rac_version()

    # Create run record
    run_data = {
        "rac_version": rac_version,
        "rac_path": rac_path,
        "citation": citation,
        "population": "cps_asec",
        "pop_year": 2024,  # PE population year
        "n_records": n_records or (results[0].n_records if results else 0),
        "overall_match_rate": accuracy["overall_match_rate"],
        "n_variables": accuracy["n_variables"],
        "sources": {
            "pe_year": pe_year,
            "taxsim_year": taxsim_year,
            "rac_version": rac_version,
        },
        "sdk_session_id": sdk_session_id,
        "notes": notes,
    }

    try:
        run_response = client.table("validation_runs").insert(run_data).execute()
        run_id = run_response.data[0]["id"]

        # Log individual results
        for r in results:
            result_data = {
                "run_id": run_id,
                "variable_name": r.variable,
                "source_a": r.source_a,
                "source_b": r.source_b,
                "n_records": r.n_records,
                "n_matched": r.n_matched,
                "match_rate": r.match_rate,
                "mean_diff": r.mean_diff,
                "max_diff": r.max_diff,
                "total_a": r.total_a,
                "total_b": r.total_b,
                "aggregate_diff_pct": r.aggregate_diff_pct,
            }
            client.table("validation_results").insert(result_data).execute()

        print(f"Logged validation run: {run_id}")
        return run_id

    except Exception as e:
        print(f"Error logging to Supabase: {e}")
        return None


def get_validation_history(
    rac_path: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Get recent validation runs, optionally filtered by rac_path."""
    client = get_supabase_client()
    if not client:
        return []

    try:
        query = client.table("validation_runs").select("*").order("created_at", desc=True).limit(limit)

        if rac_path:
            query = query.eq("rac_path", rac_path)

        response = query.execute()
        return response.data

    except Exception as e:
        print(f"Error fetching from Supabase: {e}")
        return []


def get_accuracy_by_variable() -> list[dict]:
    """Get accuracy summary by variable (uses view)."""
    client = get_supabase_client()
    if not client:
        return []

    try:
        response = client.table("variable_accuracy").select("*").execute()
        return response.data
    except Exception as e:
        print(f"Error fetching variable accuracy: {e}")
        return []

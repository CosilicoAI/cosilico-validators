"""Core record-by-record comparison logic."""

from datetime import datetime
from typing import Any

import numpy as np

# Conditional imports
try:
    from policyengine_us import Microsimulation

    HAS_POLICYENGINE = True
except ImportError:
    HAS_POLICYENGINE = False
    Microsimulation = None


def compare_records(
    cosilico_values: np.ndarray,
    pe_values: np.ndarray,
    tolerance: float = 1.0,
    top_n_mismatches: int = 10,
) -> dict:
    """Compare Cosilico vs PolicyEngine values record-by-record.

    Args:
        cosilico_values: Array of Cosilico-computed values
        pe_values: Array of PolicyEngine values
        tolerance: Maximum difference to consider a match (in dollars)
        top_n_mismatches: Number of worst mismatches to return

    Returns:
        Dict with match_rate, MAE, error distribution, worst mismatches
    """
    assert len(cosilico_values) == len(pe_values), "Arrays must have same length"

    n_records = len(cosilico_values)
    abs_errors = np.abs(cosilico_values - pe_values)

    # Match rate
    matches = abs_errors <= tolerance
    n_matches = int(np.sum(matches))
    n_mismatches = n_records - n_matches
    match_rate = n_matches / n_records if n_records > 0 else 0.0

    # Error stats
    mean_absolute_error = float(np.mean(abs_errors))
    max_error = float(np.max(abs_errors))

    # Error percentiles
    error_percentiles = {
        "p50": float(np.percentile(abs_errors, 50)),
        "p90": float(np.percentile(abs_errors, 90)),
        "p95": float(np.percentile(abs_errors, 95)),
        "p99": float(np.percentile(abs_errors, 99)),
        "max": max_error,
    }

    # Worst mismatches
    worst_indices = np.argsort(abs_errors)[-top_n_mismatches:][::-1]
    worst_mismatches = []
    for idx in worst_indices:
        if abs_errors[idx] > tolerance:
            worst_mismatches.append({
                "index": int(idx),
                "cosilico": float(cosilico_values[idx]),
                "policyengine": float(pe_values[idx]),
                "difference": float(abs_errors[idx]),
            })

    return {
        "n_records": n_records,
        "n_matches": n_matches,
        "n_mismatches": n_mismatches,
        "match_rate": match_rate,
        "mean_absolute_error": mean_absolute_error,
        "error_percentiles": error_percentiles,
        "worst_mismatches": worst_mismatches,
        "tolerance": tolerance,
    }


def load_pe_values(variable: str, year: int = 2024) -> np.ndarray:
    """Load PolicyEngine values for a variable across CPS.

    Args:
        variable: PolicyEngine variable name
        year: Tax year

    Returns:
        Array of values for each tax unit
    """
    if not HAS_POLICYENGINE:
        raise ImportError("policyengine_us not installed")

    sim = Microsimulation()
    values = sim.calculate(variable, year)
    return np.array(values)


def load_cosilico_values(variable: str, year: int = 2024) -> np.ndarray:
    """Load Cosilico-computed values for a variable across CPS.

    Args:
        variable: Variable name (maps to Cosilico statute)
        year: Tax year

    Returns:
        Array of values for each tax unit

    Raises:
        NotImplementedError: Until cosilico-engine is integrated
    """
    # TODO: Integrate cosilico-engine when ready
    # This requires:
    # 1. Loading CPS input data (employment_income, filing_status, etc.)
    # 2. Running Cosilico's income_tax calculation on each record
    # 3. Returning the results as an array
    raise NotImplementedError(
        "Cosilico engine integration not yet complete. "
        "Need to implement: load inputs from CPS, run Cosilico calculation, return array."
    )


def run_variable_comparison(
    variable: str,
    year: int = 2024,
    tolerance: float = 1.0,
) -> dict:
    """Run full comparison for a single variable.

    Args:
        variable: Variable name to compare
        year: Tax year
        tolerance: Match tolerance in dollars

    Returns:
        Comparison result dict
    """
    pe_values = load_pe_values(variable, year)
    cosilico_values = load_cosilico_values(variable, year)

    result = compare_records(cosilico_values, pe_values, tolerance=tolerance)
    result["variable"] = variable
    result["year"] = year

    return result


def generate_dashboard_json(results: list[dict], year: int = 2024) -> dict:
    """Generate dashboard JSON from comparison results.

    Args:
        results: List of variable comparison results
        year: Tax year

    Returns:
        Dashboard-formatted dict
    """
    # Overall summary
    total_records = sum(r.get("n_records", 0) for r in results)
    total_matches = sum(r.get("n_records", 0) * r.get("match_rate", 0) for r in results)
    overall_match_rate = total_matches / total_records if total_records > 0 else 0.0

    return {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "tax_year": year,
            "data_source": "CPS ASEC (Enhanced)",
            "comparison": "Cosilico vs PolicyEngine-US",
        },
        "summary": {
            "overall_match_rate": overall_match_rate,
            "total_records": total_records,
            "n_variables": len(results),
        },
        "variables": results,
    }

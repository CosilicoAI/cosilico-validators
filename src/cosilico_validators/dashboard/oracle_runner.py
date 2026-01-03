"""
Year-aware Oracle Runner

Routes validation to appropriate oracle:
- TAXSIM: 2018-2020 (uses statutory values)
- PolicyEngine: 2021+ (uses updated parameters)

TAXSIM is authoritative for historical years because:
1. It uses exact IRS-published values
2. PE may not have historical parameters
3. TAXSIM has been validated against SOI data
"""

import csv
import io
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .schema import YearResult


# Oracle selection thresholds
TAXSIM_YEARS = range(2018, 2021)  # 2018, 2019, 2020
PE_YEARS = range(2021, 2030)       # 2021+


def select_oracle(year: int) -> str:
    """Select appropriate oracle for a given year."""
    if year in TAXSIM_YEARS:
        return "taxsim"
    elif year in PE_YEARS:
        return "policyengine"
    else:
        raise ValueError(f"Year {year} not supported. Use 2018-2029.")


def run_taxsim(
    df: pd.DataFrame,
    year: int,
    variable: str,
) -> YearResult:
    """
    Run validation against TAXSIM for a given year.

    Args:
        df: DataFrame with CPS microdata and RAC calculated values
        year: Tax year
        variable: Variable to validate (e.g., "income_tax_before_credits")

    Returns:
        YearResult with match metrics
    """
    start = time.time()

    # Map variable to TAXSIM output field
    taxsim_var_map = {
        "income_tax_before_credits": "v27",  # fed_tax_before_credits
        "income_tax": "fiitax",
        "eitc": "v25",
        "ctc": "v22",  # Non-refundable CTC
        "taxable_income": "v18",
        "agi": "v10",
    }

    taxsim_field = taxsim_var_map.get(variable)
    if not taxsim_field:
        return YearResult(
            year=year,
            oracle="taxsim",
            match_rate=0.0,
            sample_size=0,
            rac_total=0.0,
            oracle_total=0.0,
            bias_pct=0.0,
            mean_diff=0.0,
            median_diff=0.0,
            max_abs_diff=0.0,
            correlation=0.0,
            discrepancies=[f"Variable {variable} not mapped to TAXSIM"],
        )

    # Build TAXSIM input from CPS data
    taxsim_input = _build_taxsim_csv(df, year)

    # Call TAXSIM API
    taxsim_output = _call_taxsim(taxsim_input)

    if taxsim_output is None:
        duration = int((time.time() - start) * 1000)
        return YearResult(
            year=year,
            oracle="taxsim",
            match_rate=0.0,
            sample_size=0,
            rac_total=0.0,
            oracle_total=0.0,
            bias_pct=0.0,
            mean_diff=0.0,
            median_diff=0.0,
            max_abs_diff=0.0,
            correlation=0.0,
            discrepancies=["TAXSIM API call failed"],
            duration_ms=duration,
        )

    # Parse TAXSIM output and merge
    taxsim_df = _parse_taxsim_output(taxsim_output)

    # Merge with RAC results
    merged = df.merge(taxsim_df, on="taxsimid", how="inner")

    # Extract values
    rac_col = f"rac_{variable}"
    oracle_col = taxsim_field

    if rac_col not in merged.columns:
        rac_col = variable  # Try without prefix

    if rac_col not in merged.columns or oracle_col not in merged.columns:
        duration = int((time.time() - start) * 1000)
        return YearResult(
            year=year,
            oracle="taxsim",
            match_rate=0.0,
            sample_size=len(merged),
            rac_total=0.0,
            oracle_total=0.0,
            bias_pct=0.0,
            mean_diff=0.0,
            median_diff=0.0,
            max_abs_diff=0.0,
            correlation=0.0,
            discrepancies=[f"Column mismatch: {rac_col} or {oracle_col} not found"],
            duration_ms=int((time.time() - start) * 1000),
        )

    rac_vals = merged[rac_col].values
    oracle_vals = merged[oracle_col].values
    weights = merged.get("weight", pd.Series([1] * len(merged))).values

    # Compute metrics
    result = _compute_metrics(rac_vals, oracle_vals, weights, year, "taxsim")
    result.duration_ms = int((time.time() - start) * 1000)
    result.oracle_version = "TAXSIM-35"

    return result


def run_policyengine(
    df: pd.DataFrame,
    year: int,
    variable: str,
) -> YearResult:
    """
    Run validation against PolicyEngine for a given year.

    Args:
        df: DataFrame with CPS microdata and RAC calculated values
        year: Tax year
        variable: Variable to validate

    Returns:
        YearResult with match metrics
    """
    start = time.time()

    try:
        from policyengine_us import Microsimulation
    except ImportError:
        return YearResult(
            year=year,
            oracle="policyengine",
            match_rate=0.0,
            sample_size=0,
            rac_total=0.0,
            oracle_total=0.0,
            bias_pct=0.0,
            mean_diff=0.0,
            median_diff=0.0,
            max_abs_diff=0.0,
            correlation=0.0,
            discrepancies=["PolicyEngine not installed"],
        )

    # Map variable to PE variable name
    pe_var_map = {
        "income_tax_before_credits": "income_tax_before_credits",
        "income_tax": "income_tax",
        "eitc": "eitc",
        "ctc": "ctc",
        "taxable_income": "taxable_income",
        "agi": "adjusted_gross_income",
    }

    pe_var = pe_var_map.get(variable, variable)

    # Run PE microsimulation
    try:
        sim = Microsimulation()
        pe_vals = np.array(sim.calculate(pe_var, year))
        tu_weights = np.array(sim.calculate("tax_unit_weight", year))
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        return YearResult(
            year=year,
            oracle="policyengine",
            match_rate=0.0,
            sample_size=0,
            rac_total=0.0,
            oracle_total=0.0,
            bias_pct=0.0,
            mean_diff=0.0,
            median_diff=0.0,
            max_abs_diff=0.0,
            correlation=0.0,
            discrepancies=[f"PE calculation error: {e}"],
            duration_ms=duration,
        )

    # Get RAC values (assuming they're aligned with PE tax units)
    rac_col = f"rac_{variable}"
    if rac_col not in df.columns:
        rac_col = variable

    if rac_col not in df.columns:
        duration = int((time.time() - start) * 1000)
        return YearResult(
            year=year,
            oracle="policyengine",
            match_rate=0.0,
            sample_size=len(df),
            rac_total=0.0,
            oracle_total=0.0,
            bias_pct=0.0,
            mean_diff=0.0,
            median_diff=0.0,
            max_abs_diff=0.0,
            correlation=0.0,
            discrepancies=[f"RAC column {rac_col} not found"],
            duration_ms=duration,
        )

    rac_vals = df[rac_col].values

    # Ensure arrays are same length
    min_len = min(len(rac_vals), len(pe_vals))
    rac_vals = rac_vals[:min_len]
    pe_vals = pe_vals[:min_len]
    weights = tu_weights[:min_len]

    # Compute metrics
    result = _compute_metrics(rac_vals, pe_vals, weights, year, "policyengine")
    result.duration_ms = int((time.time() - start) * 1000)

    try:
        import policyengine_us
        result.oracle_version = policyengine_us.__version__
    except Exception:
        result.oracle_version = "unknown"

    return result


def _compute_metrics(
    rac_vals: np.ndarray,
    oracle_vals: np.ndarray,
    weights: np.ndarray,
    year: int,
    oracle: str,
    tolerance: float = 1.0,  # $1 tolerance
) -> YearResult:
    """Compute comparison metrics."""
    diff = rac_vals - oracle_vals
    abs_diff = np.abs(diff)

    # Match rate (within tolerance)
    match_rate = (abs_diff <= tolerance).mean()

    # Weighted totals
    rac_total = (rac_vals * weights).sum()
    oracle_total = (oracle_vals * weights).sum()
    bias_pct = (rac_total - oracle_total) / oracle_total * 100 if oracle_total != 0 else 0.0

    # Distribution metrics
    mean_diff = np.mean(diff)
    median_diff = np.median(diff)
    max_abs_diff = np.max(abs_diff)

    # Correlation (for non-zero values)
    mask = (rac_vals != 0) | (oracle_vals != 0)
    if mask.sum() > 10:
        correlation = np.corrcoef(rac_vals[mask], oracle_vals[mask])[0, 1]
    else:
        correlation = 1.0 if match_rate > 0.99 else 0.0

    # Find top discrepancies
    discrepancy_idx = np.argsort(abs_diff)[-10:][::-1]
    discrepancies = []
    for idx in discrepancy_idx:
        if abs_diff[idx] > tolerance:
            discrepancies.append({
                "index": int(idx),
                "rac": float(rac_vals[idx]),
                "oracle": float(oracle_vals[idx]),
                "diff": float(diff[idx]),
            })

    return YearResult(
        year=year,
        oracle=oracle,
        match_rate=float(match_rate),
        sample_size=len(rac_vals),
        rac_total=float(rac_total),
        oracle_total=float(oracle_total),
        bias_pct=float(bias_pct),
        mean_diff=float(mean_diff),
        median_diff=float(median_diff),
        max_abs_diff=float(max_abs_diff),
        correlation=float(correlation) if not np.isnan(correlation) else 0.0,
        discrepancies=discrepancies,
    )


def _build_taxsim_csv(df: pd.DataFrame, year: int) -> str:
    """Build TAXSIM input CSV from CPS DataFrame."""
    output = io.StringIO()
    writer = csv.writer(output)

    # TAXSIM header
    headers = [
        "taxsimid", "year", "state", "mstat", "page", "sage",
        "depx", "age1", "age2", "age3",
        "pwages", "swages", "psemp", "ssemp",
        "dividends", "intrec", "stcg", "ltcg",
        "pensions", "gssi", "pui",
        "proptax", "mortgage", "childcare", "otheritem",
        "idtl",
    ]
    writer.writerow(headers)

    # Map CPS columns to TAXSIM fields
    for idx, row in df.iterrows():
        taxsim_row = [
            idx,  # taxsimid
            year,
            0,  # state (0 = no state calc)
            row.get("mstat", 1),
            row.get("age", 35),
            row.get("spouse_age", 0),
            row.get("num_dependents", 0),
            row.get("dep_age_1", 0),
            row.get("dep_age_2", 0),
            row.get("dep_age_3", 0),
            row.get("wages", 0),
            row.get("spouse_wages", 0),
            row.get("self_employment", 0),
            row.get("spouse_self_employment", 0),
            row.get("dividends", 0),
            row.get("interest", 0),
            row.get("short_term_capital_gains", 0),
            row.get("long_term_capital_gains", 0),
            row.get("pensions", 0),
            row.get("social_security", 0),
            row.get("unemployment", 0),
            row.get("property_tax", 0),
            row.get("mortgage_interest", 0),
            row.get("childcare", 0),
            row.get("other_itemized", 0),
            2,  # Full output
        ]
        writer.writerow(taxsim_row)

    return output.getvalue()


def _call_taxsim(csv_data: str, max_retries: int = 3) -> Optional[str]:
    """Call TAXSIM API with CSV data."""
    url = "https://taxsim.nber.org/taxsim35/redirect.cgi"

    for attempt in range(max_retries):
        try:
            # Write CSV to temp file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
                f.write(csv_data)
                temp_path = f.name

            try:
                result = subprocess.run(
                    ["curl", "-s", "-F", f"txpydata.csv=@{temp_path}", url],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if result.returncode != 0:
                    continue

                # Check for error response
                if "<html" in result.stdout.lower() or "error" in result.stdout.lower()[:100]:
                    continue

                return result.stdout

            finally:
                Path(temp_path).unlink(missing_ok=True)

        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue

    return None


def _parse_taxsim_output(output: str) -> pd.DataFrame:
    """Parse TAXSIM CSV output into DataFrame."""
    try:
        df = pd.read_csv(io.StringIO(output))
        # Clean column names (TAXSIM may have whitespace)
        df.columns = [c.strip() for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def validate_variable(
    df: pd.DataFrame,
    variable: str,
    years: list[int],
) -> list[YearResult]:
    """
    Validate a variable across multiple years using appropriate oracles.

    Args:
        df: DataFrame with CPS microdata and RAC calculated values
        variable: Variable to validate
        years: List of years to validate

    Returns:
        List of YearResult objects
    """
    results = []

    for year in years:
        oracle = select_oracle(year)

        if oracle == "taxsim":
            result = run_taxsim(df, year, variable)
        else:
            result = run_policyengine(df, year, variable)

        results.append(result)

    return results

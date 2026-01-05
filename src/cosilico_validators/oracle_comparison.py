"""
Oracle Comparison Module

Compares PolicyEngine, TAXSIM, and Cosilico RAC values using the variable mapping.
Produces aggregates and accuracy metrics for validation.
"""

import pandas as pd
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class ComparisonResult:
    """Result of comparing two sources for a variable."""
    variable: str
    source_a: str
    source_b: str
    n_records: int
    n_matched: int  # Within tolerance
    match_rate: float
    mean_diff: float
    max_diff: float
    total_a: float
    total_b: float
    aggregate_diff_pct: float


def load_mapping(mapping_path: Optional[Path] = None) -> dict:
    """Load variable mapping from YAML."""
    if mapping_path is None:
        # Use the canonical mapping in comparison/
        mapping_path = Path(__file__).parent / "comparison" / "variable_mappings.yaml"
    with open(mapping_path) as f:
        return yaml.safe_load(f)


def load_pe_oracle(oracle_path: Optional[Path] = None, year: int = 2024) -> pd.DataFrame:
    """Load and aggregate PE oracle to tax unit level."""
    if oracle_path is None:
        oracle_path = Path(__file__).parent.parent.parent / "oracles" / "pe_cps_oracle.parquet"

    pe = pd.read_parquet(oracle_path)
    pe = pe[pe.year == year]

    # Aggregate to tax unit level
    mapping = load_mapping()
    agg_funcs = {}
    for rac_path, var_info in mapping.get("variables", {}).items():
        pe_var = var_info.get("policyengine")
        if pe_var and pe_var in pe.columns:
            # Check if person-level entity
            entity = var_info.get("policyengine_entity", "tax_unit")
            if entity == "person":
                agg_funcs[pe_var] = "sum"
            else:
                agg_funcs[pe_var] = "max"

    tu_pe = pe.groupby("tax_unit_id").agg(agg_funcs).reset_index()
    return tu_pe


def load_taxsim_oracle(oracle_path: Optional[Path] = None, year: int = 2023) -> pd.DataFrame:
    """Load TAXSIM oracle."""
    if oracle_path is None:
        oracle_path = Path(__file__).parent.parent.parent / "oracles" / "taxsim_cps_oracle.parquet"

    taxsim = pd.read_parquet(oracle_path)
    # Filter to specific tax year if column exists
    if "tax_year" in taxsim.columns:
        taxsim = taxsim[taxsim.tax_year == year]
    return taxsim


def compare_sources(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    id_col_a: str,
    id_col_b: str,
    var_a: str,
    var_b: str,
    source_a_name: str = "A",
    source_b_name: str = "B",
    tolerance: float = 10.0,
) -> Optional[ComparisonResult]:
    """Compare a single variable between two sources."""
    if var_a not in df_a.columns or var_b not in df_b.columns:
        return None

    # Merge on ID
    merged = df_a[[id_col_a, var_a]].merge(
        df_b[[id_col_b, var_b]],
        left_on=id_col_a,
        right_on=id_col_b,
        how="inner"
    )

    if len(merged) == 0:
        return None

    # Calculate differences
    merged["diff"] = (merged[var_a] - merged[var_b]).abs()
    merged["matched"] = merged["diff"] <= tolerance

    n_records = len(merged)
    n_matched = merged["matched"].sum()
    match_rate = n_matched / n_records if n_records > 0 else 0

    total_a = merged[var_a].sum()
    total_b = merged[var_b].sum()
    agg_diff_pct = (total_a - total_b) / total_b * 100 if total_b != 0 else 0

    return ComparisonResult(
        variable=var_a,
        source_a=source_a_name,
        source_b=source_b_name,
        n_records=n_records,
        n_matched=n_matched,
        match_rate=match_rate,
        mean_diff=merged["diff"].mean(),
        max_diff=merged["diff"].max(),
        total_a=total_a,
        total_b=total_b,
        aggregate_diff_pct=agg_diff_pct,
    )


def compare_pe_taxsim(
    pe_year: int = 2024,
    taxsim_year: int = 2023,
    tolerance: float = 10.0,
) -> list[ComparisonResult]:
    """Compare all mapped variables between PE and TAXSIM."""
    mapping = load_mapping()

    pe = load_pe_oracle(year=pe_year)
    taxsim = load_taxsim_oracle(year=taxsim_year)

    results = []
    for rac_path, var_info in mapping.get("variables", {}).items():
        pe_var = var_info.get("policyengine")
        taxsim_var = var_info.get("taxsim")

        if not pe_var or not taxsim_var:
            continue  # Skip if not mapped in both

        result = compare_sources(
            df_a=pe,
            df_b=taxsim,
            id_col_a="tax_unit_id",
            id_col_b="taxsimid",
            var_a=pe_var,
            var_b=taxsim_var,
            source_a_name="PolicyEngine",
            source_b_name="TAXSIM",
            tolerance=tolerance,
        )

        if result:
            # Use RAC path as variable name for clarity
            result.variable = rac_path
            results.append(result)

    return results


def compute_overall_accuracy(results: list[ComparisonResult]) -> dict:
    """Compute overall accuracy metrics from comparison results."""
    if not results:
        return {"overall_match_rate": 0, "n_variables": 0}

    total_records = sum(r.n_records for r in results)
    total_matched = sum(r.n_matched for r in results)
    overall_match_rate = total_matched / total_records if total_records > 0 else 0

    return {
        "overall_match_rate": overall_match_rate,
        "n_variables": len(results),
        "total_records": total_records,
        "total_matched": total_matched,
        "by_variable": {r.variable: r.match_rate for r in results},
    }


def print_comparison_report(results: list[ComparisonResult]) -> None:
    """Print a formatted comparison report."""
    print("=" * 70)
    print("ORACLE COMPARISON REPORT")
    print("=" * 70)

    if not results:
        print("No comparable variables found.")
        return

    # Header
    print(f"{'Variable':<30} {'Match Rate':>12} {'Mean Diff':>12} {'Agg Diff %':>12}")
    print("-" * 70)

    for r in sorted(results, key=lambda x: x.match_rate):
        print(f"{r.variable:<30} {r.match_rate:>11.1%} ${r.mean_diff:>10,.0f} {r.aggregate_diff_pct:>11.1f}%")

    print("-" * 70)

    # Overall
    accuracy = compute_overall_accuracy(results)
    print(f"{'OVERALL':<30} {accuracy['overall_match_rate']:>11.1%}")
    print(f"\nVariables compared: {accuracy['n_variables']}")
    print(f"Total record-variable pairs: {accuracy['total_records']:,}")


if __name__ == "__main__":
    # Run comparison
    results = compare_pe_taxsim(pe_year=2024, taxsim_year=2023)
    print_comparison_report(results)

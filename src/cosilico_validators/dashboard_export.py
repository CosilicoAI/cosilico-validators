"""Export validation results to cosilico.ai dashboard format.

Usage:
    python -m cosilico_validators.dashboard_export -o validation-results.json
    cp validation-results.json /path/to/cosilico.ai/public/data/

################################################################################
#                                                                              #
#   ██████  ██████  ██ ████████ ██  ██████  █████  ██                          #
#  ██      ██   ██  ██    ██    ██ ██      ██   ██ ██                          #
#  ██      ██████   ██    ██    ██ ██      ███████ ██                          #
#  ██      ██   ██  ██    ██    ██ ██      ██   ██ ██                          #
#   ██████ ██   ██  ██    ██    ██  ██████ ██   ██ ███████                     #
#                                                                              #
#   THIS FILE IS A VALIDATOR ONLY - NO TAX RULES ALLOWED HERE!                 #
#                                                                              #
#   ALL TAX CALCULATION LOGIC MUST COME FROM:                                  #
#     - cosilico-us/*.rac files (statute encodings)                            #
#     - cosilico-engine (DSL executor)                                         #
#                                                                              #
#   This validator ONLY:                                                       #
#     1. Loads outputs from Cosilico engine                                    #
#     2. Loads outputs from external validators (PE, TAXSIM, etc)              #
#     3. Compares them                                                         #
#                                                                              #
#   DO NOT ADD:                                                                #
#     - Filing status logic                                                    #
#     - Age-based calculations                                                 #
#     - Income aggregations                                                    #
#     - ANY tax rule implementations                                           #
#                                                                              #
#   If validation fails, FIX THE .RAC FILES, not this validator!               #
#                                                                              #
################################################################################
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Any

import click
import numpy as np

from cosilico_validators.comparison.aligned import (
    load_common_dataset,
    compare_variable,
    ComparisonResult,
)


# All PE tax variables we want to track, with section metadata
# Keys must match PolicyEngine variable names exactly
# Cosilico implementation is optional - unimplemented returns 0
VARIABLES = {
    "eitc": {"section": "26/32", "title": "Earned Income Tax Credit", "implemented": True},
    "income_tax_before_credits": {"section": "26/1", "title": "Income Tax (Before Credits)", "implemented": True},
    "ctc": {"section": "26/24", "title": "Child Tax Credit (Total)", "implemented": True},
    "non_refundable_ctc": {"section": "26/24", "title": "Child Tax Credit (Non-refundable)", "implemented": True},
    "refundable_ctc": {"section": "26/24", "title": "Additional Child Tax Credit", "implemented": True},
    "standard_deduction": {"section": "26/63", "title": "Standard Deduction", "implemented": True},
    "adjusted_gross_income": {"section": "26/62", "title": "Adjusted Gross Income", "implemented": False},
    "taxable_income": {"section": "26/63", "title": "Taxable Income", "implemented": False},
    "cdcc": {"section": "26/21", "title": "Child & Dependent Care Credit", "implemented": False},
    "salt_deduction": {"section": "26/164", "title": "SALT Deduction", "implemented": False},
    "alternative_minimum_tax": {"section": "26/55", "title": "Alternative Minimum Tax", "implemented": False},
    "premium_tax_credit": {"section": "26/36B", "title": "Premium Tax Credit", "implemented": False},
    "net_investment_income_tax": {"section": "26/1411", "title": "Net Investment Income Tax", "implemented": True},
}


def get_git_commit() -> str:
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def result_to_section(result: ComparisonResult, n_households: int, meta: dict) -> dict:
    """Convert ComparisonResult to ValidationSection format."""
    return {
        "section": meta["section"],
        "title": meta["title"],
        "variable": result.variable,
        "implemented": meta["implemented"],
        "households": n_households,
        "testCases": [],
        "summary": {
            "total": result.n_records,
            "matches": int(result.match_rate * result.n_records),
            "matchRate": result.match_rate,
            "meanAbsoluteError": result.mean_absolute_error,
        },
        "validatorBreakdown": {
            "policyengine": {
                "matches": int(result.match_rate * result.n_records),
                "total": result.n_records,
                "rate": result.match_rate,
            }
        },
        "notes": (
            f"Cosilico total: ${result.cosilico_total/1e9:.1f}B, "
            f"PE total: ${result.policyengine_total/1e9:.1f}B, "
            f"Diff: ${(result.cosilico_total - result.policyengine_total)/1e9:+.1f}B"
        ) if meta["implemented"] else "Not yet implemented - returns 0",
    }


def run_export(year: int = 2024, output_path: Optional[Path] = None) -> dict:
    """Run validation and export to dashboard format."""
    from policyengine_us import Microsimulation
    import sys
    import pandas as pd

    # Load common dataset
    print("Loading common dataset from PolicyEngine...")
    dataset = load_common_dataset(year)
    print(f"  {dataset.n_records:,} tax units loaded")

    # Load Cosilico implementations
    data_sources_path = Path.home() / "CosilicoAI" / "cosilico-data-sources" / "micro" / "us"
    sys.path.insert(0, str(data_sources_path))
    from cosilico_runner import (
        PARAMS_2024,
        calculate_eitc,
        calculate_income_tax,
        calculate_standard_deduction,
        calculate_ctc,
        calculate_niit,
    )

    # Get PE microsimulation
    print("Loading PolicyEngine calculations...")
    sim = Microsimulation()

    # Build Cosilico functions - returns 0 for unimplemented
    def make_cosilico_func(var_name: str, meta: dict) -> Callable:
        if not meta["implemented"]:
            return lambda ds: np.zeros(ds.n_records)

        if var_name == "eitc":
            def func(ds):
                df = pd.DataFrame({
                    "earned_income": ds.earned_income,
                    "adjusted_gross_income": ds.adjusted_gross_income,
                    "num_eitc_children": np.clip(ds.eitc_child_count, 0, 3),
                    "is_joint": ds.is_joint,
                    "investment_income": ds.investment_income,
                })
                return calculate_eitc(df, PARAMS_2024)
            return func

        elif var_name == "income_tax_before_credits":
            def func(ds):
                df = pd.DataFrame({
                    "taxable_income": ds.taxable_income,
                    "is_joint": ds.is_joint,
                })
                return calculate_income_tax(df, PARAMS_2024)
            return func

        elif var_name == "standard_deduction":
            def func(ds):
                # filing_status is a string enum: SINGLE, JOINT, SEPARATE, HEAD_OF_HOUSEHOLD, WIDOW
                filing_status = sim.calculate("filing_status", year)
                age_head = np.array(sim.calculate("age_head", year))
                age_spouse = np.array(sim.calculate("age_spouse", year))
                is_joint = np.array([str(fs) == "JOINT" for fs in filing_status])
                is_hoh = np.array([str(fs) == "HEAD_OF_HOUSEHOLD" for fs in filing_status])
                df = pd.DataFrame({
                    "is_joint": is_joint,
                    "is_head_of_household": is_hoh,
                    "age_head": age_head,
                    "age_spouse": age_spouse,
                    "is_blind_head": np.zeros(ds.n_records, dtype=bool),
                    "is_blind_spouse": np.zeros(ds.n_records, dtype=bool),
                    "is_dependent": np.zeros(ds.n_records, dtype=bool),
                    "earned_income": ds.earned_income,
                })
                return calculate_standard_deduction(df, PARAMS_2024)
            return func

        elif var_name in ("ctc", "non_refundable_ctc"):
            def func(ds):
                ctc_child_count = np.array(sim.calculate("ctc_qualifying_children", year))
                # Other dependents not in ctc_qualifying_children
                other_dep = np.zeros(ds.n_records)
                df = pd.DataFrame({
                    "num_ctc_children": ctc_child_count,
                    "num_other_dependents": other_dep,
                    "is_joint": ds.is_joint,
                    "adjusted_gross_income": ds.adjusted_gross_income,
                    "earned_income": ds.earned_income,
                })
                nonref, refund = calculate_ctc(df, PARAMS_2024)
                return nonref + refund if var_name == "ctc" else nonref
            return func

        elif var_name == "refundable_ctc":
            def func(ds):
                ctc_child_count = np.array(sim.calculate("ctc_qualifying_children", year))
                other_dep = np.zeros(ds.n_records)
                df = pd.DataFrame({
                    "num_ctc_children": ctc_child_count,
                    "num_other_dependents": other_dep,
                    "is_joint": ds.is_joint,
                    "adjusted_gross_income": ds.adjusted_gross_income,
                    "earned_income": ds.earned_income,
                })
                _, refund = calculate_ctc(df, PARAMS_2024)
                return refund
            return func

        elif var_name == "net_investment_income_tax":
            def func(ds):
                df = pd.DataFrame({
                    "is_joint": ds.is_joint,
                    "adjusted_gross_income": ds.adjusted_gross_income,
                    "investment_income": ds.investment_income,
                })
                return calculate_niit(df, PARAMS_2024)
            return func

        else:
            # Implemented but no function yet - return zeros
            return lambda ds: np.zeros(ds.n_records)

    # Run comparisons for all variables
    results = []
    for var_name, meta in VARIABLES.items():
        print(f"Comparing {var_name}...")
        try:
            pe_values = np.array(sim.calculate(var_name, year))
            cos_func = make_cosilico_func(var_name, meta)
            result = compare_variable(dataset, cos_func, pe_values, var_name)
            results.append((result, meta))
            status = "✓" if meta["implemented"] else "○ (stub)"
            print(f"  {status} Match rate: {result.match_rate*100:.1f}%")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            continue

    # Build ValidationResults structure
    sections = [result_to_section(r, dataset.n_records, meta) for r, meta in results]

    # Separate implemented vs stub for overall calculation
    implemented_results = [r for r, m in results if m["implemented"]]
    if implemented_results:
        overall_match_rate = np.mean([r.match_rate for r in implemented_results])
        overall_mae = np.mean([r.mean_absolute_error for r in implemented_results])
    else:
        overall_match_rate = 0.0
        overall_mae = 0.0

    n_implemented = sum(1 for _, m in results if m["implemented"])
    n_total = len(results)

    dashboard_data = {
        "isSampleData": False,
        "timestamp": datetime.now().isoformat(),
        "commit": get_git_commit(),
        "dataSource": f"PolicyEngine Enhanced CPS {year}",
        "householdsTotal": dataset.n_records,
        "sections": sections,
        "coverage": {
            "implemented": n_implemented,
            "total": n_total,
            "percentage": n_implemented / n_total if n_total > 0 else 0,
        },
        "overall": {
            "totalHouseholds": dataset.n_records,
            "totalTests": sum(r.n_records for r, _ in results),
            "totalMatches": sum(int(r.match_rate * r.n_records) for r, _ in results if _["implemented"]),
            "matchRate": overall_match_rate,
            "meanAbsoluteError": overall_mae,
        },
        "validators": [
            {
                "name": "PolicyEngine",
                "available": True,
                "version": "1.150.0",
                "householdsCovered": dataset.n_records,
            },
            {
                "name": "TAXSIM",
                "available": False,
                "version": "35",
                "householdsCovered": 0,
            },
        ],
    }

    # Write to file if path provided
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(dashboard_data, f, indent=2)
        print(f"\nWritten to {output_path}")

    return dashboard_data


@click.command()
@click.option("--year", "-y", default=2024, help="Tax year")
@click.option("--output", "-o", type=click.Path(), help="Output JSON file")
def main(year: int, output: Optional[str]):
    """Export validation results to dashboard format."""
    output_path = Path(output) if output else None
    data = run_export(year, output_path)

    print("\n=== Summary ===")
    print(f"Coverage: {data['coverage']['implemented']}/{data['coverage']['total']} variables implemented")
    print(f"Match rate (implemented): {data['overall']['matchRate']*100:.1f}%")
    print(f"MAE: ${data['overall']['meanAbsoluteError']:.2f}")


if __name__ == "__main__":
    main()

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
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
import numpy as np

from cosilico_validators.comparison.aligned import (
    load_common_dataset,
    compare_variable,
    ComparisonResult,
)


# Variables to validate - keys are PolicyEngine variable names
# Section references the USC statute where the rule is encoded
VARIABLES = {
    "eitc": {"section": "26/32", "title": "Earned Income Tax Credit"},
    "income_tax_before_credits": {"section": "26/1", "title": "Income Tax (Before Credits)"},
    "ctc": {"section": "26/24", "title": "Child Tax Credit (Total)"},
    "non_refundable_ctc": {"section": "26/24", "title": "Child Tax Credit (Non-refundable)"},
    "refundable_ctc": {"section": "26/24", "title": "Additional Child Tax Credit"},
    "standard_deduction": {"section": "26/63", "title": "Standard Deduction"},
    "adjusted_gross_income": {"section": "26/62", "title": "Adjusted Gross Income"},
    "taxable_income": {"section": "26/63", "title": "Taxable Income"},
    "cdcc": {"section": "26/21", "title": "Child & Dependent Care Credit"},
    "salt_deduction": {"section": "26/164", "title": "SALT Deduction"},
    "alternative_minimum_tax": {"section": "26/55", "title": "Alternative Minimum Tax"},
    "premium_tax_credit": {"section": "26/36B", "title": "Premium Tax Credit"},
    "net_investment_income_tax": {"section": "26/1411", "title": "Net Investment Income Tax"},
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


def load_cosilico_engine():
    """Load the Cosilico engine from cosilico-engine repo."""
    engine_path = Path.home() / "CosilicoAI" / "cosilico-engine" / "src"
    if engine_path.exists():
        sys.path.insert(0, str(engine_path))

    from cosilico.vectorized_executor import VectorizedExecutor
    from cosilico.dsl_parser import Parser
    return VectorizedExecutor, Parser


def load_rac_file(section: str) -> Optional[str]:
    """Load .rac file for a given section from cosilico-us.

    Args:
        section: USC section like "26/32" or "26/63"

    Returns:
        Contents of the .rac file, or None if not found
    """
    statute_dir = Path.home() / "CosilicoAI" / "cosilico-us" / "statute"

    # Try direct path first (e.g., statute/26/32.rac)
    rac_path = statute_dir / f"{section}.rac"
    if rac_path.exists():
        return rac_path.read_text()

    # Try with /a suffix (common pattern)
    rac_path = statute_dir / section / "a.rac"
    if rac_path.exists():
        return rac_path.read_text()

    return None


def result_to_section(result: ComparisonResult, n_households: int, meta: dict, implemented: bool) -> dict:
    """Convert ComparisonResult to ValidationSection format."""
    return {
        "section": meta["section"],
        "title": meta["title"],
        "variable": result.variable,
        "implemented": implemented,
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
        ) if implemented else "Not yet implemented in .rac files",
    }


def run_export(year: int = 2024, output_path: Optional[Path] = None) -> dict:
    """Run validation and export to dashboard format.

    This function:
    1. Loads the Cosilico engine
    2. For each variable, loads the .rac file and executes it
    3. Compares against PolicyEngine outputs
    4. Returns dashboard-formatted results
    """
    from policyengine_us import Microsimulation

    # Load common dataset
    print("Loading common dataset from PolicyEngine...")
    dataset = load_common_dataset(year)
    print(f"  {dataset.n_records:,} tax units loaded")

    # Load Cosilico engine
    print("Loading Cosilico engine...")
    try:
        VectorizedExecutor, Parser = load_cosilico_engine()
        engine_available = True
    except ImportError as e:
        print(f"  Warning: Could not load engine: {e}")
        engine_available = False

    # Get PE microsimulation
    print("Loading PolicyEngine calculations...")
    sim = Microsimulation()

    # Run comparisons for all variables
    results = []
    for var_name, meta in VARIABLES.items():
        print(f"Comparing {var_name}...")

        try:
            # Get PolicyEngine values
            pe_values = np.array(sim.calculate(var_name, year))

            # Try to load and execute .rac file
            rac_code = load_rac_file(meta["section"])
            implemented = rac_code is not None and engine_available

            if implemented:
                # TODO: Execute .rac file through engine
                # For now, mark as not implemented until engine integration complete
                # executor = VectorizedExecutor(...)
                # cos_values = executor.execute(rac_code, inputs)
                implemented = False  # Engine integration pending

            if not implemented:
                # Return zeros for unimplemented variables
                cos_func = lambda ds: np.zeros(ds.n_records)
            else:
                cos_func = lambda ds: cos_values  # From engine execution

            result = compare_variable(dataset, cos_func, pe_values, var_name)
            results.append((result, meta, implemented))

            status = "✓" if implemented else "○ (not in engine yet)"
            print(f"  {status} Match rate: {result.match_rate*100:.1f}%")

        except Exception as e:
            print(f"  ✗ Error: {e}")
            continue

    # Build ValidationResults structure
    sections = [result_to_section(r, dataset.n_records, meta, impl) for r, meta, impl in results]

    # Separate implemented vs stub for overall calculation
    implemented_results = [r for r, m, impl in results if impl]
    if implemented_results:
        overall_match_rate = np.mean([r.match_rate for r in implemented_results])
        overall_mae = np.mean([r.mean_absolute_error for r in implemented_results])
    else:
        overall_match_rate = 0.0
        overall_mae = 0.0

    n_implemented = sum(1 for _, _, impl in results if impl)
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
            "totalTests": sum(r.n_records for r, _, _ in results),
            "totalMatches": sum(int(r.match_rate * r.n_records) for r, _, impl in results if impl),
            "matchRate": overall_match_rate,
            "meanAbsoluteError": overall_mae,
        },
        "validators": [
            {
                "name": "PolicyEngine",
                "available": True,
                "version": "latest",
                "householdsCovered": dataset.n_records,
            },
            {
                "name": "TAXSIM",
                "available": False,
                "version": "35",
                "householdsCovered": 0,
            },
            {
                "name": "Tax-Calculator",
                "available": False,
                "version": "latest",
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
    print(f"Coverage: {data['coverage']['implemented']}/{data['coverage']['total']} variables via engine")
    print(f"Match rate (implemented): {data['overall']['matchRate']*100:.1f}%")
    print(f"MAE: ${data['overall']['meanAbsoluteError']:.2f}")
    print("\nNote: Variables show 0% until .rac→engine integration is complete")


if __name__ == "__main__":
    main()

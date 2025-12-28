"""Export validation results to cosilico.ai dashboard format.

Usage:
    python -m cosilico_validators.dashboard_export -o validation-results.json
    cp validation-results.json /path/to/cosilico.ai/public/data/
"""

import json
import subprocess
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


# Section metadata for each variable
SECTION_METADATA = {
    "eitc": {
        "section": "26/32",
        "title": "Earned Income Tax Credit",
    },
    "income_tax_before_credits": {
        "section": "26/1",
        "title": "Income Tax (Before Credits)",
    },
    "income_tax": {
        "section": "26/1",
        "title": "Net Income Tax",
    },
    "ctc": {
        "section": "26/24",
        "title": "Child Tax Credit",
    },
    "standard_deduction": {
        "section": "26/63",
        "title": "Standard Deduction",
    },
    "adjusted_gross_income": {
        "section": "26/62",
        "title": "Adjusted Gross Income",
    },
    "taxable_income": {
        "section": "26/63",
        "title": "Taxable Income",
    },
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


def result_to_section(result: ComparisonResult, n_households: int) -> dict:
    """Convert ComparisonResult to ValidationSection format."""
    meta = SECTION_METADATA.get(result.variable, {
        "section": "unknown",
        "title": result.variable.replace("_", " ").title(),
    })

    return {
        "section": meta["section"],
        "title": meta["title"],
        "variable": result.variable,
        "households": n_households,
        "testCases": [],  # We don't store individual test cases
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
        ),
    }


def run_export(year: int = 2024, output_path: Optional[Path] = None) -> dict:
    """Run validation and export to dashboard format.

    Returns ValidationResults structure matching cosilico.ai/src/types/validation.ts
    """
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
    from cosilico_runner import PARAMS_2024, calculate_eitc, calculate_income_tax

    # Get PE values
    print("Loading PolicyEngine calculations...")
    sim = Microsimulation()
    pe_eitc = np.array(sim.calculate("eitc", year))
    pe_income_tax = np.array(sim.calculate("income_tax_before_credits", year))

    # Define Cosilico functions
    def cos_eitc(ds):
        df = pd.DataFrame({
            "earned_income": ds.earned_income,
            "adjusted_gross_income": ds.adjusted_gross_income,
            "num_eitc_children": np.clip(ds.eitc_child_count, 0, 3),
            "is_joint": ds.is_joint,
            "investment_income": ds.investment_income,
        })
        return calculate_eitc(df, PARAMS_2024)

    def cos_income_tax(ds):
        df = pd.DataFrame({
            "taxable_income": ds.taxable_income,
            "is_joint": ds.is_joint,
        })
        return calculate_income_tax(df, PARAMS_2024)

    # Run comparisons
    results = []

    print("\nComparing EITC...")
    eitc_result = compare_variable(dataset, cos_eitc, pe_eitc, "eitc")
    results.append(eitc_result)
    print(f"  Match rate: {eitc_result.match_rate*100:.1f}%")

    print("Comparing Income Tax...")
    tax_result = compare_variable(dataset, cos_income_tax, pe_income_tax, "income_tax_before_credits")
    results.append(tax_result)
    print(f"  Match rate: {tax_result.match_rate*100:.1f}%")

    # Build ValidationResults structure
    sections = [result_to_section(r, dataset.n_records) for r in results]

    overall_match_rate = np.mean([r.match_rate for r in results])
    overall_mae = np.mean([r.mean_absolute_error for r in results])

    dashboard_data = {
        "isSampleData": False,
        "timestamp": datetime.now().isoformat(),
        "commit": get_git_commit(),
        "dataSource": f"PolicyEngine Enhanced CPS {year}",
        "householdsTotal": dataset.n_records,
        "sections": sections,
        "overall": {
            "totalHouseholds": dataset.n_records,
            "totalTests": sum(r.n_records for r in results),
            "totalMatches": sum(int(r.match_rate * r.n_records) for r in results),
            "matchRate": overall_match_rate,
            "meanAbsoluteError": overall_mae,
        },
        "validators": [
            {
                "name": "PolicyEngine",
                "available": True,
                "version": "1.150.0",  # TODO: Get dynamically
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
    print(f"Variables: {len(data['sections'])}")
    print(f"Match rate: {data['overall']['matchRate']*100:.1f}%")
    print(f"MAE: ${data['overall']['meanAbsoluteError']:.2f}")


if __name__ == "__main__":
    main()

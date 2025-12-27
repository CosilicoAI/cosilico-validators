"""Aggregate income tax validation harness implementation.

Computes total federal individual income tax across CPS and compares:
- PolicyEngine-US
- TAXSIM 35
- Cosilico (when available)

Outputs JSON for the cosilico.ai/validation dashboard.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np

# Conditional imports for optional dependencies
try:
    from policyengine_us import Microsimulation

    HAS_POLICYENGINE = True
except ImportError:
    HAS_POLICYENGINE = False
    Microsimulation = None


@dataclass
class VariableConfig:
    """Configuration for a variable to aggregate."""

    name: str
    entity: str  # "tax_unit", "household", "person", "spm_unit"
    weight_var: str  # Which weight variable to use
    label: str
    in_billions: bool = True  # Display in billions


# Variable mapping table - defines entity level and appropriate weights
AGGREGATE_VARIABLES = [
    VariableConfig("income_tax", "tax_unit", "tax_unit_weight", "Federal Income Tax"),
    VariableConfig("income_tax_before_credits", "tax_unit", "tax_unit_weight", "Income Tax Before Credits"),
    VariableConfig("adjusted_gross_income", "tax_unit", "tax_unit_weight", "Adjusted Gross Income"),
    VariableConfig("eitc", "tax_unit", "tax_unit_weight", "EITC"),
    VariableConfig("ctc", "tax_unit", "tax_unit_weight", "Child Tax Credit"),
    VariableConfig("snap", "spm_unit", "spm_unit_weight", "SNAP Benefits"),
    VariableConfig("ssi", "person", "person_weight", "SSI"),
]


def compute_weighted_total(sim: Any, var_name: str, weight_name: str, year: int) -> float:
    """Compute weighted total for a variable.

    Args:
        sim: PolicyEngine Microsimulation
        var_name: Variable name to aggregate
        weight_name: Weight variable name
        year: Tax year

    Returns:
        Weighted total as float
    """
    values = np.array(sim.calculate(var_name, year))
    weights = np.array(sim.calculate(weight_name, year))
    return float(np.sum(values * weights))


def compute_policyengine_aggregates(
    sim: Any,
    year: int = 2024,
    variables: list[VariableConfig] | None = None,
) -> dict:
    """Compute federal income tax aggregates using PolicyEngine.

    Args:
        sim: PolicyEngine Microsimulation instance
        year: Tax year
        variables: List of variables to aggregate (defaults to AGGREGATE_VARIABLES)

    Returns:
        Dict with source info and aggregate values
    """
    if variables is None:
        variables = AGGREGATE_VARIABLES

    start = time.time()

    aggregates = {}
    for var_config in variables:
        try:
            total = compute_weighted_total(
                sim, var_config.name, var_config.weight_var, year
            )
            aggregates[f"total_{var_config.name}"] = total
        except Exception as e:
            # Variable might not exist or have errors
            aggregates[f"total_{var_config.name}"] = None
            aggregates[f"error_{var_config.name}"] = str(e)

    elapsed = time.time() - start

    # Population totals (sum of weights = total population)
    household_weights = np.array(sim.calculate("household_weight", year))
    aggregates["total_population"] = float(np.sum(household_weights))

    # Tax units with positive tax
    income_tax = np.array(sim.calculate("income_tax", year))
    tax_unit_weights = np.array(sim.calculate("tax_unit_weight", year))
    aggregates["tax_units_with_positive_tax"] = float(
        np.sum(tax_unit_weights[income_tax > 0])
    )

    # Compute per-capita metrics
    total_pop = aggregates.get("total_population", 1)
    total_income_tax = aggregates.get("total_income_tax", 0)
    total_agi = aggregates.get("total_adjusted_gross_income", 0)

    return {
        "source": "PolicyEngine-US",
        "version": "latest",
        "computation_time_seconds": elapsed,
        "aggregates": aggregates,
        "per_capita": {
            "mean_income_tax": (total_income_tax / total_pop) if total_pop and total_income_tax else 0,
            "mean_agi": (total_agi / total_pop) if total_pop and total_agi else 0,
        },
    }


def compute_taxsim_aggregates(
    sim: Any,
    year: int = 2024,
    sample_size: int = 1000,
) -> Optional[dict]:
    """Compute federal income tax using TAXSIM on a sample.

    TAXSIM has API rate limits, so we sample and extrapolate.

    Args:
        sim: PolicyEngine Microsimulation instance (for input data)
        year: Tax year
        sample_size: Number of records to sample

    Returns:
        Dict with TAXSIM results or None if unavailable
    """
    # TODO: Implement TAXSIM API integration
    # For now, return placeholder
    return {
        "source": "TAXSIM-35",
        "version": "35",
        "sample_size": sample_size,
        "note": "Not yet implemented - requires TAXSIM API integration",
        "aggregates": {
            "total_income_tax": None,
        },
    }


def compute_cosilico_aggregates(
    sim: Any,
    year: int = 2024,
) -> Optional[dict]:
    """Compute federal income tax using Cosilico engine.

    Args:
        sim: PolicyEngine Microsimulation instance (for input data)
        year: Tax year

    Returns:
        Dict with Cosilico results or None if engine unavailable
    """
    # TODO: Integrate cosilico-engine when ready
    try:
        # from cosilico_engine import execute_statute
        raise ImportError("Cosilico engine not yet integrated")
    except ImportError:
        return None


def generate_comparison_report(
    pe_results: dict,
    taxsim_results: Optional[dict],
    cosilico_results: Optional[dict],
    year: int = 2024,
) -> dict:
    """Generate comparison report for dashboard.

    Args:
        pe_results: PolicyEngine aggregate results
        taxsim_results: TAXSIM aggregate results (optional)
        cosilico_results: Cosilico aggregate results (optional)
        year: Tax year

    Returns:
        Dict formatted for cosilico.ai/validation dashboard
    """
    report = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "tax_year": year,
            "data_source": "CPS ASEC (Enhanced)",
        },
        "sources": {
            "policyengine": pe_results,
        },
        "comparison": {
            "baseline": "PolicyEngine-US",
            "comparisons": [],
        },
        "summary": {
            "pe_total_income_tax_billions": pe_results["aggregates"].get("total_income_tax", 0) / 1e9,
            "pe_total_agi_trillions": pe_results["aggregates"].get("total_adjusted_gross_income", 0) / 1e12,
        },
    }

    if taxsim_results:
        report["sources"]["taxsim"] = taxsim_results
        if taxsim_results["aggregates"].get("total_income_tax"):
            pe_tax = pe_results["aggregates"]["total_income_tax"]
            taxsim_tax = taxsim_results["aggregates"]["total_income_tax"]
            diff = taxsim_tax - pe_tax
            pct_diff = (diff / pe_tax * 100) if pe_tax else 0
            report["comparison"]["comparisons"].append({
                "source": "TAXSIM-35",
                "difference_billions": diff / 1e9,
                "percent_difference": pct_diff,
            })

    if cosilico_results:
        report["sources"]["cosilico"] = cosilico_results
        if cosilico_results["aggregates"].get("total_income_tax"):
            pe_tax = pe_results["aggregates"]["total_income_tax"]
            cosilico_tax = cosilico_results["aggregates"]["total_income_tax"]
            diff = cosilico_tax - pe_tax
            pct_diff = (diff / pe_tax * 100) if pe_tax else 0
            report["comparison"]["comparisons"].append({
                "source": "Cosilico",
                "difference_billions": diff / 1e9,
                "percent_difference": pct_diff,
            })

    return report


def run_aggregate_validation(
    year: int = 2024,
    use_sample: bool = False,
    sample_size: int = 1000,
    output_path: Optional[Path] = None,
) -> dict:
    """Run full aggregate validation pipeline.

    Args:
        year: Tax year
        use_sample: Whether to use sampled data (faster, for testing)
        sample_size: Sample size if using sample
        output_path: Path to save JSON output

    Returns:
        Comparison report dict
    """
    if not HAS_POLICYENGINE:
        raise ImportError(
            "policyengine_us not installed. Run: pip install policyengine-us"
        )

    print("=" * 70)
    print("Aggregate Income Tax Validation Harness")
    print("=" * 70)

    # Load CPS (uses default enhanced CPS dataset)
    print(f"Loading CPS data for {year}...")
    start = time.time()
    sim = Microsimulation()
    print(f"  Loaded in {time.time() - start:.1f}s")

    # Compute aggregates from each source
    print("Computing PolicyEngine aggregates...")
    pe_results = compute_policyengine_aggregates(sim, year)

    print("Computing TAXSIM aggregates (sample)...")
    taxsim_results = compute_taxsim_aggregates(sim, year, sample_size=sample_size)

    print("Computing Cosilico aggregates...")
    cosilico_results = compute_cosilico_aggregates(sim, year)

    # Generate comparison report
    report = generate_comparison_report(
        pe_results, taxsim_results, cosilico_results, year
    )

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    agg = pe_results["aggregates"]
    print(f"\nPolicyEngine Total Income Tax: ${agg.get('total_income_tax', 0)/1e9:.1f}B")
    print(f"PolicyEngine Total AGI: ${agg.get('total_adjusted_gross_income', 0)/1e12:.2f}T")
    print(f"PolicyEngine Total EITC: ${agg.get('total_eitc', 0)/1e9:.1f}B")
    print(f"PolicyEngine Total CTC: ${agg.get('total_ctc', 0)/1e9:.1f}B")
    print(f"Population: {agg.get('total_population', 0)/1e6:.1f}M")

    # Save output
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nResults saved to: {output_path}")

    return report


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run aggregate income tax validation"
    )
    parser.add_argument("--year", type=int, default=2024, help="Tax year")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path",
    )
    args = parser.parse_args()

    report = run_aggregate_validation(year=args.year, output_path=args.output)
    return report


if __name__ == "__main__":
    main()

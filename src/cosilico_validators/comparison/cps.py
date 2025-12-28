"""CPS microdata comparison between Cosilico and external validators.

Compares weighted totals from Cosilico's CPS calculations against
PolicyEngine, TAXSIM, and other validators.
"""

import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

# Variables to compare - maps Cosilico column names to PolicyEngine variable names
# pe_entity specifies the entity level for aggregation (tax_unit is default)
COMPARISON_VARIABLES = {
    "eitc": {"cosilico_col": "cos_eitc", "pe_var": "eitc", "title": "Earned Income Tax Credit"},
    "ctc": {"cosilico_col": "cos_ctc_total", "pe_var": "ctc", "title": "Child Tax Credit"},
    "ctc_refundable": {"cosilico_col": "cos_ctc_ref", "pe_var": "refundable_ctc", "title": "Additional Child Tax Credit"},
    "income_tax": {"cosilico_col": "cos_income_tax", "pe_var": "income_tax_before_credits", "title": "Income Tax (Before Credits)"},
    "se_tax": {"cosilico_col": "cos_se_tax", "pe_var": "self_employment_tax", "pe_entity": "person", "title": "Self-Employment Tax"},
    "niit": {"cosilico_col": "cos_niit", "pe_var": "net_investment_income_tax", "title": "Net Investment Income Tax"},
}


@dataclass
class ComparisonTotals:
    """Comparison result for a single variable."""

    variable: str
    cosilico_total: float
    policyengine_total: float
    n_records: int
    match_rate: float  # Within $1 tolerance
    mean_absolute_error: float
    title: str = ""
    cosilico_time_ms: float = 0.0
    policyengine_time_ms: float = 0.0

    @property
    def difference(self) -> float:
        """Cosilico - PolicyEngine difference."""
        return self.cosilico_total - self.policyengine_total

    @property
    def percent_difference(self) -> float:
        """Percent difference from PolicyEngine."""
        if self.policyengine_total == 0:
            return 0.0
        return (self.difference / self.policyengine_total) * 100


@dataclass
class TimedResult:
    """Result with timing information."""
    data: dict[str, np.ndarray]
    elapsed_ms: float


def _load_cosilico_data_sources():
    """Load cosilico-data-sources modules."""
    data_sources = Path.home() / "CosilicoAI" / "cosilico-data-sources" / "micro" / "us"
    if str(data_sources) not in sys.path:
        sys.path.insert(0, str(data_sources))

    from tax_unit_builder import load_and_build_tax_units
    from cosilico_runner import run_all_calculations

    return load_and_build_tax_units, run_all_calculations


def load_cosilico_cps(year: int = 2024) -> TimedResult:
    """Load Cosilico calculations from CPS microdata.

    Returns:
        TimedResult with dict of arrays and elapsed time in ms.
    """
    load_and_build_tax_units, run_all_calculations = _load_cosilico_data_sources()

    start = time.perf_counter()
    df = load_and_build_tax_units(year)
    df = run_all_calculations(df, year)
    elapsed = (time.perf_counter() - start) * 1000

    result = {"weight": df["weight"].values}

    for var_name, config in COMPARISON_VARIABLES.items():
        col = config["cosilico_col"]
        if col in df.columns:
            result[var_name] = df[col].values
        else:
            result[var_name] = np.zeros(len(df))

    return TimedResult(data=result, elapsed_ms=elapsed)


def load_policyengine_values(
    year: int = 2024,
    variables: Optional[list[str]] = None,
) -> TimedResult:
    """Load PolicyEngine calculations.

    Returns:
        TimedResult with dict of arrays and elapsed time in ms.
    """
    from policyengine_us import Microsimulation

    start = time.perf_counter()
    sim = Microsimulation()

    if variables is None:
        variables = list(COMPARISON_VARIABLES.keys())

    result = {"weight": np.array(sim.calculate("tax_unit_weight", year))}
    n_tax_units = len(result["weight"])

    for var_name in variables:
        if var_name not in COMPARISON_VARIABLES:
            continue
        config = COMPARISON_VARIABLES[var_name]
        pe_var = config["pe_var"]
        pe_entity = config.get("pe_entity", "tax_unit")

        try:
            values = np.array(sim.calculate(pe_var, year))

            if pe_entity == "person" and len(values) != n_tax_units:
                # Need to aggregate person-level to tax unit
                # Use person's tax unit ID to sum
                person_tax_unit_id = np.array(sim.calculate("person_tax_unit_id", year))
                tax_unit_ids = np.array(sim.calculate("tax_unit_id", year))

                # Sum values by tax unit
                aggregated = np.zeros(n_tax_units)
                for i, tu_id in enumerate(tax_unit_ids):
                    mask = person_tax_unit_id == tu_id
                    aggregated[i] = values[mask].sum()
                values = aggregated

            result[var_name] = values
        except Exception:
            result[var_name] = np.zeros_like(result["weight"])

    elapsed = (time.perf_counter() - start) * 1000

    return TimedResult(data=result, elapsed_ms=elapsed)


def compare_cps_totals(
    year: int = 2024,
    variables: Optional[list[str]] = None,
    tolerance: float = 1.0,
) -> dict[str, ComparisonTotals]:
    """Compare Cosilico CPS totals against PolicyEngine.

    Args:
        year: Tax year
        variables: List of variables to compare (default: all)
        tolerance: Match tolerance in dollars

    Returns:
        Dict mapping variable names to ComparisonTotals.
    """
    if variables is None:
        variables = list(COMPARISON_VARIABLES.keys())

    # Load both sets of values with timing
    cos_result = load_cosilico_cps(year)
    pe_result = load_policyengine_values(year, variables)

    cos_data = cos_result.data
    pe_data = pe_result.data

    results = {}

    for var_name in variables:
        if var_name not in COMPARISON_VARIABLES:
            continue

        config = COMPARISON_VARIABLES[var_name]
        cos_values = cos_data.get(var_name, np.zeros_like(cos_data["weight"]))
        pe_values = pe_data.get(var_name, np.zeros_like(pe_data["weight"]))
        cos_weights = cos_data["weight"]
        pe_weights = pe_data["weight"]

        # Weighted totals (can compare even with different record counts)
        cos_total = (cos_values * cos_weights).sum()
        pe_total = (pe_values * pe_weights).sum()

        # Match rate only possible if same length (same microdata)
        # If different lengths, we can only compare totals
        if len(cos_values) == len(pe_values):
            diff = np.abs(cos_values - pe_values)
            match_rate = (diff <= tolerance).mean()
            mae = diff.mean()
        else:
            # Different microdata sources - can't do unit-level comparison
            match_rate = np.nan
            mae = np.nan

        n_records = max(len(cos_values), len(pe_values))

        results[var_name] = ComparisonTotals(
            variable=var_name,
            cosilico_total=float(cos_total),
            policyengine_total=float(pe_total),
            n_records=n_records,
            match_rate=float(match_rate) if not np.isnan(match_rate) else 0.0,
            mean_absolute_error=float(mae) if not np.isnan(mae) else 0.0,
            title=config["title"],
            cosilico_time_ms=cos_result.elapsed_ms,
            policyengine_time_ms=pe_result.elapsed_ms,
        )

    return results


def export_to_dashboard(
    comparison: dict[str, ComparisonTotals],
    year: int = 2024,
) -> dict:
    """Export comparison results to dashboard JSON format."""
    sections = []
    total_cos_time = 0.0
    total_pe_time = 0.0

    for var_name, totals in comparison.items():
        sections.append({
            "variable": var_name,
            "title": totals.title,
            "cosilico_total": totals.cosilico_total,
            "policyengine_total": totals.policyengine_total,
            "difference": totals.difference,
            "percent_difference": totals.percent_difference,
            "match_rate": totals.match_rate,
            "mean_absolute_error": totals.mean_absolute_error,
            "n_records": totals.n_records,
        })
        total_cos_time = totals.cosilico_time_ms  # Same for all vars
        total_pe_time = totals.policyengine_time_ms

    all_totals = list(comparison.values())
    overall_match = np.mean([t.match_rate for t in all_totals]) if all_totals else 0
    overall_mae = np.mean([t.mean_absolute_error for t in all_totals]) if all_totals else 0

    return {
        "timestamp": datetime.now().isoformat(),
        "year": year,
        "data_source": "CPS ASEC",
        "sections": sections,
        "overall": {
            "match_rate": overall_match,
            "mean_absolute_error": overall_mae,
            "variables_compared": len(sections),
        },
        "performance": {
            "cosilico_ms": total_cos_time,
            "policyengine_ms": total_pe_time,
            "speedup": total_pe_time / total_cos_time if total_cos_time > 0 else 0,
        },
    }


def generate_report(year: int = 2024) -> str:
    """Generate a text report comparing Cosilico vs PolicyEngine."""
    comparison = compare_cps_totals(year)

    # Get timing from first result
    first_result = next(iter(comparison.values()))
    cos_time = first_result.cosilico_time_ms
    pe_time = first_result.policyengine_time_ms

    lines = [
        "=" * 80,
        f"Cosilico vs PolicyEngine: CPS Weighted Totals ({year})",
        "=" * 80,
        "",
        f"{'Variable':<25} {'Cosilico':>12} {'PolicyEngine':>12} {'Diff':>12} {'%':>8}",
        "-" * 80,
    ]

    for var_name, totals in comparison.items():
        cos_b = totals.cosilico_total / 1e9
        pe_b = totals.policyengine_total / 1e9
        diff_b = totals.difference / 1e9
        pct = totals.percent_difference

        lines.append(
            f"{totals.title:<25} ${cos_b:>10.1f}B ${pe_b:>10.1f}B ${diff_b:>+10.1f}B {pct:>+7.1f}%"
        )

    lines.extend([
        "-" * 80,
        "",
        "Match Rate (within $1):",
    ])

    for var_name, totals in comparison.items():
        lines.append(f"  {totals.title}: {totals.match_rate*100:.1f}%")

    lines.extend([
        "",
        "-" * 80,
        "Performance:",
        f"  Cosilico:     {cos_time:>10,.0f} ms ({cos_time/1000:.1f}s)",
        f"  PolicyEngine: {pe_time:>10,.0f} ms ({pe_time/1000:.1f}s)",
        f"  Speedup:      {pe_time/cos_time:>10.1f}x" if cos_time > 0 else "  Speedup:      N/A",
        "",
        "=" * 80,
    ])

    return "\n".join(lines)


def main():
    """Run comparison and print report."""
    print(generate_report(2024))


if __name__ == "__main__":
    main()

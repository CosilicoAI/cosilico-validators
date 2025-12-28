"""Aligned comparison using common dataset.

Uses PolicyEngine's input data for both systems to isolate rule differences.
"""

from dataclasses import dataclass
from typing import Callable
import numpy as np

try:
    from policyengine_us import Microsimulation
    HAS_POLICYENGINE = True
except ImportError:
    HAS_POLICYENGINE = False
    Microsimulation = None


@dataclass
class CommonDataset:
    """Shared input data for both Cosilico and PolicyEngine calculations."""

    # Tax unit identifiers
    tax_unit_id: np.ndarray
    weight: np.ndarray

    # Filing status
    is_joint: np.ndarray
    filing_status: np.ndarray  # String array: SINGLE, JOINT, HEAD_OF_HOUSEHOLD, etc.

    # Income components
    earned_income: np.ndarray
    wages: np.ndarray
    self_employment_income: np.ndarray
    interest_income: np.ndarray
    dividend_income: np.ndarray
    capital_gains: np.ndarray
    rental_income: np.ndarray
    social_security: np.ndarray
    pension_income: np.ndarray
    unemployment_compensation: np.ndarray
    other_income: np.ndarray

    # Investment income (for EITC disqualification)
    investment_income: np.ndarray

    # Computed totals from PE
    adjusted_gross_income: np.ndarray
    taxable_income: np.ndarray

    # Demographics
    eitc_child_count: np.ndarray
    ctc_child_count: np.ndarray
    head_age: np.ndarray
    spouse_age: np.ndarray

    # Standard deduction inputs (from 26 USC 63)
    head_is_blind: np.ndarray
    spouse_is_blind: np.ndarray
    head_is_dependent: np.ndarray  # Tax filer claimed as dependent on another return

    # CDCC inputs (from 26 USC 21)
    cdcc_qualifying_individuals: np.ndarray  # Count of qualifying individuals (children <13 or disabled)
    childcare_expenses: np.ndarray  # Employment-related care expenses paid during year

    @property
    def n_records(self) -> int:
        return len(self.tax_unit_id)


def load_common_dataset(year: int = 2024) -> CommonDataset:
    """Load common dataset from PolicyEngine simulation.

    Extracts all input variables needed for tax calculations from PE's
    enhanced CPS, providing a shared baseline for comparison.
    """
    if not HAS_POLICYENGINE:
        raise ImportError("policyengine_us required for common dataset")

    sim = Microsimulation()

    def calc(var):
        return np.array(sim.calculate(var, year))

    # Get tax_unit-level arrays first
    tax_unit_id = calc("tax_unit_id")
    n_tax_units = len(tax_unit_id)

    # Get filing_status as string array
    filing_status_raw = sim.calculate("filing_status", year)
    filing_status = np.array(filing_status_raw)

    # Get age at tax_unit level (directly available)
    head_age = calc("age_head")
    spouse_age = calc("age_spouse")

    # Aggregate person-level blind status to tax_unit level
    # Need to map from person to tax_unit
    is_blind_person = calc("is_blind")
    is_tax_unit_head = calc("is_tax_unit_head")
    is_tax_unit_spouse = calc("is_tax_unit_spouse")
    person_tax_unit_id = calc("person_tax_unit_id")

    # Create mapping from tax_unit_id to index
    tu_id_to_idx = {tid: idx for idx, tid in enumerate(tax_unit_id)}

    # Initialize tax_unit-level blind arrays
    head_is_blind = np.zeros(n_tax_units, dtype=bool)
    spouse_is_blind = np.zeros(n_tax_units, dtype=bool)
    head_is_dependent = np.zeros(n_tax_units, dtype=bool)

    # Aggregate person-level to tax_unit-level
    is_tax_unit_dependent = calc("is_tax_unit_dependent")
    for i in range(len(person_tax_unit_id)):
        ptu_id = person_tax_unit_id[i]
        if ptu_id in tu_id_to_idx:
            tu_idx = tu_id_to_idx[ptu_id]
            if is_tax_unit_head[i]:
                if is_blind_person[i]:
                    head_is_blind[tu_idx] = True
                if is_tax_unit_dependent[i]:
                    head_is_dependent[tu_idx] = True
            if is_tax_unit_spouse[i] and is_blind_person[i]:
                spouse_is_blind[tu_idx] = True

    return CommonDataset(
        tax_unit_id=tax_unit_id,
        weight=calc("tax_unit_weight"),
        is_joint=calc("tax_unit_is_joint"),
        filing_status=filing_status,

        # Income
        earned_income=calc("tax_unit_earned_income"),
        wages=calc("tax_unit_earned_income"),  # Simplified - PE combines wages
        self_employment_income=np.zeros_like(tax_unit_id, dtype=float),  # Included in earned
        interest_income=calc("taxable_interest_income") if _var_exists(sim, "taxable_interest_income", year) else np.zeros_like(tax_unit_id, dtype=float),
        dividend_income=calc("qualified_dividend_income") if _var_exists(sim, "qualified_dividend_income", year) else np.zeros_like(tax_unit_id, dtype=float),
        capital_gains=calc("long_term_capital_gains") + calc("short_term_capital_gains") if _var_exists(sim, "long_term_capital_gains", year) else np.zeros_like(tax_unit_id, dtype=float),
        rental_income=calc("rental_income") if _var_exists(sim, "rental_income", year) else np.zeros_like(tax_unit_id, dtype=float),
        social_security=calc("tax_unit_social_security") if _var_exists(sim, "tax_unit_social_security", year) else np.zeros_like(tax_unit_id, dtype=float),
        pension_income=calc("taxable_pension_income") if _var_exists(sim, "taxable_pension_income", year) else np.zeros_like(tax_unit_id, dtype=float),
        unemployment_compensation=calc("tax_unit_unemployment_compensation") if _var_exists(sim, "tax_unit_unemployment_compensation", year) else np.zeros_like(tax_unit_id, dtype=float),
        other_income=np.zeros_like(tax_unit_id, dtype=float),

        investment_income=calc("net_investment_income"),

        # PE computed values (used as inputs for some Cosilico formulas)
        adjusted_gross_income=calc("adjusted_gross_income"),
        taxable_income=calc("taxable_income"),

        # Demographics
        eitc_child_count=calc("eitc_child_count"),
        ctc_child_count=calc("ctc_qualifying_children") if _var_exists(sim, "ctc_qualifying_children", year) else calc("eitc_child_count"),
        head_age=head_age,
        spouse_age=spouse_age,

        # Standard deduction inputs (from 26 USC 63)
        head_is_blind=head_is_blind,
        spouse_is_blind=spouse_is_blind,
        head_is_dependent=head_is_dependent,

        # CDCC inputs (from 26 USC 21)
        cdcc_qualifying_individuals=calc("capped_count_cdcc_eligible") if _var_exists(sim, "capped_count_cdcc_eligible", year) else np.zeros_like(tax_unit_id, dtype=float),
        childcare_expenses=calc("tax_unit_childcare_expenses") if _var_exists(sim, "tax_unit_childcare_expenses", year) else np.zeros_like(tax_unit_id, dtype=float),
    )


def _var_exists(sim, var_name: str, year: int) -> bool:
    """Check if a variable exists and has values."""
    try:
        sim.calculate(var_name, year)
        return True
    except:
        return False


@dataclass
class ComparisonResult:
    """Result of comparing a single variable."""
    variable: str
    match_rate: float  # Within $1 tolerance
    mean_absolute_error: float
    n_records: int
    cosilico_total: float  # Weighted
    policyengine_total: float  # Weighted
    cosilico_values: np.ndarray
    policyengine_values: np.ndarray
    error_percentiles: dict


def compare_variable(
    dataset: CommonDataset,
    cosilico_func: Callable[[CommonDataset], np.ndarray],
    pe_values: np.ndarray,
    variable_name: str,
    tolerance: float = 1.0,
) -> ComparisonResult:
    """Compare Cosilico calculation to PolicyEngine on common dataset."""

    cos_values = cosilico_func(dataset)

    diff = np.abs(cos_values - pe_values)
    match_rate = (diff <= tolerance).mean()
    mae = diff.mean()

    return ComparisonResult(
        variable=variable_name,
        match_rate=float(match_rate),
        mean_absolute_error=float(mae),
        n_records=len(cos_values),
        cosilico_total=float((cos_values * dataset.weight).sum()),
        policyengine_total=float((pe_values * dataset.weight).sum()),
        cosilico_values=cos_values,
        policyengine_values=pe_values,
        error_percentiles={
            "p50": float(np.percentile(diff, 50)),
            "p90": float(np.percentile(diff, 90)),
            "p95": float(np.percentile(diff, 95)),
            "p99": float(np.percentile(diff, 99)),
            "max": float(diff.max()),
        },
    )


def run_aligned_comparison(year: int = 2024) -> dict:
    """Run full aligned comparison using common dataset.

    Returns dashboard-formatted results.
    """
    import sys
    from pathlib import Path
    from datetime import datetime

    # Load common dataset
    print("Loading common dataset from PolicyEngine...")
    dataset = load_common_dataset(year)
    print(f"  {dataset.n_records:,} tax units loaded")

    # Load Cosilico implementations
    data_sources_path = Path.home() / "CosilicoAI" / "cosilico-data-sources" / "micro" / "us"
    sys.path.insert(0, str(data_sources_path))
    from cosilico_runner import PARAMS_2024, calculate_eitc, calculate_income_tax
    import pandas as pd

    # Get PE values
    sim = Microsimulation()
    pe_eitc = np.array(sim.calculate("eitc", year))
    pe_income_tax = np.array(sim.calculate("income_tax_before_credits", year))

    # Define Cosilico functions that use common dataset
    def cos_eitc(ds: CommonDataset) -> np.ndarray:
        df = pd.DataFrame({
            "earned_income": ds.earned_income,
            "adjusted_gross_income": ds.adjusted_gross_income,
            "num_eitc_children": np.clip(ds.eitc_child_count, 0, 3),
            "is_joint": ds.is_joint,
            "investment_income": ds.investment_income,
        })
        return calculate_eitc(df, PARAMS_2024)

    def cos_income_tax(ds: CommonDataset) -> np.ndarray:
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
    print(f"  MAE: ${eitc_result.mean_absolute_error:,.0f}")

    print("\nComparing Income Tax...")
    tax_result = compare_variable(dataset, cos_income_tax, pe_income_tax, "income_tax_before_credits")
    results.append(tax_result)
    print(f"  Match rate: {tax_result.match_rate*100:.1f}%")
    print(f"  MAE: ${tax_result.mean_absolute_error:,.0f}")

    # Format as dashboard JSON
    return {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "tax_year": year,
            "data_source": "PolicyEngine Enhanced CPS (Common Dataset)",
            "comparison_type": "aligned_inputs",
            "description": "Both systems use identical PE inputs, isolating rule implementation differences",
        },
        "summary": {
            "overall_match_rate": float(np.mean([r.match_rate for r in results])),
            "total_records": dataset.n_records,
            "variables_compared": len(results),
        },
        "variables": [
            {
                "variable": r.variable,
                "match_rate": r.match_rate,
                "mean_absolute_error": r.mean_absolute_error,
                "n_records": r.n_records,
                "cosilico_weighted_total": r.cosilico_total,
                "policyengine_weighted_total": r.policyengine_total,
                "difference_billions": (r.cosilico_total - r.policyengine_total) / 1e9,
                "error_percentiles": r.error_percentiles,
            }
            for r in results
        ],
    }

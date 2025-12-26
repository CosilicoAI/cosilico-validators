"""TaxSim comparison infrastructure for validating Cosilico calculations.

This module provides tools to compare Cosilico tax calculations against
TaxSim 35 results and generate detailed comparison reports.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import yaml

from .taxsim_client import TaxSimCase, TaxSimClient, TaxSimResult, create_test_case
from .variable_mapping import COSILICO_ALIASES, map_cosilico_to_taxsim


@dataclass
class ComparisonResult:
    """Result of comparing a single variable between Cosilico and TaxSim."""

    case_name: str
    variable: str
    cosilico_value: Optional[float]
    taxsim_value: Optional[float]
    difference: Optional[float]
    percent_difference: Optional[float]
    within_tolerance: bool
    tolerance: float
    taxsim_raw_var: Optional[str] = None
    notes: Optional[str] = None
    error: Optional[str] = None

    @property
    def matches(self) -> bool:
        """Check if values match within tolerance."""
        return self.within_tolerance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_name": self.case_name,
            "variable": self.variable,
            "cosilico_value": self.cosilico_value,
            "taxsim_value": self.taxsim_value,
            "difference": self.difference,
            "percent_difference": self.percent_difference,
            "within_tolerance": self.within_tolerance,
            "tolerance": self.tolerance,
            "taxsim_raw_var": self.taxsim_raw_var,
            "notes": self.notes,
            "error": self.error,
        }


@dataclass
class CaseComparisonResult:
    """Results from comparing all variables for a single test case."""

    case_name: str
    case_inputs: Dict[str, Any]
    variable_results: Dict[str, ComparisonResult]
    all_match: bool
    match_count: int
    mismatch_count: int
    error_count: int
    taxsim_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_name": self.case_name,
            "case_inputs": self.case_inputs,
            "variable_results": {k: v.to_dict() for k, v in self.variable_results.items()},
            "all_match": self.all_match,
            "match_count": self.match_count,
            "mismatch_count": self.mismatch_count,
            "error_count": self.error_count,
            "taxsim_error": self.taxsim_error,
        }


@dataclass
class ValidationReport:
    """Complete validation report for multiple test cases."""

    title: str
    generated_at: str
    taxsim_version: str
    year: int
    tolerance: float
    case_results: List[CaseComparisonResult]
    summary: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Calculate summary statistics."""
        total_cases = len(self.case_results)
        cases_matching = sum(1 for c in self.case_results if c.all_match)
        total_variables = sum(len(c.variable_results) for c in self.case_results)
        variables_matching = sum(c.match_count for c in self.case_results)

        self.summary = {
            "total_cases": total_cases,
            "cases_matching": cases_matching,
            "cases_with_differences": total_cases - cases_matching,
            "case_match_rate": cases_matching / total_cases if total_cases > 0 else 0,
            "total_variable_comparisons": total_variables,
            "variables_matching": variables_matching,
            "variable_match_rate": variables_matching / total_variables if total_variables > 0 else 0,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "generated_at": self.generated_at,
            "taxsim_version": self.taxsim_version,
            "year": self.year,
            "tolerance": self.tolerance,
            "summary": self.summary,
            "case_results": [c.to_dict() for c in self.case_results],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        """Generate a markdown report."""
        lines = [
            f"# {self.title}",
            "",
            f"Generated: {self.generated_at}",
            f"TaxSim Version: {self.taxsim_version}",
            f"Tax Year: {self.year}",
            f"Tolerance: ${self.tolerance:.2f}",
            "",
            "## Summary",
            "",
            f"- **Cases Tested**: {self.summary['total_cases']}",
            f"- **Cases Matching**: {self.summary['cases_matching']} ({self.summary['case_match_rate']:.1%})",
            f"- **Variable Comparisons**: {self.summary['total_variable_comparisons']}",
            f"- **Variables Matching**: {self.summary['variables_matching']} ({self.summary['variable_match_rate']:.1%})",
            "",
        ]

        # Add case details
        lines.append("## Case Results")
        lines.append("")

        for case_result in self.case_results:
            status = "PASS" if case_result.all_match else "FAIL"
            lines.append(f"### {case_result.case_name} [{status}]")
            lines.append("")

            if case_result.taxsim_error:
                lines.append(f"**Error**: {case_result.taxsim_error}")
                lines.append("")
                continue

            # Variable comparison table
            lines.append("| Variable | Cosilico | TaxSim | Difference | Status |")
            lines.append("|----------|----------|--------|------------|--------|")

            for var_name, var_result in case_result.variable_results.items():
                cosilico_str = f"${var_result.cosilico_value:,.2f}" if var_result.cosilico_value is not None else "N/A"
                taxsim_str = f"${var_result.taxsim_value:,.2f}" if var_result.taxsim_value is not None else "N/A"
                diff_str = f"${var_result.difference:+,.2f}" if var_result.difference is not None else "N/A"
                status_str = "OK" if var_result.within_tolerance else "DIFF"
                lines.append(f"| {var_name} | {cosilico_str} | {taxsim_str} | {diff_str} | {status_str} |")

            lines.append("")

        # Add discrepancies section
        discrepancies = [
            (c, v)
            for c in self.case_results
            for v in c.variable_results.values()
            if not v.within_tolerance
        ]

        if discrepancies:
            lines.append("## Discrepancies")
            lines.append("")
            lines.append("| Case | Variable | Cosilico | TaxSim | Difference |")
            lines.append("|------|----------|----------|--------|------------|")

            for case_result, var_result in discrepancies:
                cosilico_str = f"${var_result.cosilico_value:,.2f}" if var_result.cosilico_value is not None else "N/A"
                taxsim_str = f"${var_result.taxsim_value:,.2f}" if var_result.taxsim_value is not None else "N/A"
                diff_str = f"${var_result.difference:+,.2f}" if var_result.difference is not None else "N/A"
                lines.append(f"| {case_result.case_name} | {var_result.variable} | {cosilico_str} | {taxsim_str} | {diff_str} |")

            lines.append("")

        return "\n".join(lines)


class TaxSimComparison:
    """Compare Cosilico calculations against TaxSim 35.

    Usage:
        # With a Cosilico calculation function
        def cosilico_calc(case: TaxSimCase, variables: List[str]) -> Dict[str, float]:
            # Calculate using Cosilico DSL
            return {"adjusted_gross_income": 50000, "earned_income_credit": 0}

        comparison = TaxSimComparison(
            cosilico_calculator=cosilico_calc,
            variables=["adjusted_gross_income", "earned_income_credit"],
        )

        # Load test cases and run comparison
        cases = comparison.load_test_cases("test_cases.yaml")
        report = comparison.run(cases, year=2023)
        print(report.to_markdown())
    """

    def __init__(
        self,
        cosilico_calculator: Optional[Callable[[TaxSimCase, List[str]], Dict[str, float]]] = None,
        variables: Optional[List[str]] = None,
        tolerance: float = 1.0,
        taxsim_client: Optional[TaxSimClient] = None,
    ):
        """Initialize comparison engine.

        Args:
            cosilico_calculator: Function to calculate Cosilico values.
                                 Takes (case, variables) and returns dict of values.
            variables: List of variables to compare
            tolerance: Absolute tolerance for comparison (in dollars)
            taxsim_client: TaxSim client instance (created if not provided)
        """
        self.cosilico_calculator = cosilico_calculator
        self.variables = variables or [
            "adjusted_gross_income",
            "taxable_income",
            "child_tax_credit",
            "earned_income_credit",
            "total_federal_income_tax",
        ]
        self.tolerance = tolerance
        self.client = taxsim_client or TaxSimClient()

    def load_test_cases(self, path: Union[str, Path]) -> List[TaxSimCase]:
        """Load test cases from a YAML file.

        Args:
            path: Path to YAML file with test cases

        Returns:
            List of TaxSimCase objects
        """
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)

        cases = []
        for i, case_data in enumerate(data.get("test_cases", [])):
            case = TaxSimCase.from_dict(case_data.get("inputs", {}))
            case.taxsimid = i + 1
            case.name = case_data.get("name", f"Case {i + 1}")
            case.notes = case_data.get("notes")
            cases.append(case)

        return cases

    def compare_single_variable(
        self,
        case_name: str,
        variable: str,
        cosilico_value: Optional[float],
        taxsim_result: TaxSimResult,
    ) -> ComparisonResult:
        """Compare a single variable between Cosilico and TaxSim."""
        # Get TaxSim value
        taxsim_value = taxsim_result.get(variable)

        # Also try the raw TaxSim variable name
        taxsim_raw_var = map_cosilico_to_taxsim(variable)
        if taxsim_value is None and taxsim_raw_var:
            taxsim_value = taxsim_result.raw_output.get(taxsim_raw_var)

        # Calculate difference
        if cosilico_value is not None and taxsim_value is not None:
            difference = cosilico_value - taxsim_value
            if taxsim_value != 0:
                percent_difference = (difference / abs(taxsim_value)) * 100
            else:
                percent_difference = None
            within_tolerance = abs(difference) <= self.tolerance
        else:
            difference = None
            percent_difference = None
            within_tolerance = cosilico_value is None and taxsim_value is None

        return ComparisonResult(
            case_name=case_name,
            variable=variable,
            cosilico_value=cosilico_value,
            taxsim_value=taxsim_value,
            difference=difference,
            percent_difference=percent_difference,
            within_tolerance=within_tolerance,
            tolerance=self.tolerance,
            taxsim_raw_var=taxsim_raw_var,
        )

    def compare_case(
        self,
        case: TaxSimCase,
        taxsim_result: TaxSimResult,
        cosilico_values: Optional[Dict[str, float]] = None,
    ) -> CaseComparisonResult:
        """Compare all variables for a single test case."""
        case_name = case.name or f"Case {case.taxsimid}"

        # Handle TaxSim error
        if taxsim_result.error:
            return CaseComparisonResult(
                case_name=case_name,
                case_inputs=case.to_taxsim_dict(),
                variable_results={},
                all_match=False,
                match_count=0,
                mismatch_count=0,
                error_count=1,
                taxsim_error=taxsim_result.error,
            )

        # Calculate Cosilico values if calculator provided
        if cosilico_values is None and self.cosilico_calculator:
            cosilico_values = self.cosilico_calculator(case, self.variables)
        elif cosilico_values is None:
            # Use TaxSim values as "Cosilico" values for testing infrastructure
            cosilico_values = {}

        # Compare each variable
        variable_results = {}
        match_count = 0
        mismatch_count = 0
        error_count = 0

        for variable in self.variables:
            cosilico_value = cosilico_values.get(variable)
            result = self.compare_single_variable(
                case_name, variable, cosilico_value, taxsim_result
            )
            variable_results[variable] = result

            if result.error:
                error_count += 1
            elif result.within_tolerance:
                match_count += 1
            else:
                mismatch_count += 1

        return CaseComparisonResult(
            case_name=case_name,
            case_inputs=case.to_taxsim_dict(),
            variable_results=variable_results,
            all_match=mismatch_count == 0 and error_count == 0,
            match_count=match_count,
            mismatch_count=mismatch_count,
            error_count=error_count,
        )

    def run(
        self,
        cases: List[TaxSimCase],
        year: int = 2023,
        title: Optional[str] = None,
    ) -> ValidationReport:
        """Run comparison for all test cases.

        Args:
            cases: List of test cases
            year: Tax year for comparison
            title: Report title

        Returns:
            ValidationReport with all comparison results
        """
        # Ensure year is set on all cases
        for case in cases:
            case.year = year

        # Run TaxSim calculations
        taxsim_results = self.client.calculate_batch(cases)

        # Compare each case
        case_results = []
        for case, taxsim_result in zip(cases, taxsim_results):
            case_result = self.compare_case(case, taxsim_result)
            case_results.append(case_result)

        return ValidationReport(
            title=title or f"TaxSim Validation Report - TY {year}",
            generated_at=datetime.now().isoformat(),
            taxsim_version="TAXSIM-35",
            year=year,
            tolerance=self.tolerance,
            case_results=case_results,
        )

    def run_from_yaml(
        self,
        yaml_path: Union[str, Path],
        year: int = 2023,
        title: Optional[str] = None,
    ) -> ValidationReport:
        """Load test cases from YAML and run comparison.

        Args:
            yaml_path: Path to YAML file with test cases
            year: Tax year
            title: Report title

        Returns:
            ValidationReport
        """
        cases = self.load_test_cases(yaml_path)
        return self.run(cases, year=year, title=title)


def create_comparison_report(
    cases: List[TaxSimCase],
    cosilico_values: Dict[int, Dict[str, float]],
    variables: List[str],
    year: int = 2023,
    tolerance: float = 1.0,
    title: Optional[str] = None,
) -> ValidationReport:
    """Create a comparison report from pre-calculated values.

    This is useful when you've already calculated Cosilico values and
    just want to compare against TaxSim.

    Args:
        cases: List of test cases
        cosilico_values: Dict mapping taxsimid to variable values
        variables: List of variables to compare
        year: Tax year
        tolerance: Comparison tolerance in dollars
        title: Report title

    Returns:
        ValidationReport
    """
    def get_cosilico_values(case: TaxSimCase, vars: List[str]) -> Dict[str, float]:
        return cosilico_values.get(case.taxsimid, {})

    comparison = TaxSimComparison(
        cosilico_calculator=get_cosilico_values,
        variables=variables,
        tolerance=tolerance,
    )

    return comparison.run(cases, year=year, title=title)

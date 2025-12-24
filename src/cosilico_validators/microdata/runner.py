"""Microdata validation runner.

Orchestrates comparison between Cosilico and reference calculators
(PolicyEngine, TAXSIM, etc.) on microdata.

This is the main entry point for CPS-scale validation.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set
import time

from rich.console import Console
from rich.table import Table
from rich.progress import Progress

from .base import (
    MicrodataSource,
    Calculator,
    ComparisonResult,
    compare_calculators,
)
from .policyengine import PolicyEngineMicrodataSource, PolicyEngineCalculator
from .cosilico import CosilicoCalculator


@dataclass
class VariableValidation:
    """Results for validating a single variable."""

    variable: str
    comparisons: Dict[str, ComparisonResult] = field(default_factory=dict)
    cosilico_time_ms: float = 0.0
    reference_times_ms: Dict[str, float] = field(default_factory=dict)

    @property
    def best_match_rate(self) -> float:
        """Best match rate across all comparisons."""
        if not self.comparisons:
            return 0.0
        return max(c.match_rate for c in self.comparisons.values())

    @property
    def passed(self) -> bool:
        """True if any comparison has >99% match rate."""
        return self.best_match_rate >= 0.99


@dataclass
class ValidationReport:
    """Full validation report across all variables."""

    source_name: str
    year: int
    n_records: int
    variables: Dict[str, VariableValidation] = field(default_factory=dict)
    total_time_seconds: float = 0.0

    @property
    def n_passed(self) -> int:
        return sum(1 for v in self.variables.values() if v.passed)

    @property
    def n_failed(self) -> int:
        return len(self.variables) - self.n_passed

    @property
    def pass_rate(self) -> float:
        if not self.variables:
            return 0.0
        return self.n_passed / len(self.variables)


class MicrodataValidator:
    """Validates Cosilico encodings against reference calculators on microdata.

    This orchestrates the validation process:
    1. Load microdata from a source (PolicyEngine enhanced CPS)
    2. Calculate variables using Cosilico
    3. Calculate same variables using reference calculators
    4. Compare results and report discrepancies

    Example:
        validator = MicrodataValidator()
        report = validator.run(variables=["eitc", "niit", "additional_medicare_tax"])
        validator.print_report(report)
    """

    def __init__(
        self,
        source: Optional[MicrodataSource] = None,
        calculators: Optional[Dict[str, Calculator]] = None,
        cosilico_us_path: Optional[Path] = None,
        tolerance: float = 15.0,
        year: int = 2024,
    ):
        """Initialize validator.

        Args:
            source: MicrodataSource (default: PolicyEngine enhanced CPS)
            calculators: Dict of reference calculators to compare against
            cosilico_us_path: Path to cosilico-us repo
            tolerance: Dollar tolerance for matching
            year: Tax year
        """
        self.year = year
        self.tolerance = tolerance
        self.cosilico_us_path = cosilico_us_path or Path.home() / "CosilicoAI/cosilico-us"

        # Default source: PolicyEngine enhanced CPS
        self.source = source or PolicyEngineMicrodataSource(year=year)

        # Cosilico calculator
        self.cosilico = CosilicoCalculator(cosilico_us_path=self.cosilico_us_path)

        # Reference calculators (default: PolicyEngine)
        self.calculators = calculators or {
            "PolicyEngine": PolicyEngineCalculator(),
        }

        self.console = Console()

    def get_available_variables(self) -> Set[str]:
        """Get variables that both Cosilico and at least one reference support."""
        cosilico_vars = self.cosilico.supported_variables
        reference_vars = set()
        for calc in self.calculators.values():
            reference_vars |= calc.supported_variables
        return cosilico_vars & reference_vars

    def validate_variable(
        self,
        variable: str,
        show_progress: bool = True,
    ) -> VariableValidation:
        """Validate a single variable against all reference calculators."""
        validation = VariableValidation(variable=variable)

        # Calculate with Cosilico
        if show_progress:
            self.console.print(f"  [cyan]Calculating {variable} with Cosilico...[/cyan]")

        cosilico_result = self.cosilico.calculate(variable, self.source, self.year)
        validation.cosilico_time_ms = cosilico_result.calculation_time_ms

        if not cosilico_result.success:
            if show_progress:
                self.console.print(f"    [red]Cosilico failed: {cosilico_result.error}[/red]")
            return validation

        # Compare against each reference calculator
        for name, calculator in self.calculators.items():
            if not calculator.supports_variable(variable):
                continue

            if show_progress:
                self.console.print(f"  [cyan]Comparing with {name}...[/cyan]")

            start = time.perf_counter()
            ref_result = calculator.calculate(variable, self.source, self.year)
            validation.reference_times_ms[name] = (time.perf_counter() - start) * 1000

            if not ref_result.success:
                if show_progress:
                    self.console.print(f"    [yellow]{name} failed: {ref_result.error}[/yellow]")
                continue

            # Compare
            comparison = compare_calculators(
                variable=variable,
                calc_a=self.cosilico,
                calc_b=calculator,
                source=self.source,
                tolerance=self.tolerance,
                year=self.year,
            )
            validation.comparisons[name] = comparison

            if show_progress:
                status = "[green]PASS[/green]" if comparison.match_rate >= 0.99 else "[red]FAIL[/red]"
                self.console.print(
                    f"    {status} vs {name}: {comparison.match_rate:.1%} match, "
                    f"MAE=${comparison.mean_absolute_error:.2f}"
                )

        return validation

    def run(
        self,
        variables: Optional[List[str]] = None,
        show_progress: bool = True,
    ) -> ValidationReport:
        """Run validation for multiple variables.

        Args:
            variables: Variables to validate (default: all available)
            show_progress: Whether to print progress

        Returns:
            ValidationReport with all results
        """
        start_time = time.perf_counter()

        # Default to all available variables
        if variables is None:
            variables = list(self.get_available_variables())

        if show_progress:
            self.console.print(f"\n[bold]Microdata Validation[/bold]")
            self.console.print(f"Source: {self.source.name}")
            self.console.print(f"Year: {self.year}")
            self.console.print(f"Records: {self.source.n_persons:,} persons, "
                             f"{self.source.n_tax_units:,} tax units")
            self.console.print(f"Variables: {len(variables)}")
            self.console.print()

        report = ValidationReport(
            source_name=self.source.name,
            year=self.year,
            n_records=self.source.n_tax_units,
        )

        for variable in variables:
            if show_progress:
                self.console.print(f"[bold]{variable}[/bold]")

            validation = self.validate_variable(variable, show_progress=show_progress)
            report.variables[variable] = validation

        report.total_time_seconds = time.perf_counter() - start_time

        if show_progress:
            self.print_summary(report)

        return report

    def print_summary(self, report: ValidationReport):
        """Print summary table of validation results."""
        self.console.print()
        self.console.print("[bold]Summary[/bold]")

        table = Table()
        table.add_column("Variable")
        table.add_column("Match Rate")
        table.add_column("MAE")
        table.add_column("Status")
        table.add_column("Cosilico Time")
        table.add_column("Speedup")

        for var_name, validation in report.variables.items():
            if not validation.comparisons:
                table.add_row(
                    var_name,
                    "N/A",
                    "N/A",
                    "[yellow]NO DATA[/yellow]",
                    f"{validation.cosilico_time_ms:.1f}ms",
                    "-",
                )
                continue

            # Use first comparison (typically PolicyEngine)
            comp = list(validation.comparisons.values())[0]
            ref_name = list(validation.comparisons.keys())[0]
            ref_time = validation.reference_times_ms.get(ref_name, 0)

            status = "[green]PASS[/green]" if validation.passed else "[red]FAIL[/red]"
            speedup = ref_time / validation.cosilico_time_ms if validation.cosilico_time_ms > 0 else 0

            table.add_row(
                var_name,
                f"{comp.match_rate:.1%}",
                f"${comp.mean_absolute_error:.2f}",
                status,
                f"{validation.cosilico_time_ms:.1f}ms",
                f"{speedup:.1f}x" if speedup > 0 else "-",
            )

        self.console.print(table)

        # Overall stats
        self.console.print()
        self.console.print(f"[bold]Overall: {report.n_passed}/{len(report.variables)} passed "
                          f"({report.pass_rate:.0%})[/bold]")
        self.console.print(f"Total time: {report.total_time_seconds:.1f}s")


def run_validation(
    variables: Optional[List[str]] = None,
    year: int = 2024,
    tolerance: float = 15.0,
) -> ValidationReport:
    """Convenience function to run validation with default settings.

    Args:
        variables: Variables to validate (default: all available)
        year: Tax year
        tolerance: Dollar tolerance for matching

    Returns:
        ValidationReport
    """
    validator = MicrodataValidator(year=year, tolerance=tolerance)
    return validator.run(variables=variables)


# CLI entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate Cosilico encodings on microdata")
    parser.add_argument("--variables", nargs="+", help="Variables to validate")
    parser.add_argument("--year", type=int, default=2024, help="Tax year")
    parser.add_argument("--tolerance", type=float, default=15.0, help="Dollar tolerance")
    args = parser.parse_args()

    report = run_validation(
        variables=args.variables,
        year=args.year,
        tolerance=args.tolerance,
    )

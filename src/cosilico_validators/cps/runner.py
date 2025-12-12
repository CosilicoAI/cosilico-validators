"""CPS-scale validation runner comparing Cosilico against PE and TAXSIM."""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys


@dataclass
class VariableConfig:
    """Configuration for a variable to validate."""

    name: str
    section: str  # e.g., "26/24" for CTC
    title: str
    cosilico_file: str  # Path to .cosilico file relative to cosilico-us
    cosilico_variable: str  # Variable name in .cosilico file
    pe_variable: str  # PolicyEngine variable name
    taxsim_variable: Optional[str] = None  # TAXSIM output column
    tolerance: float = 15.0  # Dollar tolerance for matching


@dataclass
class ComparisonResult:
    """Result comparing Cosilico to a single validator."""

    validator: str
    n_compared: int
    n_matches: int
    match_rate: float
    mean_absolute_error: float
    mismatches: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of validating a single variable."""

    variable: VariableConfig
    n_tax_units: int
    cosilico_values: Optional[np.ndarray] = None
    pe_comparison: Optional[ComparisonResult] = None
    taxsim_comparison: Optional[ComparisonResult] = None


class CPSValidationRunner:
    """
    Run CPS-scale validation comparing Cosilico encodings against PE and TAXSIM.

    Uses PolicyEngine's enhanced CPS via Microsimulation for data,
    then compares Cosilico's vectorized calculations against PE and TAXSIM.
    """

    # Variable configurations - maps Cosilico files to PE/TAXSIM variables
    VARIABLES = [
        VariableConfig(
            name="ctc",
            section="26/24",
            title="Child Tax Credit",
            cosilico_file="26/24/a/credit.cosilico",
            cosilico_variable="child_tax_credit",
            pe_variable="ctc",
            taxsim_variable="v22",
        ),
        VariableConfig(
            name="standard_deduction",
            section="26/63",
            title="Standard Deduction",
            cosilico_file="26/63/c/standard_deduction.cosilico",
            cosilico_variable="standard_deduction",
            pe_variable="standard_deduction",
            taxsim_variable=None,
        ),
        VariableConfig(
            name="eitc",
            section="26/32",
            title="Earned Income Tax Credit",
            cosilico_file="26/32/a/credit.cosilico",  # May need to create
            cosilico_variable="earned_income_credit",
            pe_variable="eitc",
            taxsim_variable="v25",
        ),
        VariableConfig(
            name="snap",
            section="7/2017",
            title="SNAP Allotment",
            cosilico_file="7/2017/a/allotment.cosilico",
            cosilico_variable="snap_allotment",
            pe_variable="snap",
            taxsim_variable=None,  # TAXSIM doesn't cover SNAP
        ),
    ]

    def __init__(
        self,
        year: int = 2024,
        tolerance: float = 15.0,
        dataset: str = "enhanced_cps",
        cosilico_us_path: Optional[Path] = None,
    ):
        """
        Initialize CPS validation runner.

        Args:
            year: Tax year to validate
            tolerance: Dollar tolerance for matching
            dataset: PolicyEngine dataset name
            cosilico_us_path: Path to cosilico-us repo (default: ~/CosilicoAI/cosilico-us)
        """
        self.year = year
        self.tolerance = tolerance
        self.dataset = dataset
        self.cosilico_us_path = cosilico_us_path or Path.home() / "CosilicoAI/cosilico-us"
        self.results: Dict[str, ValidationResult] = {}
        self._sim = None
        self._cosilico_executor = None

    def _get_pe_simulation(self):
        """Get or create PolicyEngine Microsimulation."""
        if self._sim is None:
            try:
                from policyengine_us import Microsimulation
            except ImportError:
                raise ImportError(
                    "policyengine-us required. Install with: pip install policyengine-us"
                )

            print(f"Loading {self.dataset} dataset...")
            self._sim = Microsimulation(dataset=self.dataset)
            n_people = self._sim.calculate("person_id", self.year).size
            print(f"Loaded {n_people:,} people")

        return self._sim

    def _get_cosilico_executor(self):
        """Get or create Cosilico vectorized executor."""
        if self._cosilico_executor is None:
            # Add cosilico-engine to path if needed
            engine_path = Path.home() / "CosilicoAI/cosilico-engine/src"
            if str(engine_path) not in sys.path:
                sys.path.insert(0, str(engine_path))

            try:
                from cosilico.vectorized_executor import VectorizedExecutor
                from cosilico.dsl_executor import get_default_parameters
            except ImportError:
                raise ImportError(
                    "cosilico-engine required. Ensure ~/CosilicoAI/cosilico-engine exists."
                )

            params = get_default_parameters()
            self._cosilico_executor = VectorizedExecutor(parameters=params)

        return self._cosilico_executor

    def _extract_inputs_from_pe(self) -> Dict[str, np.ndarray]:
        """Extract input variables from PolicyEngine simulation as numpy arrays."""
        sim = self._get_pe_simulation()

        # Get entity mappings
        tax_unit_id = sim.calculate("tax_unit_id", self.year)
        person_tax_unit_id = sim.calculate("person_tax_unit_id", self.year)

        # Extract common inputs at person level
        inputs = {
            # Demographics
            "age": sim.calculate("age", self.year),
            "is_tax_unit_head": sim.calculate("is_tax_unit_head", self.year),
            "is_tax_unit_spouse": sim.calculate("is_tax_unit_spouse", self.year),
            "is_tax_unit_dependent": sim.calculate("is_tax_unit_dependent", self.year),

            # Income
            "earned_income": sim.calculate("earned_income", self.year),
            "wages": sim.calculate("employment_income", self.year),
            "adjusted_gross_income": sim.calculate("adjusted_gross_income", self.year),

            # Filing
            "filing_status": sim.calculate("filing_status", self.year),

            # Children
            "is_child": sim.calculate("is_child", self.year),
            "is_ctc_qualifying_child": sim.calculate("is_ctc_qualifying_child", self.year),
        }

        # Entity mappings for aggregation
        inputs["_person_tax_unit_id"] = person_tax_unit_id
        inputs["_tax_unit_id"] = tax_unit_id

        return inputs

    def _run_cosilico(self, variable: VariableConfig) -> Optional[np.ndarray]:
        """Run Cosilico on CPS data for a specific variable."""
        cosilico_path = self.cosilico_us_path / variable.cosilico_file

        if not cosilico_path.exists():
            print(f"  {variable.name}: Cosilico file not found at {cosilico_path}")
            return None

        try:
            executor = self._get_cosilico_executor()
            inputs = self._extract_inputs_from_pe()

            with open(cosilico_path) as f:
                code = f.read()

            # Execute vectorized
            results = executor.execute(
                code=code,
                inputs=inputs,
                output_variables=[variable.cosilico_variable],
            )

            return results.get(variable.cosilico_variable)

        except Exception as e:
            print(f"  {variable.name}: Cosilico execution error - {e}")
            return None

    def _run_policyengine(self, variable: VariableConfig) -> np.ndarray:
        """Get PolicyEngine values for a variable."""
        sim = self._get_pe_simulation()
        return sim.calculate(variable.pe_variable, self.year)

    def _run_taxsim(self, variable: VariableConfig) -> Optional[np.ndarray]:
        """Run TAXSIM for a variable (if applicable)."""
        if variable.taxsim_variable is None:
            return None

        # TODO: Implement TAXSIM comparison
        # This requires converting CPS data to TAXSIM format and calling the API
        # For now, return None
        return None

    def _compare(
        self,
        cosilico_values: np.ndarray,
        other_values: np.ndarray,
        validator_name: str,
    ) -> ComparisonResult:
        """Compare Cosilico values against another validator."""
        # Ensure same shape
        if len(cosilico_values) != len(other_values):
            # May need to aggregate - for now just compare matching lengths
            min_len = min(len(cosilico_values), len(other_values))
            cosilico_values = cosilico_values[:min_len]
            other_values = other_values[:min_len]

        # Calculate differences
        diff = np.abs(cosilico_values - other_values)
        matches = diff <= self.tolerance
        n_matches = int(matches.sum())
        n_compared = len(diff)

        # Find mismatches for analysis
        mismatch_indices = np.where(~matches)[0]
        mismatches = []
        for idx in mismatch_indices[:100]:  # Limit to 100 examples
            mismatches.append({
                "index": int(idx),
                "cosilico": float(cosilico_values[idx]),
                "validator": float(other_values[idx]),
                "difference": float(diff[idx]),
            })

        return ComparisonResult(
            validator=validator_name,
            n_compared=n_compared,
            n_matches=n_matches,
            match_rate=n_matches / n_compared if n_compared > 0 else 0,
            mean_absolute_error=float(diff.mean()),
            mismatches=mismatches,
        )

    def run_variable(self, variable: VariableConfig) -> ValidationResult:
        """Run validation for a single variable."""
        print(f"\nValidating {variable.title} ({variable.section})...")

        # Run Cosilico
        print(f"  Running Cosilico ({variable.cosilico_file})...")
        cosilico_values = self._run_cosilico(variable)

        # Run PolicyEngine
        print(f"  Running PolicyEngine ({variable.pe_variable})...")
        pe_values = self._run_policyengine(variable)

        # Get tax unit count
        sim = self._get_pe_simulation()
        n_tax_units = len(np.unique(sim.calculate("tax_unit_id", self.year)))

        result = ValidationResult(
            variable=variable,
            n_tax_units=n_tax_units,
            cosilico_values=cosilico_values,
        )

        # Compare Cosilico vs PE
        if cosilico_values is not None:
            print(f"  Comparing Cosilico vs PolicyEngine...")
            result.pe_comparison = self._compare(cosilico_values, pe_values, "policyengine")
            print(f"    Match rate: {result.pe_comparison.match_rate:.1%}")
            print(f"    MAE: ${result.pe_comparison.mean_absolute_error:.2f}")

        # Compare Cosilico vs TAXSIM
        if variable.taxsim_variable and cosilico_values is not None:
            print(f"  Running TAXSIM ({variable.taxsim_variable})...")
            taxsim_values = self._run_taxsim(variable)
            if taxsim_values is not None:
                print(f"  Comparing Cosilico vs TAXSIM...")
                result.taxsim_comparison = self._compare(
                    cosilico_values, taxsim_values, "taxsim"
                )
                print(f"    Match rate: {result.taxsim_comparison.match_rate:.1%}")

        return result

    def run(self) -> Dict[str, ValidationResult]:
        """Run full CPS validation for all variables."""
        print(f"Starting CPS validation for {self.year}...")
        print(f"Cosilico encodings: {self.cosilico_us_path}")

        # Initialize PE simulation (loads CPS data)
        sim = self._get_pe_simulation()
        n_tax_units = len(np.unique(sim.calculate("tax_unit_id", self.year)))
        n_households = len(np.unique(sim.calculate("household_id", self.year)))
        print(f"\nDataset: {n_households:,} households, {n_tax_units:,} tax units")

        # Run each variable
        for variable in self.VARIABLES:
            self.results[variable.name] = self.run_variable(variable)

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        for name, result in self.results.items():
            if result.pe_comparison:
                print(f"{result.variable.title}:")
                print(f"  vs PolicyEngine: {result.pe_comparison.match_rate:.1%} match")
                if result.taxsim_comparison:
                    print(f"  vs TAXSIM: {result.taxsim_comparison.match_rate:.1%} match")
            else:
                print(f"{result.variable.title}: Cosilico not available")

        return self.results

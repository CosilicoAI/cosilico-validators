"""CPS-scale validation runner comparing Cosilico against PE and TAXSIM."""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys
import time

from ..variable_mapping import (
    VARIABLE_MAPPINGS,
    VariableMapping,
    get_all_required_inputs,
    discover_cosilico_files,
)


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

    @classmethod
    def from_mapping(cls, name: str, mapping: VariableMapping) -> "VariableConfig":
        """Create VariableConfig from a VariableMapping."""
        # Extract section from statute (e.g., "26 USC § 1411" -> "26/1411")
        section = mapping.statute.replace("26 USC § ", "26/").replace("7 USC § ", "7/")
        section = section.split("(")[0]  # Remove subsection refs

        return cls(
            name=name,
            section=section,
            title=mapping.title,
            cosilico_file=mapping.cosilico_file,
            cosilico_variable=mapping.cosilico_variable,
            pe_variable=mapping.pe_variable or "",
            taxsim_variable=mapping.taxsim_variable,
            tolerance=mapping.tolerance,
        )


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
class SpeedMetrics:
    """Speed benchmark results for a variable."""

    cosilico_time_ms: float  # Total execution time in milliseconds
    pe_time_ms: float  # PolicyEngine execution time in milliseconds
    n_cases: int  # Number of cases processed
    cosilico_per_case_us: float  # Microseconds per case for Cosilico
    pe_per_case_us: float  # Microseconds per case for PE
    speedup: float  # PE time / Cosilico time (how many times faster)
    cosilico_throughput: float  # Cases per second for Cosilico
    pe_throughput: float  # Cases per second for PolicyEngine


@dataclass
class ValidationResult:
    """Result of validating a single variable."""

    variable: VariableConfig
    n_tax_units: int
    cosilico_values: Optional[np.ndarray] = None
    pe_comparison: Optional[ComparisonResult] = None
    taxsim_comparison: Optional[ComparisonResult] = None
    speed_metrics: Optional[SpeedMetrics] = None


class CPSValidationRunner:
    """
    Run CPS-scale validation comparing Cosilico encodings against PE and TAXSIM.

    Uses PolicyEngine's enhanced CPS via Microsimulation for data,
    then compares Cosilico's vectorized calculations against PE and TAXSIM.

    Variables to validate are defined in variable_mapping.py - the single source
    of truth for mapping Cosilico variables to PE/TAXSIM equivalents.
    """

    @classmethod
    def get_variables(cls) -> List[VariableConfig]:
        """Get variable configurations from the central mapping."""
        return [
            VariableConfig.from_mapping(name, mapping)
            for name, mapping in VARIABLE_MAPPINGS.items()
            if mapping.pe_variable  # Only include variables with PE mappings
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
        self._entity_index = None

    def _get_pe_simulation(self):
        """Get or create PolicyEngine Microsimulation."""
        if self._sim is None:
            try:
                from policyengine_us import Microsimulation
            except ImportError:
                raise ImportError(
                    "policyengine-us required. Install with: pip install policyengine-us"
                )

            print(f"Loading default dataset...")
            self._sim = Microsimulation()
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

    def _get_entity_index(self):
        """Get or create EntityIndex from PolicyEngine simulation for entity aggregation."""
        if self._entity_index is not None:
            return self._entity_index

        # Add cosilico-engine to path if needed
        engine_path = Path.home() / "CosilicoAI/cosilico-engine/src"
        if str(engine_path) not in sys.path:
            sys.path.insert(0, str(engine_path))

        from cosilico.vectorized_executor import EntityIndex

        sim = self._get_pe_simulation()

        # Get entity IDs
        person_tax_unit_id = sim.calculate("person_tax_unit_id", self.year)
        tax_unit_id = sim.calculate("tax_unit_id", self.year)
        tax_unit_household_id = sim.calculate("tax_unit_household_id", self.year)
        household_id = sim.calculate("household_id", self.year)

        # Build person -> tax_unit mapping (index into unique tax_unit_ids)
        unique_tax_unit_ids = np.unique(tax_unit_id)
        tax_unit_id_to_idx = {tid: i for i, tid in enumerate(unique_tax_unit_ids)}
        person_to_tax_unit = np.array([tax_unit_id_to_idx[tid] for tid in person_tax_unit_id])

        # Build tax_unit -> household mapping
        unique_household_ids = np.unique(household_id)
        household_id_to_idx = {hid: i for i, hid in enumerate(unique_household_ids)}
        tax_unit_to_household = np.array([
            household_id_to_idx[hid] for hid in tax_unit_household_id
        ])

        self._entity_index = EntityIndex(
            person_to_tax_unit=person_to_tax_unit,
            tax_unit_to_household=tax_unit_to_household,
            n_persons=len(person_tax_unit_id),
            n_tax_units=len(unique_tax_unit_ids),
            n_households=len(unique_household_ids),
        )

        return self._entity_index

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

            # Income - employment
            "earned_income": sim.calculate("earned_income", self.year),
            "wages": sim.calculate("employment_income", self.year),
            "employment_income": sim.calculate("employment_income", self.year),
            "self_employment_income": sim.calculate("self_employment_income", self.year),
            "adjusted_gross_income": sim.calculate("adjusted_gross_income", self.year),

            # Income - investment (for NIIT)
            "interest_income": sim.calculate("interest_income", self.year),
            "dividend_income": sim.calculate("dividend_income", self.year),
            "long_term_capital_gains": sim.calculate("long_term_capital_gains", self.year),
            "short_term_capital_gains": sim.calculate("short_term_capital_gains", self.year),
            "rental_income": sim.calculate("rental_income", self.year),

            # Filing
            "filing_status": sim.calculate("filing_status", self.year),

            # Children (tax unit level)
            "is_child": sim.calculate("is_child", self.year),
            "ctc_qualifying_children": sim.calculate("ctc_qualifying_children", self.year),
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
            entity_index = self._get_entity_index()

            with open(cosilico_path) as f:
                code = f.read()

            # Execute vectorized with entity index for aggregation support
            results = executor.execute(
                code=code,
                inputs=inputs,
                entity_index=entity_index,
                output_variables=[variable.cosilico_variable],
            )

            return results.get(variable.cosilico_variable)

        except Exception as e:
            print(f"  {variable.name}: Cosilico execution error - {e}")
            import traceback
            traceback.print_exc()
            return None

    def _run_policyengine(self, variable: VariableConfig) -> np.ndarray:
        """Get PolicyEngine values for a variable."""
        sim = self._get_pe_simulation()
        return sim.calculate(variable.pe_variable, self.year)

    def _run_taxsim(self, variable: VariableConfig) -> Optional[np.ndarray]:
        """Run TAXSIM for a variable."""
        if variable.taxsim_variable is None:
            return None

        # Cache TAXSIM results across variables
        if not hasattr(self, "_taxsim_results"):
            self._taxsim_results = self._run_taxsim_batch()

        if self._taxsim_results is None:
            return None

        # Extract the variable column
        if variable.taxsim_variable in self._taxsim_results.columns:
            return self._taxsim_results[variable.taxsim_variable].values
        else:
            print(f"    Variable {variable.taxsim_variable} not in TAXSIM output")
            return None

    def _run_taxsim_batch(self) -> Optional[pd.DataFrame]:
        """Run TAXSIM on CPS data using ported batch runner."""
        try:
            from .taxsim_batch import TaxsimBatchRunner, load_cps_taxsim_format
        except ImportError as e:
            print(f"    TAXSIM batch module not available: {e}")
            return None

        try:
            # Load CPS in TAXSIM format
            print(f"    Loading CPS for TAXSIM...")
            cps_df = load_cps_taxsim_format()

            # Adjust year (TAXSIM-35 only supports up to 2023)
            if "year" in cps_df.columns:
                taxsim_year = min(self.year, 2023)
                cps_df["year"] = taxsim_year

            # Run TAXSIM
            runner = TaxsimBatchRunner()
            results = runner.run(cps_df, show_progress=True)

            return results

        except FileNotFoundError as e:
            print(f"    {e}")
            return None
        except Exception as e:
            print(f"    TAXSIM batch run failed: {e}")
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

        # Run Cosilico with timing
        print(f"  Running Cosilico ({variable.cosilico_file})...")
        cosilico_start = time.perf_counter()
        cosilico_values = self._run_cosilico(variable)
        cosilico_time = time.perf_counter() - cosilico_start

        # Run PolicyEngine with timing
        print(f"  Running PolicyEngine ({variable.pe_variable})...")
        pe_start = time.perf_counter()
        pe_values = self._run_policyengine(variable)
        pe_time = time.perf_counter() - pe_start

        # Get tax unit count
        sim = self._get_pe_simulation()
        n_tax_units = len(np.unique(sim.calculate("tax_unit_id", self.year)))

        # Calculate speed metrics
        speed_metrics = None
        if cosilico_values is not None and cosilico_time > 0:
            n_cases = len(cosilico_values)
            cosilico_ms = cosilico_time * 1000
            pe_ms = pe_time * 1000
            cosilico_per_case_us = (cosilico_time * 1_000_000) / n_cases
            pe_per_case_us = (pe_time * 1_000_000) / n_cases
            speedup = pe_time / cosilico_time if cosilico_time > 0 else 0
            cosilico_throughput = n_cases / cosilico_time if cosilico_time > 0 else 0
            pe_throughput = n_cases / pe_time if pe_time > 0 else 0

            speed_metrics = SpeedMetrics(
                cosilico_time_ms=cosilico_ms,
                pe_time_ms=pe_ms,
                n_cases=n_cases,
                cosilico_per_case_us=cosilico_per_case_us,
                pe_per_case_us=pe_per_case_us,
                speedup=speedup,
                cosilico_throughput=cosilico_throughput,
                pe_throughput=pe_throughput,
            )
            print(f"  Speed: Cosilico {cosilico_ms:.1f}ms, PE {pe_ms:.1f}ms ({speedup:.0f}x faster)")

        result = ValidationResult(
            variable=variable,
            n_tax_units=n_tax_units,
            cosilico_values=cosilico_values,
            speed_metrics=speed_metrics,
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

        # Run each variable from central mapping
        for variable in self.get_variables():
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
                if result.speed_metrics:
                    print(f"  Speed: {result.speed_metrics.speedup:.0f}x faster than PE")
            else:
                print(f"{result.variable.title}: Cosilico not available")

        # Speed summary
        total_cosilico_ms = sum(
            r.speed_metrics.cosilico_time_ms
            for r in self.results.values()
            if r.speed_metrics
        )
        total_pe_ms = sum(
            r.speed_metrics.pe_time_ms
            for r in self.results.values()
            if r.speed_metrics
        )
        if total_cosilico_ms > 0:
            print(f"\nOverall Speed: {total_pe_ms / total_cosilico_ms:.0f}x faster than PE")
            print(f"  Cosilico: {total_cosilico_ms:.1f}ms total")
            print(f"  PolicyEngine: {total_pe_ms:.1f}ms total")

        return self.results

"""CPS-scale validation runner using PolicyEngine's enhanced CPS."""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class VariableConfig:
    """Configuration for a variable to validate."""

    name: str
    section: str  # e.g., "26/24" for CTC
    title: str
    pe_variable: str  # PolicyEngine variable name
    taxsim_variable: Optional[str] = None  # TAXSIM output column (if applicable)
    tolerance: float = 15.0  # Dollar tolerance for matching


@dataclass
class ValidationResult:
    """Result of validating a single variable."""

    variable: VariableConfig
    households: int
    pe_results: Dict[str, int] = field(default_factory=dict)  # validator -> matches
    taxsim_results: Optional[Dict[str, int]] = None
    mismatches: List[Dict[str, Any]] = field(default_factory=list)
    mean_absolute_error: float = 0.0


class CPSValidationRunner:
    """
    Run CPS-scale validation using PolicyEngine's enhanced CPS.

    Uses Microsimulation to automatically load and weight CPS data.
    """

    # Default variable configurations
    VARIABLES = [
        VariableConfig(
            name="ctc",
            section="26/24",
            title="Child Tax Credit",
            pe_variable="ctc",
            taxsim_variable="v22",  # CTC in TAXSIM
        ),
        VariableConfig(
            name="standard_deduction",
            section="26/63",
            title="Standard Deduction",
            pe_variable="standard_deduction",
            taxsim_variable=None,  # Not directly in TAXSIM output
        ),
        VariableConfig(
            name="eitc",
            section="26/32",
            title="Earned Income Tax Credit",
            pe_variable="eitc",
            taxsim_variable="v25",  # EITC in TAXSIM
        ),
        VariableConfig(
            name="snap",
            section="7/2017",
            title="SNAP Allotment",
            pe_variable="snap",
            taxsim_variable=None,  # TAXSIM doesn't cover SNAP
        ),
    ]

    def __init__(
        self,
        year: int = 2024,
        tolerance: float = 15.0,
        dataset: str = "enhanced_cps",
    ):
        """
        Initialize CPS validation runner.

        Args:
            year: Tax year to validate
            tolerance: Dollar tolerance for matching
            dataset: PolicyEngine dataset to use (default: enhanced_cps)
        """
        self.year = year
        self.tolerance = tolerance
        self.dataset = dataset
        self.results: Dict[str, ValidationResult] = {}
        self._sim = None

    def _get_simulation(self):
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
            print(f"Loaded {self._sim.calculate('person_id').size} people")

        return self._sim

    def run_policyengine(self) -> pd.DataFrame:
        """Run PolicyEngine on enhanced CPS."""
        sim = self._get_simulation()

        # Get tax unit IDs for grouping
        tax_unit_id = sim.calculate("tax_unit_id", self.year)
        unique_tax_units = np.unique(tax_unit_id)
        n_tax_units = len(unique_tax_units)
        print(f"Calculating for {n_tax_units:,} tax units...")

        results = {"tax_unit_id": unique_tax_units}

        for var in self.VARIABLES:
            try:
                # Calculate variable at tax unit level
                values = sim.calculate(var.pe_variable, self.year)
                # Group by tax unit (most tax variables are already at tax_unit level)
                if len(values) == n_tax_units:
                    results[var.pe_variable] = values
                else:
                    # Aggregate to tax unit level
                    df = pd.DataFrame({
                        "tax_unit_id": tax_unit_id,
                        "value": values
                    })
                    agg = df.groupby("tax_unit_id")["value"].sum()
                    results[var.pe_variable] = agg.reindex(unique_tax_units).values
                print(f"  {var.pe_variable}: computed")
            except Exception as e:
                print(f"  {var.pe_variable}: ERROR - {e}")
                results[var.pe_variable] = np.full(n_tax_units, np.nan)

        return pd.DataFrame(results)

    def get_household_count(self) -> int:
        """Get number of households in the dataset."""
        sim = self._get_simulation()
        household_id = sim.calculate("household_id", self.year)
        return len(np.unique(household_id))

    def get_tax_unit_count(self) -> int:
        """Get number of tax units in the dataset."""
        sim = self._get_simulation()
        tax_unit_id = sim.calculate("tax_unit_id", self.year)
        return len(np.unique(tax_unit_id))

    def compare_results(
        self,
        pe_results: pd.DataFrame,
        variable: VariableConfig,
    ) -> ValidationResult:
        """Analyze PE results for a variable."""
        # Get values for this variable
        values = pe_results[variable.pe_variable]
        valid_mask = ~np.isnan(values)
        n_valid = valid_mask.sum()
        n_total = len(values)

        # Calculate statistics
        valid_values = values[valid_mask]
        nonzero_mask = valid_values != 0
        n_nonzero = nonzero_mask.sum()

        result = ValidationResult(
            variable=variable,
            households=n_total,
            pe_results={
                "policyengine": int(n_valid),
                "nonzero": int(n_nonzero),
            },
            mean_absolute_error=0.0,  # No comparison target yet
        )

        # Summary statistics
        if n_nonzero > 0:
            nonzero_values = valid_values[nonzero_mask]
            result.mismatches.append({
                "type": "summary",
                "count": int(n_nonzero),
                "mean": float(nonzero_values.mean()),
                "median": float(np.median(nonzero_values)),
                "min": float(nonzero_values.min()),
                "max": float(nonzero_values.max()),
                "total": float(nonzero_values.sum()),
            })

        return result

    def run(self) -> Dict[str, ValidationResult]:
        """Run full CPS validation."""
        print(f"Starting CPS validation for {self.year}...")

        print("\nRunning PolicyEngine calculations...")
        pe_results = self.run_policyengine()

        n_households = self.get_household_count()
        n_tax_units = self.get_tax_unit_count()
        print(f"\nDataset: {n_households:,} households, {n_tax_units:,} tax units")

        print("\nAnalyzing results...")
        for var in self.VARIABLES:
            self.results[var.name] = self.compare_results(pe_results, var)
            r = self.results[var.name]
            print(f"  {var.title}: {r.pe_results.get('nonzero', 0):,} nonzero values")

        return self.results

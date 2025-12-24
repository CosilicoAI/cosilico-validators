"""Base abstractions for microdata validation.

This module defines the core interfaces that all microdata sources
and calculators must implement, enabling clean comparison between
Cosilico encodings and reference implementations.

Design principles:
1. Clear separation between data source and calculation engine
2. Explicit entity relationships for proper aggregation
3. Lazy computation with caching for performance
4. Type-safe interfaces with numpy arrays
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from pathlib import Path
import numpy as np


@dataclass
class EntityIndex:
    """Maps relationships between entity levels for aggregation.

    Tax calculations often require aggregating from person level
    (wages, age) to tax unit level (filing status, EITC) to
    household level (SNAP).

    Attributes:
        person_to_tax_unit: For each person, the index of their tax unit
        tax_unit_to_household: For each tax unit, the index of their household
        n_persons: Total number of person records
        n_tax_units: Total number of tax units
        n_households: Total number of households
    """

    person_to_tax_unit: np.ndarray  # shape: [n_persons], dtype: int
    tax_unit_to_household: np.ndarray  # shape: [n_tax_units], dtype: int
    n_persons: int
    n_tax_units: int
    n_households: int

    def aggregate_to_tax_unit(
        self,
        person_values: np.ndarray,
        agg_func: str = "sum"
    ) -> np.ndarray:
        """Aggregate person-level values to tax unit level.

        Args:
            person_values: Array of shape [n_persons]
            agg_func: Aggregation function - "sum", "max", "min", "any", "all"

        Returns:
            Array of shape [n_tax_units]
        """
        if agg_func == "sum":
            return np.bincount(
                self.person_to_tax_unit,
                weights=person_values,
                minlength=self.n_tax_units
            )
        elif agg_func == "max":
            result = np.full(self.n_tax_units, -np.inf)
            np.maximum.at(result, self.person_to_tax_unit, person_values)
            result[result == -np.inf] = 0
            return result
        elif agg_func == "min":
            result = np.full(self.n_tax_units, np.inf)
            np.minimum.at(result, self.person_to_tax_unit, person_values)
            result[result == np.inf] = 0
            return result
        elif agg_func == "any":
            return np.bincount(
                self.person_to_tax_unit,
                weights=person_values.astype(float),
                minlength=self.n_tax_units
            ) > 0
        elif agg_func == "all":
            true_count = np.bincount(
                self.person_to_tax_unit,
                weights=person_values.astype(float),
                minlength=self.n_tax_units
            )
            total_count = np.bincount(
                self.person_to_tax_unit,
                minlength=self.n_tax_units
            )
            return true_count == total_count
        else:
            raise ValueError(f"Unknown aggregation function: {agg_func}")

    def broadcast_to_person(self, tax_unit_values: np.ndarray) -> np.ndarray:
        """Broadcast tax unit values to person level.

        Args:
            tax_unit_values: Array of shape [n_tax_units]

        Returns:
            Array of shape [n_persons]
        """
        return tax_unit_values[self.person_to_tax_unit]


@dataclass
class CalculationResult:
    """Result of calculating a variable on microdata.

    Includes the computed values, timing metrics, and any errors.
    """

    variable: str
    values: Optional[np.ndarray]  # None if calculation failed
    entity: str  # "person", "tax_unit", or "household"
    n_records: int
    calculation_time_ms: float
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.values is not None and self.error is None


class MicrodataSource(ABC):
    """Abstract base class for microdata sources.

    A MicrodataSource provides:
    1. Input variables as numpy arrays
    2. Entity structure (person, tax_unit, household relationships)
    3. Weights for population-representative calculations

    Implementations: PolicyEngineMicrodataSource, CensusCPSSource, etc.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this data source."""
        pass

    @property
    @abstractmethod
    def year(self) -> int:
        """Tax year of the microdata."""
        pass

    @property
    @abstractmethod
    def n_persons(self) -> int:
        """Number of person records."""
        pass

    @property
    @abstractmethod
    def n_tax_units(self) -> int:
        """Number of tax unit records."""
        pass

    @property
    @abstractmethod
    def n_households(self) -> int:
        """Number of household records."""
        pass

    @abstractmethod
    def get_entity_index(self) -> EntityIndex:
        """Get entity relationship mappings.

        Returns:
            EntityIndex with person->tax_unit->household mappings
        """
        pass

    @abstractmethod
    def get_variable(self, name: str, entity: str = "person") -> np.ndarray:
        """Get a variable as a numpy array.

        Args:
            name: Variable name (e.g., "employment_income", "age")
            entity: Entity level - "person", "tax_unit", or "household"

        Returns:
            Numpy array of values for the requested entity level

        Raises:
            KeyError: If variable is not available
        """
        pass

    @abstractmethod
    def get_weights(self, entity: str = "person") -> np.ndarray:
        """Get sampling weights for population-representative calculations.

        Args:
            entity: Entity level for weights

        Returns:
            Numpy array of weights
        """
        pass

    @abstractmethod
    def available_variables(self, entity: Optional[str] = None) -> Set[str]:
        """Get set of available variable names.

        Args:
            entity: If specified, only return variables for this entity level

        Returns:
            Set of variable names
        """
        pass

    def get_inputs(self, variable_names: List[str]) -> Dict[str, np.ndarray]:
        """Get multiple variables as a dictionary.

        Convenience method that calls get_variable for each name.

        Args:
            variable_names: List of variable names to retrieve

        Returns:
            Dict mapping variable names to numpy arrays
        """
        inputs = {}
        for name in variable_names:
            try:
                inputs[name] = self.get_variable(name)
            except KeyError:
                # Variable not available - skip silently
                pass
        return inputs


class Calculator(ABC):
    """Abstract base class for tax/benefit calculators.

    A Calculator computes tax and benefit variables on microdata.
    Different implementations use different engines:
    - CosilicoCalculator: Uses Cosilico DSL executor
    - PolicyEngineCalculator: Uses PolicyEngine microsimulation
    - TAXSIMCalculator: Uses NBER TAXSIM web service

    This abstraction enables apples-to-apples comparison between
    implementations.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this calculator."""
        pass

    @property
    @abstractmethod
    def supported_variables(self) -> Set[str]:
        """Set of variables this calculator can compute."""
        pass

    @abstractmethod
    def calculate(
        self,
        variable: str,
        source: MicrodataSource,
        year: Optional[int] = None,
    ) -> CalculationResult:
        """Calculate a variable on microdata.

        Args:
            variable: Variable to calculate (e.g., "eitc", "net_investment_income_tax")
            source: MicrodataSource providing inputs
            year: Tax year (defaults to source.year)

        Returns:
            CalculationResult with computed values or error
        """
        pass

    def supports_variable(self, variable: str) -> bool:
        """Check if this calculator supports a variable."""
        return variable.lower() in {v.lower() for v in self.supported_variables}

    def batch_calculate(
        self,
        variables: List[str],
        source: MicrodataSource,
        year: Optional[int] = None,
    ) -> Dict[str, CalculationResult]:
        """Calculate multiple variables.

        Default implementation calls calculate() for each variable.
        Subclasses can override for batch optimization.

        Args:
            variables: List of variable names
            source: MicrodataSource providing inputs
            year: Tax year

        Returns:
            Dict mapping variable names to CalculationResults
        """
        results = {}
        for var in variables:
            results[var] = self.calculate(var, source, year)
        return results


@dataclass
class ComparisonResult:
    """Result of comparing two calculators on the same microdata."""

    variable: str
    source_name: str
    calculator_a: str
    calculator_b: str
    n_compared: int
    n_matches: int
    match_rate: float
    mean_absolute_error: float
    tolerance: float
    mismatches: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True if match rate exceeds 99%."""
        return self.match_rate >= 0.99


def compare_calculators(
    variable: str,
    calc_a: Calculator,
    calc_b: Calculator,
    source: MicrodataSource,
    tolerance: float = 15.0,
    year: Optional[int] = None,
    max_mismatches: int = 100,
) -> ComparisonResult:
    """Compare two calculators on the same microdata.

    Args:
        variable: Variable to compare
        calc_a: First calculator (typically Cosilico)
        calc_b: Second calculator (typically PolicyEngine)
        source: MicrodataSource with inputs
        tolerance: Dollar tolerance for matching
        year: Tax year
        max_mismatches: Maximum number of mismatches to record

    Returns:
        ComparisonResult with match statistics
    """
    result_a = calc_a.calculate(variable, source, year)
    result_b = calc_b.calculate(variable, source, year)

    if not result_a.success:
        return ComparisonResult(
            variable=variable,
            source_name=source.name,
            calculator_a=calc_a.name,
            calculator_b=calc_b.name,
            n_compared=0,
            n_matches=0,
            match_rate=0.0,
            mean_absolute_error=float("inf"),
            tolerance=tolerance,
            mismatches=[{"error": f"{calc_a.name} failed: {result_a.error}"}],
        )

    if not result_b.success:
        return ComparisonResult(
            variable=variable,
            source_name=source.name,
            calculator_a=calc_a.name,
            calculator_b=calc_b.name,
            n_compared=0,
            n_matches=0,
            match_rate=0.0,
            mean_absolute_error=float("inf"),
            tolerance=tolerance,
            mismatches=[{"error": f"{calc_b.name} failed: {result_b.error}"}],
        )

    values_a = result_a.values
    values_b = result_b.values

    # Handle different array lengths (different entity levels)
    if len(values_a) != len(values_b):
        min_len = min(len(values_a), len(values_b))
        values_a = values_a[:min_len]
        values_b = values_b[:min_len]

    # Calculate differences
    diff = np.abs(values_a - values_b)
    matches = diff <= tolerance
    n_matches = int(matches.sum())
    n_compared = len(diff)

    # Record mismatches for analysis
    mismatch_indices = np.where(~matches)[0]
    mismatches = []
    for idx in mismatch_indices[:max_mismatches]:
        mismatches.append({
            "index": int(idx),
            calc_a.name: float(values_a[idx]),
            calc_b.name: float(values_b[idx]),
            "difference": float(diff[idx]),
        })

    return ComparisonResult(
        variable=variable,
        source_name=source.name,
        calculator_a=calc_a.name,
        calculator_b=calc_b.name,
        n_compared=n_compared,
        n_matches=n_matches,
        match_rate=n_matches / n_compared if n_compared > 0 else 0.0,
        mean_absolute_error=float(diff.mean()),
        tolerance=tolerance,
        mismatches=mismatches,
    )

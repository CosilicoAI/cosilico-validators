"""PolicyEngine microdata source and calculator.

Wraps PolicyEngine's Microsimulation to provide:
1. Access to enhanced CPS microdata (includes IRS PUF imputations)
2. Calculation of any PolicyEngine variable
3. Entity relationships for aggregation

The enhanced CPS is the preferred data source because it includes
imputed variables from the IRS Public Use File that aren't in raw CPS:
- Investment income (interest, dividends, capital gains)
- Itemized deductions
- Tax liability validation targets
"""

import time
from typing import Any, Dict, Optional, Set
import numpy as np

from .base import (
    MicrodataSource,
    Calculator,
    EntityIndex,
    CalculationResult,
)


class PolicyEngineMicrodataSource(MicrodataSource):
    """Microdata source using PolicyEngine's Microsimulation.

    This wraps PE's enhanced CPS, which combines:
    - Census CPS ASEC (demographics, employment, program participation)
    - IRS SOI PUF imputations (investment income, deductions)

    The enhanced CPS is ideal for validation because it has:
    - ~200k person records for statistical power
    - Rich income detail at all levels
    - Validated against IRS aggregate targets
    """

    def __init__(self, year: int = 2024, dataset: str = "enhanced_cps"):
        """Initialize PolicyEngine microdata source.

        Args:
            year: Tax year
            dataset: Dataset name (default "enhanced_cps")
        """
        self._year = year
        self._dataset = dataset
        self._sim = None
        self._entity_index = None
        self._variable_cache: Dict[str, np.ndarray] = {}

    def _get_simulation(self):
        """Lazy load PolicyEngine Microsimulation."""
        if self._sim is None:
            try:
                from policyengine_us import Microsimulation
            except ImportError:
                raise ImportError(
                    "policyengine-us required. Install with: "
                    "pip install policyengine-us"
                )
            self._sim = Microsimulation()
        return self._sim

    @property
    def name(self) -> str:
        return f"PolicyEngine {self._dataset}"

    @property
    def year(self) -> int:
        return self._year

    @property
    def n_persons(self) -> int:
        sim = self._get_simulation()
        return len(sim.calculate("person_id", self._year))

    @property
    def n_tax_units(self) -> int:
        sim = self._get_simulation()
        return len(np.unique(sim.calculate("tax_unit_id", self._year)))

    @property
    def n_households(self) -> int:
        sim = self._get_simulation()
        return len(np.unique(sim.calculate("household_id", self._year)))

    def get_entity_index(self) -> EntityIndex:
        """Build EntityIndex from PE entity relationships."""
        if self._entity_index is not None:
            return self._entity_index

        sim = self._get_simulation()

        # Get entity IDs
        person_tax_unit_id = sim.calculate("person_tax_unit_id", self._year)
        tax_unit_id = sim.calculate("tax_unit_id", self._year)
        tax_unit_household_id = sim.calculate("tax_unit_household_id", self._year)
        household_id = sim.calculate("household_id", self._year)

        # Build person -> tax_unit mapping (index into unique tax_unit_ids)
        unique_tax_unit_ids = np.unique(tax_unit_id)
        tax_unit_id_to_idx = {int(tid): i for i, tid in enumerate(unique_tax_unit_ids)}
        person_to_tax_unit = np.array([
            tax_unit_id_to_idx[int(tid)] for tid in person_tax_unit_id
        ])

        # Build tax_unit -> household mapping
        unique_household_ids = np.unique(household_id)
        household_id_to_idx = {int(hid): i for i, hid in enumerate(unique_household_ids)}
        tax_unit_to_household = np.array([
            household_id_to_idx[int(hid)] for hid in tax_unit_household_id
        ])

        self._entity_index = EntityIndex(
            person_to_tax_unit=person_to_tax_unit,
            tax_unit_to_household=tax_unit_to_household,
            n_persons=len(person_tax_unit_id),
            n_tax_units=len(unique_tax_unit_ids),
            n_households=len(unique_household_ids),
        )

        return self._entity_index

    def get_variable(self, name: str, entity: str = "person") -> np.ndarray:
        """Get a PE variable as numpy array.

        PE variables are entity-specific. This method returns the variable
        at its natural entity level, or aggregates/broadcasts as needed.

        Args:
            name: PE variable name
            entity: Requested entity level

        Returns:
            Numpy array of values
        """
        cache_key = f"{name}_{entity}"
        if cache_key in self._variable_cache:
            return self._variable_cache[cache_key]

        sim = self._get_simulation()
        values = np.asarray(sim.calculate(name, self._year))

        # Cache and return
        self._variable_cache[cache_key] = values
        return values

    def get_weights(self, entity: str = "person") -> np.ndarray:
        """Get sampling weights.

        PE provides household weights. We broadcast to person/tax_unit.
        """
        sim = self._get_simulation()

        if entity == "household":
            return np.asarray(sim.calculate("household_weight", self._year))

        # For person/tax_unit, use household weights broadcast
        # This is a simplification - proper weighting would use
        # tax_unit_weight if available
        hh_weights = np.asarray(sim.calculate("household_weight", self._year))

        if entity == "person":
            # Broadcast household weights to persons
            person_hh_id = sim.calculate("person_household_id", self._year)
            hh_id = sim.calculate("household_id", self._year)
            hh_id_to_idx = {int(hid): i for i, hid in enumerate(hh_id)}
            return np.array([hh_weights[hh_id_to_idx[int(hid)]] for hid in person_hh_id])

        elif entity == "tax_unit":
            # Use tax unit weights if available, otherwise household
            try:
                return np.asarray(sim.calculate("tax_unit_weight", self._year))
            except Exception:
                # Fallback to household weights
                entity_index = self.get_entity_index()
                unique_hh_ids = np.unique(sim.calculate("household_id", self._year))
                return hh_weights[entity_index.tax_unit_to_household]

        return hh_weights

    def available_variables(self, entity: Optional[str] = None) -> Set[str]:
        """Get available PE variables.

        PE has hundreds of variables. We return a curated set of
        commonly used ones for validation.
        """
        # Core variables used in validation
        common_vars = {
            # Demographics
            "age", "is_tax_unit_head", "is_tax_unit_spouse", "is_tax_unit_dependent",
            "is_child", "filing_status",

            # Employment income
            "employment_income", "self_employment_income", "earned_income",

            # Investment income
            "interest_income", "dividend_income",
            "long_term_capital_gains", "short_term_capital_gains",
            "rental_income", "capital_gains",

            # Other income
            "social_security", "pension_income", "unemployment_compensation",

            # AGI and deductions
            "adjusted_gross_income", "standard_deduction", "itemized_deductions",
            "taxable_income",

            # Credits
            "eitc", "ctc", "cdctc", "premium_tax_credit",

            # Taxes
            "income_tax", "income_tax_before_credits",
            "self_employment_tax", "additional_medicare_tax",
            "net_investment_income_tax", "alternative_minimum_tax",

            # Benefits
            "snap", "medicaid", "ssi", "tanf",

            # Entities
            "person_id", "tax_unit_id", "household_id",
            "person_tax_unit_id", "tax_unit_household_id",

            # Children counts
            "ctc_qualifying_children", "eitc_child_count",
        }
        return common_vars


class PolicyEngineCalculator(Calculator):
    """Calculator using PolicyEngine microsimulation.

    This wraps PE's calculation engine, which evaluates variables
    on the full microdata in dependency order.
    """

    def __init__(self):
        self._sim = None

    @property
    def name(self) -> str:
        return "PolicyEngine"

    # Variable name aliases for consistency across calculators
    VARIABLE_ALIASES = {
        "niit": "net_investment_income_tax",
        "agi": "adjusted_gross_income",
        "qbi_deduction": "qualified_business_income_deduction",
        "earned_income_credit": "eitc",
        "child_tax_credit": "ctc",
    }

    @property
    def supported_variables(self) -> Set[str]:
        """PE supports hundreds of variables."""
        base_vars = {
            # Tax credits
            "eitc", "ctc", "refundable_ctc", "cdctc", "premium_tax_credit",

            # Income measures
            "adjusted_gross_income", "taxable_income", "earned_income",

            # Taxes
            "income_tax", "income_tax_before_credits",
            "self_employment_tax", "additional_medicare_tax",
            "net_investment_income_tax", "alternative_minimum_tax",
            "capital_gains_tax",

            # Deductions
            "standard_deduction", "itemized_deductions",
            "qualified_business_income_deduction",

            # Social Security
            "taxable_social_security",

            # Benefits
            "snap", "medicaid", "ssi", "tanf",
        }
        # Add aliases
        return base_vars | set(self.VARIABLE_ALIASES.keys())

    def _normalize_variable(self, variable: str) -> str:
        """Normalize variable name to PE canonical name."""
        return self.VARIABLE_ALIASES.get(variable.lower(), variable.lower())

    def calculate(
        self,
        variable: str,
        source: MicrodataSource,
        year: Optional[int] = None,
    ) -> CalculationResult:
        """Calculate a variable using PolicyEngine.

        If source is already a PolicyEngineMicrodataSource, we reuse
        its simulation. Otherwise, we'd need to transfer data (not implemented).
        """
        if not isinstance(source, PolicyEngineMicrodataSource):
            return CalculationResult(
                variable=variable,
                values=None,
                entity="tax_unit",
                n_records=0,
                calculation_time_ms=0,
                error="PolicyEngineCalculator requires PolicyEngineMicrodataSource",
            )

        year = year or source.year
        start_time = time.perf_counter()

        # Normalize variable name (e.g., "niit" -> "net_investment_income_tax")
        pe_variable = self._normalize_variable(variable)

        try:
            values = source.get_variable(pe_variable)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Determine entity from array length
            n = len(values)
            if n == source.n_persons:
                entity = "person"
            elif n == source.n_tax_units:
                entity = "tax_unit"
            elif n == source.n_households:
                entity = "household"
            else:
                entity = "unknown"

            return CalculationResult(
                variable=variable,
                values=values,
                entity=entity,
                n_records=n,
                calculation_time_ms=elapsed_ms,
            )

        except Exception as e:
            return CalculationResult(
                variable=variable,
                values=None,
                entity="unknown",
                n_records=0,
                calculation_time_ms=(time.perf_counter() - start_time) * 1000,
                error=str(e),
            )

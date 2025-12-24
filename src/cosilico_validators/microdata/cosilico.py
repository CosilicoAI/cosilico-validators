"""Cosilico calculator for microdata validation.

Wraps the Cosilico VectorizedExecutor to calculate tax/benefit
variables on microdata, enabling comparison against PolicyEngine,
TAXSIM, and other reference implementations.

The Cosilico engine:
1. Parses .cosilico DSL files from cosilico-us
2. Executes formulas using vectorized NumPy operations
3. Handles entity aggregation (person -> tax_unit -> household)
"""

import sys
import time
from pathlib import Path
from typing import Dict, Optional, Set
import numpy as np

from .base import (
    MicrodataSource,
    Calculator,
    CalculationResult,
)

# Variable mappings from common names to cosilico file locations
VARIABLE_MAPPING: Dict[str, Dict[str, str]] = {
    # Tax credits
    "eitc": {
        # Use validation-focused encoding that takes PE's precomputed eligibility
        "file": "statute/26/32/eitc_validation.cosilico",
        "variable": "earned_income_credit",
    },
    "ctc": {
        "file": "statute/26/24/a/credit.cosilico",
        "variable": "child_tax_credit",
    },

    # Income measures
    "agi": {
        "file": "statute/26/62/a/adjusted_gross_income.cosilico",
        "variable": "adjusted_gross_income",
    },
    "adjusted_gross_income": {
        "file": "statute/26/62/a/adjusted_gross_income.cosilico",
        "variable": "adjusted_gross_income",
    },

    # Deductions
    "standard_deduction": {
        "file": "statute/26/63/c/standard_deduction.cosilico",
        "variable": "standard_deduction",
    },

    # Taxes
    "net_investment_income_tax": {
        "file": "statute/26/1411/net_investment_income_tax.cosilico",
        "variable": "net_investment_income_tax",
    },
    "niit": {
        "file": "statute/26/1411/net_investment_income_tax.cosilico",
        "variable": "net_investment_income_tax",
    },
    "additional_medicare_tax": {
        "file": "statute/26/3101/b/2/additional_medicare_tax.cosilico",
        "variable": "additional_medicare_tax",
    },
    "self_employment_tax": {
        "file": "statute/26/1401/self_employment_tax.cosilico",
        "variable": "self_employment_tax",
    },
    "capital_gains_tax": {
        "file": "statute/26/1/h/capital_gains_tax.cosilico",
        "variable": "capital_gains_tax",
    },

    # Other
    "qualified_business_income_deduction": {
        "file": "statute/26/199A/qbi_deduction.cosilico",
        "variable": "qualified_business_income_deduction",
    },
    "qbi_deduction": {
        "file": "statute/26/199A/qbi_deduction.cosilico",
        "variable": "qualified_business_income_deduction",
    },
    "premium_tax_credit": {
        "file": "statute/26/36B/premium_tax_credit.cosilico",
        "variable": "premium_tax_credit",
    },
    "taxable_social_security": {
        "file": "statute/26/86/taxable_social_security.cosilico",
        "variable": "taxable_social_security",
    },

    # Benefits
    "snap": {
        "file": "statute/7/2017/a/allotment.cosilico",
        "variable": "snap_allotment",
    },
}


class CosilicoCalculator(Calculator):
    """Calculator using Cosilico DSL executor.

    Loads .cosilico statute files and executes them on microdata
    using the VectorizedExecutor for high performance.

    Attributes:
        cosilico_us_path: Path to cosilico-us repo with statute files
    """

    def __init__(
        self,
        cosilico_us_path: Optional[Path] = None,
        cosilico_engine_path: Optional[Path] = None,
    ):
        """Initialize Cosilico calculator.

        Args:
            cosilico_us_path: Path to cosilico-us repo (default: ~/CosilicoAI/cosilico-us)
            cosilico_engine_path: Path to cosilico-engine (default: ~/CosilicoAI/cosilico-engine)
        """
        self.cosilico_us_path = cosilico_us_path or Path.home() / "CosilicoAI/cosilico-us"
        self.cosilico_engine_path = cosilico_engine_path or Path.home() / "CosilicoAI/cosilico-engine"
        self._executor = None
        self._parameters = None

    def _ensure_engine_imported(self):
        """Ensure cosilico-engine is importable."""
        engine_src = self.cosilico_engine_path / "src"
        if str(engine_src) not in sys.path:
            sys.path.insert(0, str(engine_src))

    def _get_executor(self):
        """Lazy load VectorizedExecutor."""
        if self._executor is None:
            self._ensure_engine_imported()

            from cosilico.vectorized_executor import VectorizedExecutor
            from cosilico.dsl_executor import get_default_parameters

            self._parameters = get_default_parameters()
            self._executor = VectorizedExecutor(parameters=self._parameters)

        return self._executor

    def _get_entity_index(self, source: MicrodataSource):
        """Get EntityIndex from source, converting to cosilico format."""
        self._ensure_engine_imported()
        from cosilico.vectorized_executor import EntityIndex as CosilicoEntityIndex

        base_index = source.get_entity_index()

        return CosilicoEntityIndex(
            person_to_tax_unit=base_index.person_to_tax_unit,
            tax_unit_to_household=base_index.tax_unit_to_household,
            n_persons=base_index.n_persons,
            n_tax_units=base_index.n_tax_units,
            n_households=base_index.n_households,
        )

    @property
    def name(self) -> str:
        return "Cosilico"

    @property
    def supported_variables(self) -> Set[str]:
        """Variables with .cosilico encodings."""
        return set(VARIABLE_MAPPING.keys())

    def _extract_inputs(self, source: MicrodataSource) -> Dict[str, np.ndarray]:
        """Extract all needed inputs from source."""
        # Common inputs needed by most tax calculations
        input_names = [
            # Demographics
            "age", "is_tax_unit_head", "is_tax_unit_spouse", "is_tax_unit_dependent",
            "is_child", "filing_status",

            # Employment income - both raw and IRS-specific
            "employment_income", "self_employment_income", "earned_income",
            "wages", "irs_employment_income", "taxable_self_employment_income",
            "taxable_earnings_for_social_security",  # W-2 wages subject to SS tax

            # Investment income - both raw and tax-specific
            "interest_income", "dividend_income", "taxable_interest_income",
            "long_term_capital_gains", "short_term_capital_gains",
            "rental_income", "capital_gains",
            # Tax-unit level capital gains with $3k loss limit
            "loss_limited_net_capital_gains",

            # AGI and other
            "adjusted_gross_income", "taxable_income",

            # Children
            "ctc_qualifying_children",

            # EITC-specific (from PE)
            "eitc_child_count", "eitc_eligible", "eitc_phase_in_rate", "eitc_maximum",
            # Tax unit level earned income for EITC
            "tax_unit_earned_income",
        ]

        # Aliases: PE variable name -> encoding variable name
        # This maps PolicyEngine's computed values to what the encodings expect
        input_aliases = {
            "eitc_child_count": "num_qualifying_children",
            "eitc_eligible": "is_eligible_individual",
            "tax_unit_earned_income": "earned_income",  # Use TaxUnit level for EITC
        }

        inputs = {}
        for name in input_names:
            try:
                value = np.asarray(source.get_variable(name))
                inputs[name] = value
                # Also add under alias if defined
                if name in input_aliases:
                    inputs[input_aliases[name]] = value
            except (KeyError, Exception):
                pass  # Variable not available

        return inputs

    def calculate(
        self,
        variable: str,
        source: MicrodataSource,
        year: Optional[int] = None,
    ) -> CalculationResult:
        """Calculate a variable using Cosilico DSL executor.

        Args:
            variable: Variable name (e.g., "eitc", "net_investment_income_tax")
            source: MicrodataSource providing inputs
            year: Tax year (unused, encodings are year-specific)

        Returns:
            CalculationResult with computed values or error
        """
        # Look up variable mapping
        var_lower = variable.lower()
        if var_lower not in VARIABLE_MAPPING:
            return CalculationResult(
                variable=variable,
                values=None,
                entity="unknown",
                n_records=0,
                calculation_time_ms=0,
                error=f"No Cosilico encoding for variable: {variable}",
            )

        mapping = VARIABLE_MAPPING[var_lower]
        cosilico_file = self.cosilico_us_path / mapping["file"]
        cosilico_variable = mapping["variable"]

        if not cosilico_file.exists():
            return CalculationResult(
                variable=variable,
                values=None,
                entity="unknown",
                n_records=0,
                calculation_time_ms=0,
                error=f"Cosilico file not found: {cosilico_file}",
            )

        start_time = time.perf_counter()

        try:
            executor = self._get_executor()
            inputs = self._extract_inputs(source)
            entity_index = self._get_entity_index(source)

            with open(cosilico_file) as f:
                code = f.read()

            # Execute with entity index for aggregation support
            results = executor.execute(
                code=code,
                inputs=inputs,
                entity_index=entity_index,
                output_variables=[cosilico_variable],
            )

            values = results.get(cosilico_variable)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if values is None:
                return CalculationResult(
                    variable=variable,
                    values=None,
                    entity="unknown",
                    n_records=0,
                    calculation_time_ms=elapsed_ms,
                    error=f"Variable {cosilico_variable} not in results",
                )

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
                metadata={
                    "cosilico_file": str(cosilico_file),
                    "cosilico_variable": cosilico_variable,
                },
            )

        except Exception as e:
            import traceback
            return CalculationResult(
                variable=variable,
                values=None,
                entity="unknown",
                n_records=0,
                calculation_time_ms=(time.perf_counter() - start_time) * 1000,
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            )

    def batch_calculate(
        self,
        variables: list,
        source: MicrodataSource,
        year: Optional[int] = None,
    ) -> Dict[str, CalculationResult]:
        """Calculate multiple variables, reusing inputs and entity index.

        This is more efficient than calling calculate() repeatedly
        because we extract inputs and build entity index once.
        """
        results = {}

        # Pre-extract inputs and entity index
        try:
            executor = self._get_executor()
            inputs = self._extract_inputs(source)
            entity_index = self._get_entity_index(source)
        except Exception as e:
            # Return errors for all variables
            for var in variables:
                results[var] = CalculationResult(
                    variable=var,
                    values=None,
                    entity="unknown",
                    n_records=0,
                    calculation_time_ms=0,
                    error=f"Setup failed: {e}",
                )
            return results

        # Calculate each variable
        for variable in variables:
            var_lower = variable.lower()
            if var_lower not in VARIABLE_MAPPING:
                results[variable] = CalculationResult(
                    variable=variable,
                    values=None,
                    entity="unknown",
                    n_records=0,
                    calculation_time_ms=0,
                    error=f"No Cosilico encoding for: {variable}",
                )
                continue

            mapping = VARIABLE_MAPPING[var_lower]
            cosilico_file = self.cosilico_us_path / mapping["file"]
            cosilico_variable = mapping["variable"]

            if not cosilico_file.exists():
                results[variable] = CalculationResult(
                    variable=variable,
                    values=None,
                    entity="unknown",
                    n_records=0,
                    calculation_time_ms=0,
                    error=f"File not found: {cosilico_file}",
                )
                continue

            start_time = time.perf_counter()

            try:
                with open(cosilico_file) as f:
                    code = f.read()

                calc_results = executor.execute(
                    code=code,
                    inputs=inputs,
                    entity_index=entity_index,
                    output_variables=[cosilico_variable],
                )

                values = calc_results.get(cosilico_variable)
                elapsed_ms = (time.perf_counter() - start_time) * 1000

                if values is not None:
                    n = len(values)
                    if n == source.n_persons:
                        entity = "person"
                    elif n == source.n_tax_units:
                        entity = "tax_unit"
                    else:
                        entity = "unknown"

                    results[variable] = CalculationResult(
                        variable=variable,
                        values=values,
                        entity=entity,
                        n_records=n,
                        calculation_time_ms=elapsed_ms,
                    )
                else:
                    results[variable] = CalculationResult(
                        variable=variable,
                        values=None,
                        entity="unknown",
                        n_records=0,
                        calculation_time_ms=elapsed_ms,
                        error=f"Variable not in results",
                    )

            except Exception as e:
                results[variable] = CalculationResult(
                    variable=variable,
                    values=None,
                    entity="unknown",
                    n_records=0,
                    calculation_time_ms=(time.perf_counter() - start_time) * 1000,
                    error=str(e),
                )

        return results

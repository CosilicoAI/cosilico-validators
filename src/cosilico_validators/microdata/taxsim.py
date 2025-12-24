"""TAXSIM calculator for microdata validation.

TAXSIM is NBER's Tax Simulator, the gold standard for federal tax
calculations. It's particularly valuable for validating:
- Income tax liability
- EITC
- Self-employment tax
- Capital gains treatment

TAXSIM-35 (current version) is accessed via web service.
See: https://taxsim.nber.org/taxsim35/
"""

import io
import time
from typing import Dict, Optional, Set
import numpy as np
import pandas as pd
import requests

from .base import (
    MicrodataSource,
    Calculator,
    CalculationResult,
)


# TAXSIM variable mappings
# Input variables (what we send to TAXSIM)
TAXSIM_INPUT_VARS = {
    "taxsimid": "Record ID",
    "year": "Tax year",
    "state": "State code (0=no state tax)",
    "mstat": "Filing status (1=single, 2=joint, 6=HOH, 8=separate)",
    "page": "Primary taxpayer age",
    "sage": "Spouse age",
    "depx": "Number of dependents",
    "dep13": "Children under 13",
    "dep17": "Children under 17",
    "dep18": "Children under 19",
    "pwages": "Primary wages",
    "swages": "Spouse wages",
    "psemp": "Primary self-employment income",
    "ssemp": "Spouse self-employment income",
    "dividends": "Dividend income",
    "intrec": "Interest received",
    "stcg": "Short-term capital gains",
    "ltcg": "Long-term capital gains",
    "otherprop": "Other property income (rent, royalties)",
    "nonprop": "Other non-property income",
    "pensions": "Taxable pension income",
    "gssi": "Gross Social Security income",
    "ui": "Unemployment compensation",
    "transfers": "Non-taxable transfer income",
    "rentpaid": "Rent paid (state use)",
    "pression": "Real estate taxes paid",
    "otheritem": "Other itemized deductions",
    "childcare": "Child care expenses",
}

# Output variables (what TAXSIM returns)
TAXSIM_OUTPUT_VARS = {
    "v1": "taxsimid",
    "v2": "year",
    "v4": "state",
    "v5": "fiitax",  # Federal income tax
    "v6": "siitax",  # State income tax
    "v7": "fica",    # FICA (Social Security + Medicare)
    "v10": "fagi",   # Federal AGI
    "v11": "ui_agi", # UI in AGI
    "v12": "ss_agi", # Social Security in AGI
    "v13": "exemp",  # Exemption amount
    "v14": "deduct", # Deductions
    "v15": "txbl",   # Taxable income
    "v16": "frate",  # Federal marginal rate
    "v17": "srate",  # State marginal rate
    "v18": "ficar",  # FICA rate
    "v19": "tfica",  # Total FICA
    "v22": "ctc",    # Child Tax Credit
    "v23": "eitc",   # EITC
    "v24": "cdctc",  # CDCTC
    "v25": "eitc2",  # EITC (duplicate?)
    "v28": "setax",  # Self-employment tax
}


class TAXSIMCalculator(Calculator):
    """Calculator using NBER TAXSIM-35 web service.

    TAXSIM is accessed via HTTP POST to taxsim.nber.org.
    It processes batches of tax records and returns calculated values.

    Limitations:
    - TAXSIM-35 only supports years through 2023
    - Some newer provisions may not be implemented
    - Rate limits may apply for large batches
    """

    TAXSIM_URL = "https://taxsim.nber.org/taxsim35/taxsim.cgi"

    def __init__(self, max_batch_size: int = 10000):
        """Initialize TAXSIM calculator.

        Args:
            max_batch_size: Maximum records per TAXSIM request
        """
        self.max_batch_size = max_batch_size

    @property
    def name(self) -> str:
        return "TAXSIM"

    @property
    def supported_variables(self) -> Set[str]:
        """Variables TAXSIM can calculate."""
        return {
            "income_tax", "federal_income_tax",
            "eitc", "earned_income_credit",
            "ctc", "child_tax_credit",
            "cdctc", "child_and_dependent_care_credit",
            "self_employment_tax",
            "adjusted_gross_income", "agi",
            "taxable_income",
            "fica",
        }

    def _source_to_taxsim_inputs(
        self,
        source: MicrodataSource,
        year: int,
    ) -> pd.DataFrame:
        """Convert MicrodataSource to TAXSIM input format.

        This is a simplified conversion. A production implementation
        would handle more edge cases.
        """
        n = source.n_tax_units

        # Build TAXSIM input DataFrame
        df = pd.DataFrame({
            "taxsimid": np.arange(1, n + 1),
            "year": min(year, 2023),  # TAXSIM-35 max year
            "state": 0,  # No state tax for now
        })

        # Filing status
        try:
            filing_status = source.get_variable("filing_status", "tax_unit")
            # Convert PE filing status to TAXSIM mstat
            # PE: SINGLE, JOINT, SEPARATE, HEAD_OF_HOUSEHOLD, WIDOW
            # TAXSIM: 1=single, 2=joint, 6=HOH, 8=separate
            mstat_map = {
                "SINGLE": 1,
                "JOINT": 2,
                "HEAD_OF_HOUSEHOLD": 6,
                "SEPARATE": 8,
                "WIDOW": 8,
            }
            df["mstat"] = [mstat_map.get(str(s), 1) for s in filing_status]
        except Exception:
            df["mstat"] = 1

        # Ages - use median if not available
        try:
            df["page"] = source.get_variable("age", "tax_unit").astype(int)
        except Exception:
            df["page"] = 40

        df["sage"] = 0  # Assume single for simplicity

        # Dependents
        try:
            df["depx"] = source.get_variable("ctc_qualifying_children", "tax_unit").astype(int)
            df["dep13"] = df["depx"]
            df["dep17"] = df["depx"]
            df["dep18"] = df["depx"]
        except Exception:
            df["depx"] = 0
            df["dep13"] = 0
            df["dep17"] = 0
            df["dep18"] = 0

        # Income - need to aggregate from person to tax_unit
        entity_index = source.get_entity_index()

        def get_tax_unit_sum(var_name: str) -> np.ndarray:
            try:
                person_vals = source.get_variable(var_name, "person")
                return entity_index.aggregate_to_tax_unit(person_vals, "sum")
            except Exception:
                return np.zeros(n)

        df["pwages"] = get_tax_unit_sum("employment_income")
        df["swages"] = 0  # Simplified
        df["psemp"] = get_tax_unit_sum("self_employment_income")
        df["ssemp"] = 0
        df["dividends"] = get_tax_unit_sum("dividend_income")
        df["intrec"] = get_tax_unit_sum("interest_income")
        df["stcg"] = get_tax_unit_sum("short_term_capital_gains")
        df["ltcg"] = get_tax_unit_sum("long_term_capital_gains")
        df["otherprop"] = get_tax_unit_sum("rental_income")
        df["nonprop"] = 0
        df["pensions"] = get_tax_unit_sum("pension_income")
        df["gssi"] = get_tax_unit_sum("social_security")
        df["ui"] = get_tax_unit_sum("unemployment_compensation")
        df["transfers"] = 0
        df["rentpaid"] = 0
        df["pression"] = 0
        df["otheritem"] = 0
        df["childcare"] = 0

        return df

    def _call_taxsim(self, input_df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Send data to TAXSIM web service and parse response."""
        # Convert to CSV format
        csv_buffer = io.StringIO()
        input_df.to_csv(csv_buffer, index=False)
        csv_data = csv_buffer.getvalue()

        try:
            response = requests.post(
                self.TAXSIM_URL,
                data=csv_data,
                headers={"Content-Type": "text/csv"},
                timeout=300,  # 5 minute timeout for large batches
            )
            response.raise_for_status()

            # Parse response CSV
            result_df = pd.read_csv(io.StringIO(response.text))
            return result_df

        except requests.RequestException as e:
            print(f"TAXSIM request failed: {e}")
            return None

    def calculate(
        self,
        variable: str,
        source: MicrodataSource,
        year: Optional[int] = None,
    ) -> CalculationResult:
        """Calculate a variable using TAXSIM.

        Note: TAXSIM processes all variables at once, so this is
        inefficient for single variables. Use batch_calculate() instead.
        """
        year = year or source.year
        start_time = time.perf_counter()

        try:
            # Convert source to TAXSIM format
            input_df = self._source_to_taxsim_inputs(source, year)

            # Call TAXSIM in batches
            all_results = []
            for i in range(0, len(input_df), self.max_batch_size):
                batch = input_df.iloc[i:i + self.max_batch_size]
                result = self._call_taxsim(batch)
                if result is not None:
                    all_results.append(result)

            if not all_results:
                return CalculationResult(
                    variable=variable,
                    values=None,
                    entity="tax_unit",
                    n_records=0,
                    calculation_time_ms=(time.perf_counter() - start_time) * 1000,
                    error="TAXSIM request failed",
                )

            results_df = pd.concat(all_results, ignore_index=True)

            # Map variable name to TAXSIM output column
            var_lower = variable.lower()
            taxsim_col = {
                "income_tax": "v5",
                "federal_income_tax": "v5",
                "eitc": "v25",
                "earned_income_credit": "v25",
                "ctc": "v22",
                "child_tax_credit": "v22",
                "cdctc": "v24",
                "self_employment_tax": "v28",
                "adjusted_gross_income": "v10",
                "agi": "v10",
                "taxable_income": "v15",
                "fica": "v19",
            }.get(var_lower)

            if taxsim_col is None or taxsim_col not in results_df.columns:
                return CalculationResult(
                    variable=variable,
                    values=None,
                    entity="tax_unit",
                    n_records=0,
                    calculation_time_ms=(time.perf_counter() - start_time) * 1000,
                    error=f"Variable not available in TAXSIM output: {variable}",
                )

            values = results_df[taxsim_col].values
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            return CalculationResult(
                variable=variable,
                values=values,
                entity="tax_unit",
                n_records=len(values),
                calculation_time_ms=elapsed_ms,
                metadata={"taxsim_column": taxsim_col},
            )

        except Exception as e:
            import traceback
            return CalculationResult(
                variable=variable,
                values=None,
                entity="tax_unit",
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
        """Calculate multiple variables with a single TAXSIM call.

        This is more efficient than calling calculate() repeatedly
        because TAXSIM returns all variables at once.
        """
        year = year or source.year
        start_time = time.perf_counter()
        results = {}

        try:
            # Convert source to TAXSIM format
            input_df = self._source_to_taxsim_inputs(source, year)

            # Call TAXSIM in batches
            all_results = []
            for i in range(0, len(input_df), self.max_batch_size):
                batch = input_df.iloc[i:i + self.max_batch_size]
                result = self._call_taxsim(batch)
                if result is not None:
                    all_results.append(result)

            if not all_results:
                for var in variables:
                    results[var] = CalculationResult(
                        variable=var,
                        values=None,
                        entity="tax_unit",
                        n_records=0,
                        calculation_time_ms=0,
                        error="TAXSIM request failed",
                    )
                return results

            results_df = pd.concat(all_results, ignore_index=True)
            total_time = (time.perf_counter() - start_time) * 1000
            per_var_time = total_time / len(variables)

            # Map each variable
            var_to_col = {
                "income_tax": "v5",
                "federal_income_tax": "v5",
                "eitc": "v25",
                "earned_income_credit": "v25",
                "ctc": "v22",
                "child_tax_credit": "v22",
                "cdctc": "v24",
                "self_employment_tax": "v28",
                "adjusted_gross_income": "v10",
                "agi": "v10",
                "taxable_income": "v15",
                "fica": "v19",
            }

            for var in variables:
                var_lower = var.lower()
                taxsim_col = var_to_col.get(var_lower)

                if taxsim_col is None or taxsim_col not in results_df.columns:
                    results[var] = CalculationResult(
                        variable=var,
                        values=None,
                        entity="tax_unit",
                        n_records=0,
                        calculation_time_ms=per_var_time,
                        error=f"Variable not in TAXSIM output",
                    )
                else:
                    results[var] = CalculationResult(
                        variable=var,
                        values=results_df[taxsim_col].values,
                        entity="tax_unit",
                        n_records=len(results_df),
                        calculation_time_ms=per_var_time,
                    )

            return results

        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000
            for var in variables:
                results[var] = CalculationResult(
                    variable=var,
                    values=None,
                    entity="tax_unit",
                    n_records=0,
                    calculation_time_ms=elapsed / len(variables),
                    error=str(e),
                )
            return results

"""PSL Tax-Calculator validator - uses the Policy Simulation Library Tax-Calculator package.

Compares Cosilico calculations against PSL/Tax-Calculator (https://github.com/PSLmodels/Tax-Calculator).
Tax-Calculator is an open-source microsimulation model for analyzing US federal income and payroll taxes.
"""

from typing import Any, Dict, Optional, Set

import pandas as pd

from cosilico_validators.validators.base import (
    BaseValidator,
    TestCase,
    ValidatorResult,
    ValidatorType,
)

# Variable mapping from common names to Tax-Calculator variable names
VARIABLE_MAPPING = {
    # Income measures
    "adjusted_gross_income": "c00100",  # AGI
    "agi": "c00100",
    "taxable_income": "c04800",
    "gross_income": "c00100",
    # Income tax
    "income_tax": "iitax",  # Individual income tax liability
    "federal_income_tax": "iitax",
    "income_tax_before_credits": "c05800",  # Tax before credits
    # Tax credits
    "eitc": "eitc",  # Earned Income Tax Credit
    "earned_income_credit": "eitc",
    "ctc": "c07220",  # Child Tax Credit
    "child_tax_credit": "c07220",
    "actc": "c11070",  # Additional (refundable) CTC
    "additional_ctc": "c11070",
    "refundable_ctc": "c11070",
    "cdctc": "c07180",  # Child and Dependent Care Credit
    "child_and_dependent_care_credit": "c07180",
    # AMT
    "amt": "c09600",  # Alternative Minimum Tax
    "alternative_minimum_tax": "c09600",
    # Payroll taxes
    "fica": "payrolltax",
    "payroll_tax": "payrolltax",
    "employee_payroll_tax": "ptax_was",
    "self_employment_tax": "setax",
    # Social Security
    "taxable_social_security": "c02500",
    # Other
    "standard_deduction": "standard",
    "total_tax": "combined",  # Combined income + payroll tax
}

# Supported variables
SUPPORTED_VARIABLES: Set[str] = set(VARIABLE_MAPPING.keys()) | set(VARIABLE_MAPPING.values())


class PSLTaxCalculatorValidator(BaseValidator):
    """Validator using PSL Tax-Calculator microsimulation.

    Tax-Calculator provides highly configurable tax calculation with 200+ policy parameters.
    It supports tax years from 2013 onwards.

    Documentation: http://taxcalc.pslmodels.org/
    Source: https://github.com/PSLmodels/Tax-Calculator
    """

    name = "PSL Tax-Calculator"
    validator_type = ValidatorType.SUPPLEMENTARY
    supported_variables = SUPPORTED_VARIABLES

    def __init__(self):
        self._calculator_class = None
        self._records_class = None
        self._policy_class = None

    def _get_classes(self):
        """Lazy load Tax-Calculator classes to avoid import overhead."""
        if self._calculator_class is None:
            try:
                from taxcalc import Calculator, Policy, Records

                self._calculator_class = Calculator
                self._records_class = Records
                self._policy_class = Policy
            except ImportError as e:
                raise ImportError(
                    "taxcalc not installed. "
                    "Install with: pip install cosilico-validators[psl]"
                ) from e
        return self._calculator_class, self._records_class, self._policy_class

    def supports_variable(self, variable: str) -> bool:
        return variable.lower() in SUPPORTED_VARIABLES

    def _build_input_data(self, test_case: TestCase, year: int) -> pd.DataFrame:
        """Convert test case inputs to Tax-Calculator input format.

        Tax-Calculator uses MARS codes for filing status:
        1 = Single
        2 = Married filing jointly
        3 = Married filing separately
        4 = Head of household
        5 = Qualifying widow(er)
        """
        inputs = test_case.inputs

        # Filing status mapping
        mars_codes = {
            "SINGLE": 1,
            "JOINT": 2,
            "MARRIED_FILING_JOINTLY": 2,
            "MARRIED_FILING_SEPARATELY": 3,
            "SEPARATE": 3,
            "HEAD_OF_HOUSEHOLD": 4,
            "HOH": 4,
            "WIDOW": 5,
            "WIDOWER": 5,
        }

        # Build base record
        record = {
            "RECID": 1,
            "MARS": mars_codes.get(inputs.get("filing_status", "SINGLE").upper(), 1),
            "FLPDYR": year,
            "age_head": inputs.get("age", inputs.get("age_at_end_of_year", 30)),
            "age_spouse": 0,
            "XTOT": 1,  # Total exemptions
        }

        # Handle spouse for joint filers
        filing_status = inputs.get("filing_status", "SINGLE").upper()
        if filing_status in ["JOINT", "MARRIED_FILING_JOINTLY"]:
            record["age_spouse"] = inputs.get("spouse_age", record["age_head"])
            record["XTOT"] = 2

        # Map income inputs
        income_mappings = {
            "earned_income": "e00200",  # Wages, salaries, tips
            "employment_income": "e00200",
            "wages": "e00200",
            "self_employment_income": "e00900",  # Self-employment income
            "interest_income": "e00300",  # Taxable interest
            "dividend_income": "e00600",  # Ordinary dividends
            "qualified_dividends": "e00650",  # Qualified dividends
            "long_term_capital_gains": "p23250",  # Long-term capital gains
            "short_term_capital_gains": "p22250",  # Short-term capital gains
            "social_security": "e02400",  # Social security benefits
            "pension_income": "e01500",  # Pension/annuity income
        }

        for input_key, tc_var in income_mappings.items():
            if input_key.lower() in {k.lower(): k for k in inputs}:
                actual_key = next(k for k in inputs if k.lower() == input_key.lower())
                record[tc_var] = inputs[actual_key]

        # Handle AGI as wages if no specific breakdown
        if "agi" in inputs and "e00200" not in record:
            record["e00200"] = inputs["agi"]

        # Handle children/dependents
        num_children = 0
        for child_key in ["eitc_qualifying_children_count", "num_children",
                          "qualifying_children_under_17", "ctc_qualifying_children"]:
            if child_key.lower() in {k.lower(): k for k in inputs}:
                actual_key = next(k for k in inputs if k.lower() == child_key.lower())
                num_children = max(num_children, inputs[actual_key])

        if num_children > 0:
            record["XTOT"] += num_children
            # EIC qualifying children
            record["EIC"] = min(num_children, 3)  # EITC limited to 3 children
            # Set number of dependents for CTC
            record["n24"] = num_children  # Number of children under 17

        return pd.DataFrame([record])

    def validate(
        self, test_case: TestCase, variable: str, year: int = 2023
    ) -> ValidatorResult:
        """Run validation using Tax-Calculator.

        Note: Tax-Calculator supports tax years from 2013 onwards.
        """
        # Validate year
        if year < 2013:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=f"Tax-Calculator only supports tax years 2013+, got {year}",
            )

        var_lower = variable.lower()
        if var_lower not in VARIABLE_MAPPING:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=f"Variable '{variable}' not supported by Tax-Calculator",
            )

        try:
            Calculator, Records, Policy = self._get_classes()

            # Build input data
            input_df = self._build_input_data(test_case, year)

            # Create policy for the given year
            policy = Policy()

            # Create records from DataFrame
            records = Records(
                data=input_df,
                start_year=year,
                gfactors=None,
                weights=None,
            )

            # Create calculator
            calc = Calculator(policy=policy, records=records)
            calc.calc_all()

            # Get the output variable name
            tc_variable = VARIABLE_MAPPING.get(var_lower, var_lower)

            # Extract result
            if hasattr(calc.dataframe([tc_variable]), tc_variable):
                result_df = calc.dataframe([tc_variable])
                calculated = float(result_df[tc_variable].iloc[0])
            else:
                # Try accessing through array
                try:
                    calculated = float(calc.array(tc_variable)[0])
                except Exception:
                    return ValidatorResult(
                        validator_name=self.name,
                        validator_type=self.validator_type,
                        calculated_value=None,
                        error=f"Could not extract {tc_variable} from Tax-Calculator output",
                    )

            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=calculated,
                metadata={"tc_variable": tc_variable, "year": year},
            )

        except ImportError as e:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=str(e),
            )
        except Exception as e:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=f"Tax-Calculator execution failed: {e}",
            )

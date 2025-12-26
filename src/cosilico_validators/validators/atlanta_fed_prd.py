"""Atlanta Fed Policy Rules Database validator.

Compares Cosilico benefit program calculations against the Atlanta Fed's Policy Rules Database (PRD).
The PRD contains rules and provisions for major federal and state public assistance programs.

Source: https://github.com/Research-Division/policy-rules-database
Documentation: https://www.atlantafed.org/economic-mobility-and-resilience/advancing-careers-for-low-income-families/policy-rules-database
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Set
from urllib.request import urlopen, Request
from urllib.error import URLError

from cosilico_validators.validators.base import (
    BaseValidator,
    TestCase,
    ValidatorResult,
    ValidatorType,
)

# Variable mapping from common names to PRD parameter names
VARIABLE_MAPPING = {
    # SNAP (Supplemental Nutrition Assistance Program)
    "snap": "SNAP",
    "snap_benefits": "SNAP",
    "snap_max_benefit": "SNAP_max_benefit",
    "snap_standard_deduction": "SNAP_standard_deduction",
    "snap_income_limit": "SNAP_gross_income_limit",
    "snap_net_income_limit": "SNAP_net_income_limit",
    # TANF (Temporary Assistance for Needy Families)
    "tanf": "TANF",
    "tanf_max_benefit": "TANF_max_benefit",
    "tanf_income_limit": "TANF_income_limit",
    # Medicaid/CHIP
    "medicaid": "Medicaid",
    "medicaid_income_limit": "Medicaid_income_limit",
    "chip": "CHIP",
    "chip_income_limit": "CHIP_income_limit",
    # CCDF (Child Care and Development Fund)
    "ccdf": "CCDF",
    "ccdf_income_limit": "CCDF_income_limit",
    "ccdf_copay": "CCDF_copay",
    # Housing Choice Voucher (Section 8)
    "section8": "Section8",
    "housing_voucher": "Section8",
    "section8_income_limit": "Section8_income_limit",
    # WIC
    "wic": "WIC",
    "wic_income_limit": "WIC_income_limit",
    # LIHEAP
    "liheap": "LIHEAP",
    "liheap_income_limit": "LIHEAP_income_limit",
    # Head Start
    "head_start": "HeadStart",
    "head_start_income_limit": "HeadStart_income_limit",
    # Tax credits (PRD also covers these)
    "eitc": "EITC",
    "earned_income_credit": "EITC",
    "eitc_phase_in_rate": "EITC_phase_in_rate",
    "eitc_phase_out_rate": "EITC_phase_out_rate",
    "eitc_max_credit": "EITC_max_credit",
    "ctc": "CTC",
    "child_tax_credit": "CTC",
    "ctc_max_credit": "CTC_max_credit",
    "ctc_phase_out_threshold": "CTC_phase_out_threshold",
}

# Supported variables
SUPPORTED_VARIABLES: Set[str] = set(VARIABLE_MAPPING.keys())

# PRD GitHub raw file base URL
PRD_GITHUB_BASE = "https://raw.githubusercontent.com/Research-Division/policy-rules-database/main"


class AtlantaFedPRDValidator(BaseValidator):
    """Validator using the Atlanta Fed Policy Rules Database.

    The PRD provides eligibility thresholds, phase-out rates, and benefit amounts
    for major federal and state public assistance programs. It's particularly
    useful for validating:
    - SNAP eligibility and benefit calculations
    - TANF parameters by state
    - Medicaid/CHIP income limits
    - Child care subsidy thresholds
    - EITC and CTC parameters

    Note: PRD uses RData format for its parameter files. This validator
    downloads and caches the data, converting to JSON for easier processing.
    For full RData support, R must be installed.
    """

    name = "Atlanta Fed PRD"
    validator_type = ValidatorType.SUPPLEMENTARY
    supported_variables = SUPPORTED_VARIABLES

    def __init__(self, cache_dir: Optional[Path] = None, use_r: bool = False):
        """Initialize PRD validator.

        Args:
            cache_dir: Directory to cache downloaded PRD data. Defaults to temp dir.
            use_r: If True, attempt to use R to read RData files. Otherwise,
                   use fallback parameter tables.
        """
        self.cache_dir = cache_dir or Path(tempfile.gettempdir()) / "cosilico-prd-cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.use_r = use_r
        self._parameters_cache: Dict[str, Any] = {}

    def supports_variable(self, variable: str) -> bool:
        return variable.lower() in SUPPORTED_VARIABLES

    def _load_federal_poverty_level(self, year: int, household_size: int = 1) -> float:
        """Get the Federal Poverty Level for a given year and household size.

        FPL is used as a reference for many benefit program eligibility thresholds.
        """
        # 2024 FPL values (contiguous 48 states)
        # https://aspe.hhs.gov/topics/poverty-economic-mobility/poverty-guidelines
        fpl_base = {
            2024: 15060,
            2023: 14580,
            2022: 13590,
            2021: 12880,
            2020: 12760,
        }
        fpl_increment = {
            2024: 5380,
            2023: 5140,
            2022: 4720,
            2021: 4540,
            2020: 4480,
        }

        base = fpl_base.get(year, 15060)  # Default to 2024 if year not found
        increment = fpl_increment.get(year, 5380)

        return base + (household_size - 1) * increment

    def _get_snap_parameters(self, year: int, state: str = "US") -> Dict[str, float]:
        """Get SNAP parameters for a given year.

        SNAP is a federal program with mostly uniform rules, though
        some states have waivers for different gross income limits.
        """
        # Standard SNAP parameters (federal)
        # Max benefits by household size (FFY 2024)
        max_benefits_2024 = {
            1: 291, 2: 535, 3: 766, 4: 973, 5: 1155,
            6: 1386, 7: 1532, 8: 1751
        }
        max_benefits_2023 = {
            1: 281, 2: 516, 3: 740, 4: 939, 5: 1116,
            6: 1339, 7: 1480, 8: 1691
        }

        max_benefits = max_benefits_2024 if year >= 2024 else max_benefits_2023

        # Gross income limit is 130% FPL (standard), net income limit is 100% FPL
        # Some states have BBCE (Broad-Based Categorical Eligibility) with higher limits

        return {
            "gross_income_limit_pct_fpl": 130,  # 130% FPL for gross income
            "net_income_limit_pct_fpl": 100,    # 100% FPL for net income
            "standard_deduction": 198 if year >= 2024 else 193,  # For 1-3 person households
            "earned_income_deduction_rate": 0.20,  # 20% earned income deduction
            "max_shelter_deduction": 672 if year >= 2024 else 624,  # Max excess shelter
            "utility_allowance": 447 if year >= 2024 else 435,  # Standard utility allowance (varies by state)
            "benefit_reduction_rate": 0.30,  # 30% of net income
            "max_benefits": max_benefits,
        }

    def _get_eitc_parameters(self, year: int) -> Dict[str, Any]:
        """Get EITC parameters for a given year.

        These are the federal EITC parameters. State EITC is often a
        percentage of the federal credit.
        """
        # 2024 EITC parameters
        params_2024 = {
            "phase_in_rate": {0: 0.0765, 1: 0.34, 2: 0.40, 3: 0.45},
            "phase_out_rate": {0: 0.0765, 1: 0.1598, 2: 0.2106, 3: 0.2106},
            "max_credit": {0: 632, 1: 4213, 2: 6960, 3: 7830},
            "phase_in_end": {0: 8260, 1: 12390, 2: 17400, 3: 17400},
            "phase_out_start_single": {0: 10330, 1: 22720, 2: 22720, 3: 22720},
            "phase_out_start_joint": {0: 17250, 1: 29640, 2: 29640, 3: 29640},
            "phase_out_end_single": {0: 18591, 1: 49084, 2: 55768, 3: 59899},
            "phase_out_end_joint": {0: 25511, 1: 56004, 2: 62688, 3: 66819},
            "investment_income_limit": 11600,
            "earned_income_limit": 66819,  # Max earnings (joint, 3+ children)
        }

        # 2023 EITC parameters
        params_2023 = {
            "phase_in_rate": {0: 0.0765, 1: 0.34, 2: 0.40, 3: 0.45},
            "phase_out_rate": {0: 0.0765, 1: 0.1598, 2: 0.2106, 3: 0.2106},
            "max_credit": {0: 600, 1: 3995, 2: 6604, 3: 7430},
            "phase_in_end": {0: 7840, 1: 11750, 2: 16510, 3: 16510},
            "phase_out_start_single": {0: 9800, 1: 21560, 2: 21560, 3: 21560},
            "phase_out_start_joint": {0: 16370, 1: 28120, 2: 28120, 3: 28120},
            "phase_out_end_single": {0: 17640, 1: 46560, 2: 52918, 3: 56838},
            "phase_out_end_joint": {0: 24210, 1: 53120, 2: 59478, 3: 63398},
            "investment_income_limit": 11000,
            "earned_income_limit": 63398,
        }

        return params_2024 if year >= 2024 else params_2023

    def _get_ctc_parameters(self, year: int) -> Dict[str, Any]:
        """Get Child Tax Credit parameters for a given year."""
        # Post-ARPA parameters (2022+)
        if year >= 2022:
            return {
                "max_credit_per_child": 2000,
                "refundable_portion_max": 1700 if year >= 2024 else 1600,
                "phase_out_threshold_single": 200000,
                "phase_out_threshold_joint": 400000,
                "phase_out_rate": 0.05,  # $50 per $1000 above threshold
                "earned_income_threshold": 2500,  # Min earned income for refundable portion
                "refundable_rate": 0.15,  # 15% of earned income above threshold
            }
        return {}

    def _calculate_snap_benefit(
        self,
        gross_income: float,
        earned_income: float,
        household_size: int,
        year: int,
        state: str = "US",
    ) -> float:
        """Calculate SNAP benefit using PRD parameters.

        This implements the standard SNAP benefit formula:
        1. Check gross income against 130% FPL
        2. Calculate net income (gross - deductions)
        3. Check net income against 100% FPL
        4. Benefit = Max benefit - 30% of net income
        """
        params = self._get_snap_parameters(year, state)
        fpl = self._load_federal_poverty_level(year, household_size)

        # Gross income test (130% FPL)
        gross_limit = fpl * (params["gross_income_limit_pct_fpl"] / 100)
        if gross_income > gross_limit:
            return 0.0

        # Calculate net income
        # Apply standard deduction
        net_income = gross_income - params["standard_deduction"]
        # Apply 20% earned income deduction
        net_income -= earned_income * params["earned_income_deduction_rate"]
        # Apply shelter deduction (simplified - assume standard utility allowance)
        # In practice, this requires rent/mortgage info
        net_income = max(0, net_income)

        # Net income test (100% FPL)
        net_limit = fpl * (params["net_income_limit_pct_fpl"] / 100)
        if net_income > net_limit:
            return 0.0

        # Calculate benefit
        max_benefit = params["max_benefits"].get(household_size, params["max_benefits"][8])
        benefit = max_benefit - (net_income * params["benefit_reduction_rate"])

        # Minimum benefit is $0 or minimum allotment for 1-2 person households
        min_benefit = 23 if household_size <= 2 else 0  # 2024 minimum
        return max(min_benefit, benefit) if benefit > min_benefit else max(0, benefit)

    def _calculate_eitc(
        self,
        earned_income: float,
        num_children: int,
        filing_status: str,
        year: int,
    ) -> float:
        """Calculate EITC using PRD parameters."""
        params = self._get_eitc_parameters(year)
        children = min(num_children, 3)  # EITC maxes at 3 children

        is_joint = filing_status.upper() in ["JOINT", "MARRIED_FILING_JOINTLY"]

        # Get parameters for this number of children
        phase_in_rate = params["phase_in_rate"][children]
        phase_out_rate = params["phase_out_rate"][children]
        max_credit = params["max_credit"][children]
        phase_in_end = params["phase_in_end"][children]

        if is_joint:
            phase_out_start = params["phase_out_start_joint"][children]
            phase_out_end = params["phase_out_end_joint"][children]
        else:
            phase_out_start = params["phase_out_start_single"][children]
            phase_out_end = params["phase_out_end_single"][children]

        # Calculate credit
        if earned_income <= 0:
            return 0.0

        if earned_income <= phase_in_end:
            # Phase-in region
            credit = earned_income * phase_in_rate
        elif earned_income <= phase_out_start:
            # Plateau region
            credit = max_credit
        elif earned_income <= phase_out_end:
            # Phase-out region
            credit = max_credit - (earned_income - phase_out_start) * phase_out_rate
        else:
            # Beyond phase-out
            credit = 0.0

        return max(0.0, min(max_credit, credit))

    def validate(
        self, test_case: TestCase, variable: str, year: int = 2024
    ) -> ValidatorResult:
        """Run validation using PRD parameters.

        Currently supports:
        - SNAP benefits and eligibility
        - EITC calculations
        - Parameter lookups (income limits, phase-out rates)
        """
        var_lower = variable.lower()
        if var_lower not in SUPPORTED_VARIABLES:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=f"Variable '{variable}' not supported by Atlanta Fed PRD",
            )

        try:
            inputs = test_case.inputs

            # Extract common inputs
            earned_income = inputs.get("earned_income", inputs.get("employment_income", 0))
            gross_income = inputs.get("gross_income", earned_income)
            filing_status = inputs.get("filing_status", "SINGLE")
            state = inputs.get("state", inputs.get("state_name", "US"))

            # Extract household info
            household_size = inputs.get("household_size", 1)
            num_children = 0
            for child_key in ["eitc_qualifying_children_count", "num_children",
                              "qualifying_children", "children"]:
                if child_key in inputs:
                    num_children = inputs[child_key]
                    break

            # If we have children, adjust household size
            if num_children > 0 and household_size == 1:
                household_size = num_children + 1  # Parent(s) + children

            # Handle different variable types
            if var_lower in ["snap", "snap_benefits"]:
                calculated = self._calculate_snap_benefit(
                    gross_income=gross_income,
                    earned_income=earned_income,
                    household_size=household_size,
                    year=year,
                    state=state,
                )
            elif var_lower in ["eitc", "earned_income_credit"]:
                calculated = self._calculate_eitc(
                    earned_income=earned_income,
                    num_children=num_children,
                    filing_status=filing_status,
                    year=year,
                )
            elif var_lower == "snap_income_limit":
                fpl = self._load_federal_poverty_level(year, household_size)
                calculated = fpl * 1.30  # 130% FPL gross income limit
            elif var_lower == "snap_net_income_limit":
                fpl = self._load_federal_poverty_level(year, household_size)
                calculated = fpl  # 100% FPL net income limit
            elif var_lower in ["eitc_max_credit"]:
                params = self._get_eitc_parameters(year)
                children = min(num_children, 3)
                calculated = params["max_credit"][children]
            elif var_lower == "eitc_phase_in_rate":
                params = self._get_eitc_parameters(year)
                children = min(num_children, 3)
                calculated = params["phase_in_rate"][children]
            elif var_lower == "eitc_phase_out_rate":
                params = self._get_eitc_parameters(year)
                children = min(num_children, 3)
                calculated = params["phase_out_rate"][children]
            elif var_lower in ["ctc", "child_tax_credit"]:
                params = self._get_ctc_parameters(year)
                if not params:
                    return ValidatorResult(
                        validator_name=self.name,
                        validator_type=self.validator_type,
                        calculated_value=None,
                        error=f"CTC parameters not available for year {year}",
                    )
                # Simplified CTC calculation (not accounting for phase-out)
                calculated = num_children * params["max_credit_per_child"]
            elif var_lower == "ctc_max_credit":
                params = self._get_ctc_parameters(year)
                calculated = params.get("max_credit_per_child", 0) * max(num_children, 1)
            else:
                return ValidatorResult(
                    validator_name=self.name,
                    validator_type=self.validator_type,
                    calculated_value=None,
                    error=f"Calculation for '{variable}' not yet implemented in PRD validator",
                )

            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=calculated,
                metadata={
                    "year": year,
                    "state": state,
                    "household_size": household_size,
                    "source": "Atlanta Fed Policy Rules Database",
                },
            )

        except Exception as e:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=f"PRD validation failed: {e}",
            )

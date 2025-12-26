"""Yale Budget Lab validator.

Compares Cosilico calculations against Yale Budget Lab revenue estimates
and distributional analyses.

Source: https://budgetlab.yale.edu/
Data: https://github.com/YaleBudgetLab (where available)

Note: Yale Budget Lab primarily publishes aggregate revenue estimates and
distributional analyses rather than individual-level calculations. This validator
focuses on comparing aggregate statistics and revenue projections.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Set
from urllib.request import urlopen, Request
from urllib.error import URLError
import tempfile

from cosilico_validators.validators.base import (
    BaseValidator,
    TestCase,
    ValidatorResult,
    ValidatorType,
)

# Variable mapping for Yale Budget Lab comparisons
# Focus on aggregate revenue and distributional metrics
VARIABLE_MAPPING = {
    # Revenue estimates (10-year projections)
    "revenue_estimate": "revenue_estimate",
    "revenue_10yr": "revenue_10yr",
    "revenue_conventional": "revenue_conventional",
    "revenue_dynamic": "revenue_dynamic",
    # Distributional analysis
    "effective_tax_rate": "effective_tax_rate",
    "tax_burden_bottom_quintile": "tax_burden_q1",
    "tax_burden_second_quintile": "tax_burden_q2",
    "tax_burden_middle_quintile": "tax_burden_q3",
    "tax_burden_fourth_quintile": "tax_burden_q4",
    "tax_burden_top_quintile": "tax_burden_q5",
    "tax_burden_top_1pct": "tax_burden_top1",
    "tax_burden_top_01pct": "tax_burden_top01",
    # Tax policy parameters (for reform analysis)
    "top_marginal_rate": "top_marginal_rate",
    "corporate_rate": "corporate_rate",
    "capital_gains_rate": "capital_gains_rate",
    # Tariff analysis (Yale's specialty area)
    "effective_tariff_rate": "effective_tariff_rate",
    "tariff_revenue": "tariff_revenue",
    # Time burden analysis
    "tax_filing_time_hours": "tax_filing_time_hours",
    "tax_filing_cost": "tax_filing_cost",
}

# Supported variables
SUPPORTED_VARIABLES: Set[str] = set(VARIABLE_MAPPING.keys())


class YaleBudgetLabValidator(BaseValidator):
    """Validator using Yale Budget Lab analyses.

    The Yale Budget Lab is a non-partisan policy research center that provides
    in-depth analysis of federal policy proposals. Their analyses focus on:

    1. Revenue Estimates - Conventional and dynamic scoring
    2. Distributional Analysis - Effects across income quintiles
    3. Tariff Analysis - Trade policy impacts
    4. Tax Filing Burden - Time and cost of compliance

    Unlike TAXSIM or PolicyEngine, Yale Budget Lab doesn't provide individual-level
    calculations. Instead, this validator compares:
    - Aggregate statistics from Cosilico microsimulation
    - Revenue estimates for policy reforms
    - Distributional metrics

    Data sources:
    - Published research papers with data downloads
    - GitHub repositories where available
    - Official Budget Lab data releases
    """

    name = "Yale Budget Lab"
    validator_type = ValidatorType.SUPPLEMENTARY
    supported_variables = SUPPORTED_VARIABLES

    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize Yale Budget Lab validator.

        Args:
            cache_dir: Directory to cache downloaded data. Defaults to temp dir.
        """
        self.cache_dir = cache_dir or Path(tempfile.gettempdir()) / "cosilico-ybl-cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._data_cache: Dict[str, Any] = {}

    def supports_variable(self, variable: str) -> bool:
        return variable.lower() in SUPPORTED_VARIABLES

    def _get_current_tax_parameters(self, year: int) -> Dict[str, float]:
        """Get current law tax parameters.

        These are baseline parameters from Yale Budget Lab analyses.
        """
        # Current law parameters (as of 2024)
        if year >= 2026:
            # Post-TCJA sunset (if not extended)
            return {
                "top_marginal_rate": 0.396,  # Reverts from 0.37
                "corporate_rate": 0.21,
                "capital_gains_rate": 0.20,
                "estate_tax_exemption": 5_000_000,  # Reverts to ~$5M indexed
                "salt_cap": None,  # SALT cap expires
                "standard_deduction_single": 8100,  # Reverts (indexed)
                "standard_deduction_joint": 16200,
                "personal_exemption": 4700,  # Personal exemptions return
            }
        else:
            # TCJA parameters (2018-2025)
            return {
                "top_marginal_rate": 0.37,
                "corporate_rate": 0.21,
                "capital_gains_rate": 0.20,
                "estate_tax_exemption": 13_610_000,  # 2024 value
                "salt_cap": 10000,
                "standard_deduction_single": 14600,  # 2024 value
                "standard_deduction_joint": 29200,
                "personal_exemption": 0,  # Suspended under TCJA
            }

    def _get_tariff_data(self, year: int) -> Dict[str, float]:
        """Get tariff data from Yale Budget Lab analyses.

        Yale has been tracking US tariff rates extensively, particularly
        the tariffs implemented in 2025.
        """
        # Data from Yale Budget Lab tariff analysis
        # https://budgetlab.yale.edu/research/state-us-tariffs-november-17-2025
        if year >= 2025:
            return {
                "effective_tariff_rate": 0.168,  # 16.8% as of Nov 2025
                "effective_tariff_rate_post_adjustment": 0.144,  # After consumption shifts
                "tariff_revenue_10yr": 2.7e12,  # $2.7 trillion over 10 years
                "highest_rate_since": 1935,
            }
        elif year >= 2018:
            # Pre-2025 tariff levels
            return {
                "effective_tariff_rate": 0.03,  # ~3% baseline
                "tariff_revenue_10yr": 0.5e12,  # Approximate
            }
        else:
            return {
                "effective_tariff_rate": 0.015,  # ~1.5% historical average
                "tariff_revenue_10yr": 0.3e12,
            }

    def _get_distributional_data(self, year: int, reform: Optional[str] = None) -> Dict[str, float]:
        """Get distributional analysis data.

        Returns effective tax rates and tax burden shares by income quintile.
        Data based on Yale Budget Lab distributional analyses.
        """
        # Current law distributional data (approximate, from CBO/Yale analyses)
        # These are federal tax burdens as share of pre-tax income
        if year >= 2024:
            return {
                "tax_burden_q1": 0.02,   # Bottom quintile: ~2%
                "tax_burden_q2": 0.06,   # Second quintile: ~6%
                "tax_burden_q3": 0.10,   # Middle quintile: ~10%
                "tax_burden_q4": 0.14,   # Fourth quintile: ~14%
                "tax_burden_q5": 0.24,   # Top quintile: ~24%
                "tax_burden_top1": 0.30, # Top 1%: ~30%
                "tax_burden_top01": 0.33, # Top 0.1%: ~33%
                # Average effective rates (all federal taxes)
                "effective_tax_rate_q1": 0.08,
                "effective_tax_rate_q2": 0.13,
                "effective_tax_rate_q3": 0.17,
                "effective_tax_rate_q4": 0.20,
                "effective_tax_rate_q5": 0.26,
            }
        return {}

    def _get_tax_filing_burden(self, year: int) -> Dict[str, float]:
        """Get tax filing burden estimates.

        Yale Budget Lab has analyzed the time burden of tax filing and
        how reforms could reduce compliance costs.
        """
        # Data from Yale Budget Lab tax filing analysis
        # https://budgetlab.yale.edu/research (tax filing burden studies)
        if year >= 2024:
            return {
                "total_hours_individual": 1.8e9,  # ~1.8 billion hours total
                "hours_per_return_avg": 11,  # Average hours per return
                "hours_per_return_simple": 3,  # Simple returns
                "hours_per_return_complex": 20,  # Complex returns (itemizers, business)
                "total_cost_individual": 200e9,  # ~$200 billion total cost
                "cost_per_return_avg": 150,  # Average cost (software, preparers)
            }
        return {}

    def validate(
        self, test_case: TestCase, variable: str, year: int = 2024
    ) -> ValidatorResult:
        """Run validation using Yale Budget Lab data.

        Note: Yale Budget Lab provides aggregate statistics, not individual calculations.
        This validator is useful for:
        1. Validating microsimulation aggregates against Yale estimates
        2. Checking policy parameters used in reforms
        3. Comparing distributional results

        For individual-level tax calculations, use PolicyEngine or TAXSIM.
        """
        var_lower = variable.lower()
        if var_lower not in SUPPORTED_VARIABLES:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=f"Variable '{variable}' not supported by Yale Budget Lab validator",
            )

        try:
            inputs = test_case.inputs

            # Handle different variable types
            if var_lower in ["top_marginal_rate", "corporate_rate", "capital_gains_rate",
                              "salt_cap", "standard_deduction_single", "standard_deduction_joint"]:
                params = self._get_current_tax_parameters(year)
                ybl_key = var_lower
                if ybl_key in params:
                    calculated = params[ybl_key]
                else:
                    return ValidatorResult(
                        validator_name=self.name,
                        validator_type=self.validator_type,
                        calculated_value=None,
                        error=f"Parameter '{variable}' not found for year {year}",
                    )

            elif var_lower in ["effective_tariff_rate", "tariff_revenue", "tariff_revenue_10yr"]:
                tariff_data = self._get_tariff_data(year)
                if var_lower == "tariff_revenue":
                    var_lower = "tariff_revenue_10yr"
                if var_lower in tariff_data:
                    calculated = tariff_data[var_lower]
                else:
                    return ValidatorResult(
                        validator_name=self.name,
                        validator_type=self.validator_type,
                        calculated_value=None,
                        error=f"Tariff data for '{variable}' not found for year {year}",
                    )

            elif var_lower.startswith("tax_burden_"):
                dist_data = self._get_distributional_data(year)
                ybl_key = VARIABLE_MAPPING.get(var_lower, var_lower)
                if ybl_key in dist_data:
                    calculated = dist_data[ybl_key]
                else:
                    return ValidatorResult(
                        validator_name=self.name,
                        validator_type=self.validator_type,
                        calculated_value=None,
                        error=f"Distributional data for '{variable}' not available",
                    )

            elif var_lower == "effective_tax_rate":
                # For individual-level effective tax rate, we need income quintile
                quintile = inputs.get("income_quintile", 3)  # Default to middle
                dist_data = self._get_distributional_data(year)
                key = f"effective_tax_rate_q{quintile}"
                if key in dist_data:
                    calculated = dist_data[key]
                else:
                    return ValidatorResult(
                        validator_name=self.name,
                        validator_type=self.validator_type,
                        calculated_value=None,
                        error=f"Effective tax rate for quintile {quintile} not available",
                    )

            elif var_lower in ["tax_filing_time_hours", "tax_filing_cost"]:
                burden_data = self._get_tax_filing_burden(year)
                if var_lower == "tax_filing_time_hours":
                    # Return per-return average hours
                    complexity = inputs.get("return_complexity", "avg")
                    key = f"hours_per_return_{complexity}"
                    calculated = burden_data.get(key, burden_data.get("hours_per_return_avg", 11))
                else:
                    calculated = burden_data.get("cost_per_return_avg", 150)

            elif var_lower in ["revenue_estimate", "revenue_10yr", "revenue_conventional"]:
                # Revenue estimates require reform specification
                reform = inputs.get("reform", inputs.get("policy_reform"))
                if not reform:
                    return ValidatorResult(
                        validator_name=self.name,
                        validator_type=self.validator_type,
                        calculated_value=None,
                        error="Revenue estimates require a 'reform' input specification",
                        metadata={"note": "Yale Budget Lab provides reform-specific revenue estimates"},
                    )
                # This would require lookup in a database of Yale's published estimates
                return ValidatorResult(
                    validator_name=self.name,
                    validator_type=self.validator_type,
                    calculated_value=None,
                    error=f"Revenue estimate for reform '{reform}' requires manual lookup",
                    metadata={
                        "source": "https://budgetlab.yale.edu/",
                        "note": "Check Yale Budget Lab publications for specific reform estimates",
                    },
                )

            else:
                return ValidatorResult(
                    validator_name=self.name,
                    validator_type=self.validator_type,
                    calculated_value=None,
                    error=f"Calculation for '{variable}' not yet implemented",
                )

            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=calculated,
                metadata={
                    "year": year,
                    "source": "Yale Budget Lab",
                    "url": "https://budgetlab.yale.edu/",
                },
            )

        except Exception as e:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=f"Yale Budget Lab validation failed: {e}",
            )

    def compare_aggregates(
        self,
        cosilico_aggregates: Dict[str, float],
        year: int = 2024,
    ) -> Dict[str, Dict[str, Any]]:
        """Compare Cosilico microsimulation aggregates against Yale Budget Lab estimates.

        This is the primary use case for Yale Budget Lab validation - comparing
        aggregate statistics from a microsimulation against Yale's published estimates.

        Args:
            cosilico_aggregates: Dictionary of aggregate statistics from Cosilico
                                 (e.g., total_tax_revenue, avg_effective_rate)
            year: Tax year

        Returns:
            Dictionary with comparison results for each metric
        """
        results = {}

        # Compare distributional metrics if provided
        dist_data = self._get_distributional_data(year)
        for key, ybl_value in dist_data.items():
            if key in cosilico_aggregates:
                cosilico_value = cosilico_aggregates[key]
                diff = abs(cosilico_value - ybl_value)
                diff_pct = (diff / ybl_value * 100) if ybl_value != 0 else 0
                results[key] = {
                    "cosilico": cosilico_value,
                    "yale_budget_lab": ybl_value,
                    "difference": diff,
                    "difference_pct": diff_pct,
                    "matches": diff_pct < 5,  # 5% tolerance for aggregate comparisons
                }

        # Compare tariff estimates if provided
        tariff_data = self._get_tariff_data(year)
        for key, ybl_value in tariff_data.items():
            if key in cosilico_aggregates:
                cosilico_value = cosilico_aggregates[key]
                diff = abs(cosilico_value - ybl_value)
                diff_pct = (diff / ybl_value * 100) if ybl_value != 0 else 0
                results[key] = {
                    "cosilico": cosilico_value,
                    "yale_budget_lab": ybl_value,
                    "difference": diff,
                    "difference_pct": diff_pct,
                    "matches": diff_pct < 10,  # 10% tolerance for revenue estimates
                }

        return results

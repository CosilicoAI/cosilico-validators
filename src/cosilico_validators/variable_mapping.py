"""Variable mappings from Cosilico to external validators (PolicyEngine, TAXSIM).

This is the single source of truth for mapping Cosilico variable names to
external validator variable names. The CPS runner uses this to:
1. Discover which variables to validate
2. Map Cosilico outputs to PE/TAXSIM equivalents
3. Know which inputs each variable needs
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path
import yaml


@dataclass
class VariableMapping:
    """Mapping for a single variable between Cosilico and external validators."""

    # Cosilico info
    cosilico_variable: str  # Variable name in .cosilico file
    cosilico_file: str  # Path relative to cosilico-us (e.g., "statute/26/1411/niit.cosilico")

    # Statute reference
    statute: str  # e.g., "26 USC § 1411"
    title: str  # Human-readable name

    # External validator mappings
    pe_variable: Optional[str] = None  # PolicyEngine variable name
    taxsim_variable: Optional[str] = None  # TAXSIM output column (e.g., "v25")

    # Required inputs from PE
    required_inputs: List[str] = field(default_factory=list)

    # Validation settings
    tolerance: float = 15.0  # Dollar tolerance for matching


# Master mapping - defines all variables we can validate
VARIABLE_MAPPINGS: Dict[str, VariableMapping] = {
    # =========================================================================
    # TITLE 26 - INTERNAL REVENUE CODE
    # =========================================================================

    # §32 - Earned Income Credit
    "eitc": VariableMapping(
        cosilico_variable="earned_income_credit",
        cosilico_file="statute/26/32/a/1/earned_income_credit.cosilico",
        statute="26 USC § 32",
        title="Earned Income Tax Credit",
        pe_variable="eitc",
        taxsim_variable="v25",
        required_inputs=["earned_income", "adjusted_gross_income", "filing_status", "ctc_qualifying_children"],
    ),

    # §24 - Child Tax Credit
    "ctc": VariableMapping(
        cosilico_variable="child_tax_credit",
        cosilico_file="statute/26/24/child_tax_credit.cosilico",
        statute="26 USC § 24",
        title="Child Tax Credit",
        pe_variable="ctc",
        taxsim_variable="v22",
        required_inputs=["adjusted_gross_income", "filing_status", "ctc_qualifying_children"],
    ),

    # §63 - Standard Deduction
    "standard_deduction": VariableMapping(
        cosilico_variable="standard_deduction",
        cosilico_file="statute/26/63/standard_deduction.cosilico",
        statute="26 USC § 63",
        title="Standard Deduction",
        pe_variable="standard_deduction",
        taxsim_variable=None,  # TAXSIM computes but doesn't output separately
        required_inputs=["filing_status", "age", "is_blind"],
    ),

    # §62 - Adjusted Gross Income
    "agi": VariableMapping(
        cosilico_variable="adjusted_gross_income",
        cosilico_file="statute/26/62/a/adjusted_gross_income.cosilico",
        statute="26 USC § 62",
        title="Adjusted Gross Income",
        pe_variable="adjusted_gross_income",
        taxsim_variable="v10",
        required_inputs=["employment_income", "self_employment_income", "interest_income",
                         "dividend_income", "rental_income", "capital_gains"],
    ),

    # §1411 - Net Investment Income Tax
    "niit": VariableMapping(
        cosilico_variable="net_investment_income_tax",
        cosilico_file="statute/26/1411/net_investment_income_tax.cosilico",
        statute="26 USC § 1411",
        title="Net Investment Income Tax",
        pe_variable="net_investment_income_tax",
        taxsim_variable=None,  # TAXSIM-35 doesn't have NIIT
        required_inputs=["adjusted_gross_income", "interest_income", "dividend_income",
                         "long_term_capital_gains", "short_term_capital_gains",
                         "rental_income", "filing_status"],
    ),

    # §3101(b)(2) - Additional Medicare Tax
    "additional_medicare_tax": VariableMapping(
        cosilico_variable="additional_medicare_tax",
        cosilico_file="statute/26/3101/b/2/additional_medicare_tax.cosilico",
        statute="26 USC § 3101(b)(2)",
        title="Additional Medicare Tax",
        pe_variable="additional_medicare_tax",
        taxsim_variable=None,  # TAXSIM-35 doesn't have this
        required_inputs=["employment_income", "self_employment_income", "filing_status"],
    ),

    # §1401 - Self-Employment Tax
    "self_employment_tax": VariableMapping(
        cosilico_variable="self_employment_tax",
        cosilico_file="statute/26/1401/self_employment_tax.cosilico",
        statute="26 USC § 1401",
        title="Self-Employment Tax",
        pe_variable="self_employment_tax",
        taxsim_variable="v16",
        required_inputs=["self_employment_income"],
    ),

    # §1(h) - Capital Gains Tax
    "capital_gains_tax": VariableMapping(
        cosilico_variable="capital_gains_tax",
        cosilico_file="statute/26/1/h/capital_gains_tax.cosilico",
        statute="26 USC § 1(h)",
        title="Capital Gains Tax",
        pe_variable="capital_gains_tax",
        taxsim_variable=None,
        required_inputs=["long_term_capital_gains", "short_term_capital_gains",
                         "taxable_income", "filing_status"],
    ),

    # §199A - Qualified Business Income Deduction
    "qbi_deduction": VariableMapping(
        cosilico_variable="qualified_business_income_deduction",
        cosilico_file="statute/26/199A/qbi_deduction.cosilico",
        statute="26 USC § 199A",
        title="Qualified Business Income Deduction",
        pe_variable="qualified_business_income_deduction",
        taxsim_variable=None,
        required_inputs=["self_employment_income", "taxable_income", "filing_status"],
    ),

    # §36B - Premium Tax Credit
    "ptc": VariableMapping(
        cosilico_variable="premium_tax_credit",
        cosilico_file="statute/26/36B/premium_tax_credit.cosilico",
        statute="26 USC § 36B",
        title="Premium Tax Credit",
        pe_variable="premium_tax_credit",
        taxsim_variable=None,  # TAXSIM doesn't have health credits
        required_inputs=["adjusted_gross_income", "household_size", "filing_status",
                         "is_marketplace_health_coverage_enrolled"],
    ),

    # §86 - Taxable Social Security
    "taxable_social_security": VariableMapping(
        cosilico_variable="taxable_social_security",
        cosilico_file="statute/26/86/taxable_social_security.cosilico",
        statute="26 USC § 86",
        title="Taxable Social Security Benefits",
        pe_variable="taxable_social_security",
        taxsim_variable="v19",
        required_inputs=["social_security_benefits", "adjusted_gross_income", "filing_status"],
    ),

    # =========================================================================
    # TITLE 7 - AGRICULTURE (SNAP)
    # =========================================================================

    "snap": VariableMapping(
        cosilico_variable="snap_allotment",
        cosilico_file="statute/7/2017/a/allotment.cosilico",
        statute="7 USC § 2017",
        title="SNAP Allotment",
        pe_variable="snap",
        taxsim_variable=None,  # TAXSIM doesn't cover benefits
        required_inputs=["household_size", "gross_income", "net_income", "is_snap_eligible"],
    ),
}


def get_all_required_inputs() -> List[str]:
    """Get all unique input variables needed across all mappings."""
    inputs = set()
    for mapping in VARIABLE_MAPPINGS.values():
        inputs.update(mapping.required_inputs)
    return sorted(inputs)


def get_mapping(variable_name: str) -> Optional[VariableMapping]:
    """Get mapping for a variable by name."""
    return VARIABLE_MAPPINGS.get(variable_name)


def get_variables_with_pe_mapping() -> List[str]:
    """Get list of variables that have PolicyEngine mappings."""
    return [name for name, m in VARIABLE_MAPPINGS.items() if m.pe_variable]


def get_variables_with_taxsim_mapping() -> List[str]:
    """Get list of variables that have TAXSIM mappings."""
    return [name for name, m in VARIABLE_MAPPINGS.items() if m.taxsim_variable]


def discover_cosilico_files(cosilico_us_path: Path) -> Dict[str, Path]:
    """Discover all .cosilico files in cosilico-us repo."""
    discovered = {}
    for cosilico_file in cosilico_us_path.rglob("*.cosilico"):
        rel_path = str(cosilico_file.relative_to(cosilico_us_path))
        # Find matching mapping
        for name, mapping in VARIABLE_MAPPINGS.items():
            if mapping.cosilico_file == rel_path:
                discovered[name] = cosilico_file
                break
    return discovered

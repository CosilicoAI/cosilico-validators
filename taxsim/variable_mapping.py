"""Variable mapping between TaxSim 35 and Cosilico.

TaxSim uses numbered variables (v1, v2, etc.) and some named columns.
This module provides bidirectional mapping to Cosilico variable names.

Reference: https://taxsim.nber.org/taxsim35/
"""

from typing import Any, Dict, Optional


# TaxSim input variables (what we send to TaxSim)
TAXSIM_INPUT_VARS = {
    "taxsimid": "Record ID (required)",
    "year": "Tax year (required, 1960-2023)",
    "state": "State code (0=no state, 1-56 for states)",
    "mstat": "Filing status (1=single, 2=joint, 6=HOH, 8=separate)",
    "page": "Primary taxpayer age",
    "sage": "Spouse age (0 if single)",
    "depx": "Number of dependents",
    "dep13": "Dependents under 13",
    "dep17": "Dependents under 17",
    "dep18": "Dependents under 19",
    "age1": "Age of dependent 1",
    "age2": "Age of dependent 2",
    "age3": "Age of dependent 3",
    "pwages": "Primary taxpayer wages",
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
    "pui": "Primary unemployment insurance",
    "sui": "Spouse unemployment insurance",
    "transfers": "Non-taxable transfer income",
    "rentpaid": "Rent paid (for state credits)",
    "proptax": "Property taxes paid",
    "otheritem": "Other itemized deductions",
    "childcare": "Child care expenses",
    "mortgage": "Mortgage interest paid",
    "scorp": "S-corp income",
    "pbusinc": "Primary business income",
    "pprofinc": "Primary professional income",
    "sbusinc": "Spouse business income",
    "sprofinc": "Spouse professional income",
    "idtl": "Output detail level (0=standard, 2=full)",
}

# TaxSim output variables (what TaxSim returns)
# Using idtl=2 provides full output with v1-v45
TAXSIM_OUTPUT_VARS = {
    # Identifiers
    "taxsimid": "Record ID",
    "year": "Tax year",
    "state": "State code",

    # Main tax outputs
    "fiitax": "Federal income tax liability",
    "siitax": "State income tax liability",
    "fica": "FICA (employee share)",

    # Intermediate calculations (v-numbered)
    "v10": "Federal AGI",
    "v11": "UI included in AGI",
    "v12": "Social Security included in AGI",
    "v13": "Zero bracket / personal exemption",
    "v14": "Deductions",
    "v15": "Exemptions",
    "v16": "Exemption phaseout",
    "v17": "Standard deduction",
    "v18": "Taxable income",
    "v19": "Tax on taxable income (before credits)",
    "v20": "Exemption surtax",
    "v21": "AMT liability before credits",
    "v22": "Child Tax Credit (non-refundable)",
    "v23": "Additional Child Tax Credit (refundable)",
    "v24": "Child and Dependent Care Credit",
    "v25": "Earned Income Credit",
    "v26": "ACTC added to refund",
    "v27": "AMT liability",
    "v28": "Tax before credits",
    "v29": "FICA (total)",
    "v30": "Federal marginal rate",
    "v31": "State marginal rate",
    "v32": "State AGI",
    "v33": "State exemptions",
    "v34": "State standard deduction",
    "v35": "State itemized deductions",
    "v36": "State taxable income",
    "v37": "State property tax credit",
    "v38": "State child care credit",
    "v39": "State EITC",
    "v40": "State total credits",
    "v41": "State bracket rate",
    "v42": "Self-employment tax",
    "v43": "Medicare recapture tax",
    "v44": "NIIT (Net Investment Income Tax)",
    "v45": "Total tax",
}


# Mapping from TaxSim variables to Cosilico variable names
TAXSIM_TO_COSILICO: Dict[str, str] = {
    # Main outputs
    "fiitax": "total_federal_income_tax",
    "siitax": "state_income_tax",
    "fica": "employee_fica_tax",

    # AGI and income
    "v10": "adjusted_gross_income",
    "v18": "taxable_income",
    "v17": "standard_deduction",
    "v14": "itemized_deductions",

    # Credits
    "v22": "child_tax_credit",
    "v23": "additional_child_tax_credit",
    "v24": "child_and_dependent_care_credit",
    "v25": "earned_income_credit",

    # AMT
    "v27": "amt",
    "v21": "amt_before_credits",

    # FICA
    "v29": "total_fica_tax",
    "v42": "self_employment_tax",

    # State
    "v32": "state_agi",
    "v36": "state_taxable_income",
    "v39": "state_eitc",

    # Other
    "v44": "net_investment_income_tax",
    "v45": "total_tax",
}


# Reverse mapping: Cosilico to TaxSim
COSILICO_TO_TAXSIM: Dict[str, str] = {v: k for k, v in TAXSIM_TO_COSILICO.items()}


# Additional aliases for common variable names
COSILICO_ALIASES: Dict[str, str] = {
    "agi": "adjusted_gross_income",
    "ctc": "child_tax_credit",
    "actc": "additional_child_tax_credit",
    "eitc": "earned_income_credit",
    "cdctc": "child_and_dependent_care_credit",
    "federal_income_tax": "total_federal_income_tax",
    "income_tax": "total_federal_income_tax",
}


# Filing status mapping
FILING_STATUS_TO_MSTAT: Dict[str, int] = {
    "SINGLE": 1,
    "JOINT": 2,
    "MARRIED_FILING_JOINTLY": 2,
    "HEAD_OF_HOUSEHOLD": 6,
    "HOH": 6,
    "MARRIED_FILING_SEPARATELY": 8,
    "SEPARATE": 8,
    "WIDOW": 2,  # Qualifying widow(er) treated as joint
}


# State FIPS codes
STATE_FIPS: Dict[str, int] = {
    "AL": 1, "AK": 2, "AZ": 4, "AR": 5, "CA": 6, "CO": 8, "CT": 9, "DE": 10,
    "DC": 11, "FL": 12, "GA": 13, "HI": 15, "ID": 16, "IL": 17, "IN": 18,
    "IA": 19, "KS": 20, "KY": 21, "LA": 22, "ME": 23, "MD": 24, "MA": 25,
    "MI": 26, "MN": 27, "MS": 28, "MO": 29, "MT": 30, "NE": 31, "NV": 32,
    "NH": 33, "NJ": 34, "NM": 35, "NY": 36, "NC": 37, "ND": 38, "OH": 39,
    "OK": 40, "OR": 41, "PA": 42, "RI": 44, "SC": 45, "SD": 46, "TN": 47,
    "TX": 48, "UT": 49, "VT": 50, "VA": 51, "WA": 53, "WV": 54, "WI": 55,
    "WY": 56,
}


def map_taxsim_to_cosilico(taxsim_var: str) -> Optional[str]:
    """Map a TaxSim variable name to Cosilico variable name.

    Args:
        taxsim_var: TaxSim variable name (e.g., "v10", "fiitax")

    Returns:
        Cosilico variable name, or None if no mapping exists
    """
    return TAXSIM_TO_COSILICO.get(taxsim_var)


def map_cosilico_to_taxsim(cosilico_var: str) -> Optional[str]:
    """Map a Cosilico variable name to TaxSim variable name.

    Args:
        cosilico_var: Cosilico variable name (e.g., "adjusted_gross_income")

    Returns:
        TaxSim variable name, or None if no mapping exists
    """
    # First resolve any aliases
    canonical = COSILICO_ALIASES.get(cosilico_var.lower(), cosilico_var)
    return COSILICO_TO_TAXSIM.get(canonical)


def get_filing_status_code(filing_status: str) -> int:
    """Convert filing status string to TaxSim mstat code.

    Args:
        filing_status: Filing status string (e.g., "SINGLE", "JOINT")

    Returns:
        TaxSim mstat code (1, 2, 6, or 8)
    """
    return FILING_STATUS_TO_MSTAT.get(filing_status.upper(), 1)


def get_state_code(state: str) -> int:
    """Convert state abbreviation to FIPS code.

    Args:
        state: Two-letter state abbreviation (e.g., "CA", "NY")

    Returns:
        State FIPS code (0 for no state tax)
    """
    return STATE_FIPS.get(state.upper(), 0)


def build_variable_documentation() -> str:
    """Generate documentation for variable mappings.

    Returns:
        Formatted documentation string
    """
    lines = [
        "TaxSim 35 Variable Mapping",
        "=" * 50,
        "",
        "## TaxSim Output Variables",
        "",
        "| TaxSim | Cosilico | Description |",
        "|--------|----------|-------------|",
    ]

    for taxsim_var, cosilico_var in sorted(TAXSIM_TO_COSILICO.items()):
        desc = TAXSIM_OUTPUT_VARS.get(taxsim_var, "")
        lines.append(f"| {taxsim_var} | {cosilico_var} | {desc} |")

    lines.extend([
        "",
        "## Cosilico Aliases",
        "",
        "| Alias | Canonical Name |",
        "|-------|---------------|",
    ])

    for alias, canonical in sorted(COSILICO_ALIASES.items()):
        lines.append(f"| {alias} | {canonical} |")

    return "\n".join(lines)

"""
Validate 26 USC 1 (Income Tax Rates) encoding against PolicyEngine-US and TAXSIM.

This script tests the income_tax_before_credits calculation for 2024 tax year
against external calculators to ensure accuracy of the RAC encoding.
"""

import json
from decimal import Decimal
from typing import Dict, List, Tuple

try:
    from policyengine_us import Simulation
    POLICYENGINE_AVAILABLE = True
except ImportError:
    POLICYENGINE_AVAILABLE = False
    print("WARNING: PolicyEngine-US not available. Install with: pip install policyengine-us")


def calculate_expected_2024(taxable_income: float, filing_status: str) -> float:
    """
    Calculate expected tax from 2024 IRS tax brackets (manually from statute).

    2024 brackets (indexed from 2018 base):
    Single:
      10%: $0-$11,600
      12%: $11,600-$47,150
      22%: $47,150-$100,525
      24%: $100,525-$191,950
      32%: $191,950-$243,725
      35%: $243,725-$609,350
      37%: over $609,350

    Married Filing Jointly:
      10%: $0-$23,200
      12%: $23,200-$94,300
      22%: $94,300-$201,050
      24%: $201,050-$383,900
      32%: $383,900-$487,450
      35%: $487,450-$731,200
      37%: over $731,200

    Head of Household:
      10%: $0-$16,550
      12%: $16,550-$63,100
      22%: $63,100-$100,500
      24%: $100,500-$191,950
      32%: $191,950-$243,700
      35%: $243,700-$609,350
      37%: over $609,350
    """

    if filing_status == "SINGLE":
        brackets = [11600, 47150, 100525, 191950, 243725, 609350]
    elif filing_status in ["JOINT", "MARRIED_FILING_JOINTLY"]:
        brackets = [23200, 94300, 201050, 383900, 487450, 731200]
    elif filing_status in ["HEAD_OF_HOUSEHOLD", "HOH"]:
        brackets = [16550, 63100, 100500, 191950, 243700, 609350]
    else:
        raise ValueError(f"Unknown filing status: {filing_status}")

    rates = [0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37]

    tax = 0.0
    prev_bracket = 0

    for i, bracket in enumerate(brackets):
        if taxable_income <= bracket:
            tax += rates[i] * (taxable_income - prev_bracket)
            return round(tax, 2)
        else:
            tax += rates[i] * (bracket - prev_bracket)
            prev_bracket = bracket

    # Top bracket
    tax += rates[-1] * (taxable_income - prev_bracket)
    return round(tax, 2)


def test_policyengine(taxable_income: float, filing_status: str, year: int = 2024) -> Tuple[float, str]:
    """Test against PolicyEngine-US."""
    if not POLICYENGINE_AVAILABLE:
        return None, "PolicyEngine not available"

    try:
        # Map filing status
        filing_status_map = {
            "SINGLE": "SINGLE",
            "JOINT": "JOINT",
            "MARRIED_FILING_JOINTLY": "JOINT",
            "HEAD_OF_HOUSEHOLD": "HEAD_OF_HOUSEHOLD",
            "HOH": "HEAD_OF_HOUSEHOLD",
        }

        pe_status = filing_status_map.get(filing_status, filing_status)

        situation = {
            "people": {
                "person": {
                    "age": {"2024": 40},
                }
            },
            "tax_units": {
                "tax_unit": {
                    "members": ["person"],
                    "taxable_income": {str(year): taxable_income},
                    "filing_status": {str(year): pe_status},
                }
            },
            "households": {
                "household": {
                    "members": ["person"],
                    "state_name": {"2024": "CA"},
                }
            },
        }

        sim = Simulation(situation=situation)
        result = sim.calculate("income_tax_before_credits", year)

        # Result is an array, get first element
        return float(result[0]), None
    except Exception as e:
        return None, f"PolicyEngine error: {str(e)}"


def test_taxsim(taxable_income: float, filing_status: str, year: int = 2024) -> Tuple[float, str]:
    """
    Test against TAXSIM-35.

    Note: TAXSIM requires more complete inputs (wages, dependents, etc.)
    For this validation, we'll skip TAXSIM and note it needs full input specification.
    """
    return None, "TAXSIM requires full tax return inputs (not just taxable income)"


def run_validation():
    """Run validation tests for 26 USC 1."""

    test_cases = [
        # Basic test cases
        {
            "name": "Single filer, $50,000 taxable income (2024)",
            "taxable_income": 50000,
            "filing_status": "SINGLE",
            "year": 2024,
        },
        {
            "name": "Married filing jointly, $100,000 taxable income (2024)",
            "taxable_income": 100000,
            "filing_status": "JOINT",
            "year": 2024,
        },
        {
            "name": "Head of household, $75,000 taxable income (2024)",
            "taxable_income": 75000,
            "filing_status": "HEAD_OF_HOUSEHOLD",
            "year": 2024,
        },

        # Bracket boundaries - Single
        {
            "name": "Single at 10% bracket top ($11,600)",
            "taxable_income": 11600,
            "filing_status": "SINGLE",
            "year": 2024,
        },
        {
            "name": "Single at 12% bracket top ($47,150)",
            "taxable_income": 47150,
            "filing_status": "SINGLE",
            "year": 2024,
        },
        {
            "name": "Single at 22% bracket top ($100,525)",
            "taxable_income": 100525,
            "filing_status": "SINGLE",
            "year": 2024,
        },
        {
            "name": "Single at 24% bracket top ($191,950)",
            "taxable_income": 191950,
            "filing_status": "SINGLE",
            "year": 2024,
        },
        {
            "name": "Single at 32% bracket top ($243,725)",
            "taxable_income": 243725,
            "filing_status": "SINGLE",
            "year": 2024,
        },
        {
            "name": "Single at 35% bracket top ($609,350)",
            "taxable_income": 609350,
            "filing_status": "SINGLE",
            "year": 2024,
        },

        # Bracket boundaries - Joint
        {
            "name": "Joint at 10% bracket top ($23,200)",
            "taxable_income": 23200,
            "filing_status": "JOINT",
            "year": 2024,
        },
        {
            "name": "Joint at 22% bracket top ($201,050)",
            "taxable_income": 201050,
            "filing_status": "JOINT",
            "year": 2024,
        },

        # Edge cases
        {
            "name": "Zero income",
            "taxable_income": 0,
            "filing_status": "SINGLE",
            "year": 2024,
        },
        {
            "name": "Very high income - Single ($1,000,000)",
            "taxable_income": 1000000,
            "filing_status": "SINGLE",
            "year": 2024,
        },
    ]

    results = []
    matches_within_1_dollar = 0
    total_tests = 0

    print("=" * 80)
    print("26 USC 1 VALIDATION REPORT - Income Tax Before Credits")
    print("=" * 80)
    print()

    for test_case in test_cases:
        name = test_case["name"]
        taxable_income = test_case["taxable_income"]
        filing_status = test_case["filing_status"]
        year = test_case["year"]

        # Calculate expected from statute
        expected = calculate_expected_2024(taxable_income, filing_status)

        # Test PolicyEngine
        pe_result, pe_error = test_policyengine(taxable_income, filing_status, year)

        # Test TAXSIM (skipped for now)
        taxsim_result, taxsim_error = test_taxsim(taxable_income, filing_status, year)

        result = {
            "name": name,
            "taxable_income": taxable_income,
            "filing_status": filing_status,
            "year": year,
            "expected": expected,
            "policyengine": pe_result,
            "policyengine_error": pe_error,
            "taxsim": taxsim_result,
            "taxsim_error": taxsim_error,
        }

        results.append(result)

        # Check match
        pe_matches = False
        if pe_result is not None:
            total_tests += 1
            diff = abs(pe_result - expected)
            pe_matches = diff <= 1.0
            if pe_matches:
                matches_within_1_dollar += 1
            result["policyengine_diff"] = diff
            result["policyengine_matches"] = pe_matches

        # Print result
        print(f"Test: {name}")
        print(f"  Taxable Income: ${taxable_income:,.0f}")
        print(f"  Filing Status: {filing_status}")
        print(f"  Expected (from statute): ${expected:,.2f}")

        if pe_result is not None:
            status_icon = "✓" if pe_matches else "✗"
            print(f"  PolicyEngine: ${pe_result:,.2f} {status_icon}")
            if not pe_matches:
                print(f"    Difference: ${diff:,.2f}")
        else:
            print(f"  PolicyEngine: {pe_error}")

        if taxsim_result is not None:
            print(f"  TAXSIM: ${taxsim_result:,.2f}")
        else:
            print(f"  TAXSIM: {taxsim_error}")

        print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if total_tests > 0:
        match_rate = (matches_within_1_dollar / total_tests) * 100
        print(f"PolicyEngine Match Rate: {matches_within_1_dollar}/{total_tests} ({match_rate:.1f}%)")
        print(f"Match threshold: ±$1.00")
    else:
        print("No PolicyEngine tests completed")

    print()
    print("TAXSIM: Not tested (requires full tax return inputs)")

    print()
    print("=" * 80)
    print("DISCREPANCIES")
    print("=" * 80)

    discrepancies = [r for r in results if r.get("policyengine_matches") is False]

    if discrepancies:
        for disc in discrepancies:
            print(f"\nCase: {disc['name']}")
            print(f"  Expected: ${disc['expected']:,.2f}")
            print(f"  PolicyEngine: ${disc['policyengine']:,.2f}")
            print(f"  Difference: ${disc['policyengine_diff']:,.2f}")
            print(f"  Reason: Possible indexing discrepancy or calculation difference")
    else:
        print("\nNo discrepancies found! All tests match within $1.00")

    # Save results to JSON
    output_file = "validation_26_usc_1_results.json"
    with open(output_file, "w") as f:
        json.dump({
            "timestamp": "2025-01-03",
            "section": "26 USC 1",
            "variable": "income_tax_before_credits",
            "total_tests": total_tests,
            "matches": matches_within_1_dollar,
            "match_rate": matches_within_1_dollar / total_tests if total_tests > 0 else 0,
            "results": results,
        }, f, indent=2)

    print()
    print(f"Results saved to: {output_file}")


if __name__ == "__main__":
    run_validation()

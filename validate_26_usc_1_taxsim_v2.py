"""
Validate 26 USC 1 (Income Tax Rates) against TAXSIM-35 using the validator framework.
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from cosilico_validators.validators.base import TestCase
from cosilico_validators.validators.taxsim import TaxsimValidator


def calculate_expected_tax_2024(taxable_income: float, filing_status: str) -> float:
    """Calculate expected tax from 2024 brackets."""
    if filing_status == "SINGLE":
        brackets = [11600, 47150, 100525, 191950, 243725, 609350]
    elif filing_status == "JOINT":
        brackets = [23200, 94300, 201050, 383900, 487450, 731200]
    elif filing_status == "HOH":
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

    tax += rates[-1] * (taxable_income - prev_bracket)
    return round(tax, 2)


def run_validation():
    """Run TAXSIM validation for 26 USC 1."""

    # Standard deductions for 2024
    STD_DEDUCT_SINGLE_2024 = 14600
    STD_DEDUCT_JOINT_2024 = 29200
    STD_DEDUCT_HOH_2024 = 21900

    # Test cases with full inputs
    test_cases = [
        {
            "name": "Single filer, $50k wages (2024)",
            "inputs": {
                "earned_income": 50000,
                "filing_status": "SINGLE",
                "age": 40,
            },
            "year": 2023,  # TAXSIM-35 only goes up to 2023
            "filing_status": "SINGLE",
            "std_deduction": 13850,  # 2023 value
            "expected_taxable_income": 50000 - 13850,
        },
        {
            "name": "Married filing jointly, $100k wages (2024)",
            "inputs": {
                "earned_income": 100000,
                "filing_status": "JOINT",
                "age": 40,
            },
            "year": 2023,
            "filing_status": "JOINT",
            "std_deduction": 27700,  # 2023 value
            "expected_taxable_income": 100000 - 27700,
        },
        {
            "name": "Head of household, $75k wages (2024)",
            "inputs": {
                "earned_income": 75000,
                "filing_status": "HEAD_OF_HOUSEHOLD",
                "age": 40,
                "num_children": 1,
            },
            "year": 2023,
            "filing_status": "HOH",
            "std_deduction": 20800,  # 2023 value
            "expected_taxable_income": 75000 - 20800,
        },
        {
            "name": "Single filer, high income $250k (2023)",
            "inputs": {
                "earned_income": 250000,
                "filing_status": "SINGLE",
                "age": 40,
            },
            "year": 2023,
            "filing_status": "SINGLE",
            "std_deduction": 13850,
            "expected_taxable_income": 250000 - 13850,
        },
        {
            "name": "Joint filers, $117.5k wages (2023)",
            "inputs": {
                "earned_income": 117500,
                "filing_status": "JOINT",
                "age": 40,
            },
            "year": 2023,
            "filing_status": "JOINT",
            "std_deduction": 27700,
            "expected_taxable_income": 117500 - 27700,
        },
    ]

    # Use 2023 brackets for comparison since TAXSIM doesn't support 2024
    brackets_2023 = {
        "SINGLE": [11000, 44725, 95375, 182100, 231250, 578125],
        "JOINT": [22000, 89050, 190750, 364200, 462500, 693750],
        "HOH": [15700, 59850, 95350, 182100, 231250, 578100],
    }

    def calc_2023_tax(taxable_income, filing_status):
        """Calculate 2023 tax."""
        brackets = brackets_2023[filing_status]
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
        tax += rates[-1] * (taxable_income - prev_bracket)
        return round(tax, 2)

    print("=" * 80)
    print("26 USC 1 TAXSIM VALIDATION REPORT - Income Tax Before Credits")
    print("=" * 80)
    print()
    print("NOTE: Using TAXSIM-35 with 2023 tax year (2024 not yet available in TAXSIM)")
    print()

    # Create validator
    try:
        validator = TaxsimValidator(mode="web")
        print("Using TAXSIM web API")
    except Exception as e:
        print(f"WARNING: Could not initialize TAXSIM validator: {e}")
        print("Falling back to manual calculation only")
        validator = None

    results = []
    matches = 0
    total = 0

    for test in test_cases:
        name = test['name']
        year = test['year']
        expected_taxable_income = test['expected_taxable_income']
        filing_status = test['filing_status']

        # Calculate expected tax from statute
        expected_tax = calc_2023_tax(expected_taxable_income, filing_status)

        print(f"Test: {name}")
        print(f"  Year: {year}")
        print(f"  Wages: ${test['inputs']['earned_income']:,.0f}")
        print(f"  Filing Status: {filing_status}")
        print(f"  Standard Deduction: ${test['std_deduction']:,.0f}")
        print(f"  Expected Taxable Income: ${expected_taxable_income:,.0f}")
        print(f"  Expected Tax (from statute): ${expected_tax:,.2f}")

        if validator:
            # Run TAXSIM
            test_case = TestCase(
                name=name,
                inputs=test['inputs'],
                expected={"tax_before_credits": expected_tax},
            )

            try:
                result = validator.validate(test_case, "tax_before_credits", year=year)

                if result.success:
                    taxsim_tax = result.calculated_value
                    diff = abs(taxsim_tax - expected_tax)
                    matches_within_1 = diff <= 1.0

                    if matches_within_1:
                        matches += 1
                    total += 1

                    status_icon = "✓" if matches_within_1 else "✗"
                    print(f"  TAXSIM Tax Before Credits: ${taxsim_tax:,.2f} {status_icon}")

                    if not matches_within_1:
                        print(f"    Difference: ${diff:,.2f}")

                    results.append({
                        "name": name,
                        "year": year,
                        "wages": test['inputs']['earned_income'],
                        "filing_status": filing_status,
                        "expected_taxable_income": expected_taxable_income,
                        "expected_tax": expected_tax,
                        "taxsim_tax": taxsim_tax,
                        "difference": diff,
                        "matches": matches_within_1,
                    })
                else:
                    print(f"  TAXSIM Error: {result.error}")
                    results.append({
                        "name": name,
                        "error": result.error,
                    })

            except Exception as e:
                print(f"  TAXSIM Error: {str(e)}")
                results.append({
                    "name": name,
                    "error": str(e),
                })
        else:
            print(f"  TAXSIM: Not available")

        print()

    # Summary
    if total > 0:
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)

        match_rate = (matches / total) * 100
        print(f"TAXSIM Match Rate: {matches}/{total} ({match_rate:.1f}%)")
        print(f"Match threshold: ±$1.00")

        print()
        print("=" * 80)
        print("DISCREPANCIES")
        print("=" * 80)

        discrepancies = [r for r in results if r.get('matches') is False]

        if discrepancies:
            for disc in discrepancies:
                print(f"\nCase: {disc['name']}")
                print(f"  Expected: ${disc['expected_tax']:,.2f}")
                print(f"  TAXSIM: ${disc['taxsim_tax']:,.2f}")
                print(f"  Difference: ${disc['difference']:,.2f}")
                print(f"  Possible reasons:")
                print(f"    - Rounding differences in standard deduction")
                print(f"    - Minor bracket calculation differences")
        else:
            print("\nNo discrepancies found! All tests match within $1.00")

        # Save results
        output_file = "validation_26_usc_1_taxsim_results.json"
        with open(output_file, "w") as f:
            json.dump({
                "timestamp": "2025-01-03",
                "section": "26 USC 1",
                "variable": "income_tax_before_credits",
                "validator": "TAXSIM-35",
                "total_tests": total,
                "matches": matches,
                "match_rate": match_rate / 100 if total > 0 else 0,
                "results": results,
            }, f, indent=2)

        print()
        print(f"Results saved to: {output_file}")
    else:
        print("No tests completed")


if __name__ == "__main__":
    run_validation()

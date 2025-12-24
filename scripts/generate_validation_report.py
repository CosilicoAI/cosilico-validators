#!/usr/bin/env python3
"""Generate detailed validation report for newly encoded variables."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cosilico_validators.encoding_orchestrator import encode_variable
from cosilico_validators.consensus.engine import ConsensusLevel
import json


def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(title.center(80))
    print("=" * 80)


def print_variable_detail(var_name, session):
    """Print detailed results for a variable."""
    result = session.validation_result
    print(f"\nVariable: {var_name}")
    print(f"Statute: {session.statute_ref}")
    print(f"Status: {result.status.value}")
    print(f"Match Rate: {result.match_rate:.1%}")
    print(f"Reward Signal: {result.reward_signal:+.2f}")
    print(f"Passed: {'✅' if result.passed else '❌'}")

    # Show test case results
    print(f"\nTest Cases ({len(session.test_cases)} total):")
    for i, (tc, consensus_result) in enumerate(
        zip(session.test_cases, result.consensus_results), 1
    ):
        status_icon = (
            "✅"
            if consensus_result.consensus_level == ConsensusLevel.FULL_AGREEMENT
            else "⚠️"
        )
        print(f"  {status_icon} {i}. {tc['name']}")
        print(f"      Expected: {tc['expected']}")
        if consensus_result.consensus_value is not None:
            print(f"      PE Value: ${consensus_result.consensus_value:.2f}")
        else:
            print(f"      PE Value: None")
        print(f"      Consensus: {consensus_result.consensus_level.value}")

    # Show any issues or upstream bugs
    if result.issues:
        print(f"\n⚠️  Issues ({len(result.issues)}):")
        for issue in result.issues:
            print(f"  - {issue}")

    if result.upstream_bugs:
        print(f"\n🐛 Potential Upstream Bugs ({len(result.upstream_bugs)}):")
        for bug in result.upstream_bugs:
            print(f"  - {bug}")


# Test case definitions (imported from encode_new_variables.py)
NIIT_TEST_CASES = [
    {
        "name": "NIIT - Below threshold, no tax",
        "inputs": {
            "employment_income": 150000,
            "interest_income": 5000,
            "dividend_income": 3000,
            "filing_status": "SINGLE",
        },
        "expected": {"net_investment_income_tax": 0},
        "citation": "26 USC § 1411(b) - below $200k threshold for single",
    },
    {
        "name": "NIIT - Above threshold, single filer",
        "inputs": {
            "employment_income": 180000,
            "interest_income": 25000,
            "dividend_income": 15000,
            "filing_status": "SINGLE",
        },
        "expected": {"net_investment_income_tax": None},
        "citation": "26 USC § 1411(a)(1) - 3.8% tax on NII for single filer over $200k",
    },
    {
        "name": "NIIT - Joint filers above threshold",
        "inputs": {
            "employment_income": 240000,
            "interest_income": 30000,
            "long_term_capital_gains": 20000,
            "filing_status": "JOINT",
        },
        "expected": {"net_investment_income_tax": None},
        "citation": "26 USC § 1411(b) - $250k threshold for joint filers",
    },
    {
        "name": "NIIT - Large capital gains",
        "inputs": {
            "employment_income": 150000,
            "long_term_capital_gains": 100000,
            "filing_status": "SINGLE",
        },
        "expected": {"net_investment_income_tax": None},
        "citation": "26 USC § 1411(c)(1)(A)(iii) - capital gains included in NII",
    },
    {
        "name": "NIIT - No investment income",
        "inputs": {
            "employment_income": 300000,
            "filing_status": "SINGLE",
        },
        "expected": {"net_investment_income_tax": 0},
        "citation": "26 USC § 1411 - no tax without NII",
    },
]

ADDITIONAL_MEDICARE_TAX_TEST_CASES = [
    {
        "name": "Additional Medicare Tax - Below threshold",
        "inputs": {
            "employment_income": 180000,
            "filing_status": "SINGLE",
        },
        "expected": {"additional_medicare_tax": 0},
        "citation": "26 USC § 3101(b)(2) - $200k threshold for single",
    },
    {
        "name": "Additional Medicare Tax - Single filer above threshold",
        "inputs": {
            "employment_income": 250000,
            "filing_status": "SINGLE",
        },
        "expected": {"additional_medicare_tax": None},
        "citation": "26 USC § 3101(b)(2) - 0.9% on wages over $200k",
    },
    {
        "name": "Additional Medicare Tax - Joint filers",
        "inputs": {
            "employment_income": 275000,
            "filing_status": "JOINT",
        },
        "expected": {"additional_medicare_tax": None},
        "citation": "26 USC § 3101(b)(2)(B)(i)(II) - $250k threshold for joint",
    },
    {
        "name": "Additional Medicare Tax - Self-employment income",
        "inputs": {
            "self_employment_income": 250000,
            "filing_status": "SINGLE",
        },
        "expected": {"additional_medicare_tax": None},
        "citation": "26 USC § 1401(b)(2) - applies to self-employment income",
    },
    {
        "name": "Additional Medicare Tax - Mixed income",
        "inputs": {
            "employment_income": 150000,
            "self_employment_income": 100000,
            "filing_status": "SINGLE",
        },
        "expected": {"additional_medicare_tax": None},
        "citation": "26 USC § 3101(b)(2) - combined wages and SE income",
    },
]

QBI_TEST_CASES = [
    {
        "name": "QBI - Simple case below threshold",
        "inputs": {
            "self_employment_income": 50000,
            "filing_status": "SINGLE",
        },
        "expected": {"qualified_business_income_deduction": None},
        "citation": "26 USC § 199A(a) - 20% deduction for QBI",
    },
    {
        "name": "QBI - Single filer below taxable income threshold",
        "inputs": {
            "self_employment_income": 100000,
            "employment_income": 50000,
            "filing_status": "SINGLE",
        },
        "expected": {"qualified_business_income_deduction": None},
        "citation": "26 USC § 199A(b)(2) - threshold $191,950 (2024)",
    },
    {
        "name": "QBI - Joint filers with substantial business income",
        "inputs": {
            "self_employment_income": 300000,
            "filing_status": "JOINT",
        },
        "expected": {"qualified_business_income_deduction": None},
        "citation": "26 USC § 199A(b)(3) - phase-out for specified service trades",
    },
    {
        "name": "QBI - Above threshold, limited by W-2/property",
        "inputs": {
            "self_employment_income": 250000,
            "filing_status": "SINGLE",
        },
        "expected": {"qualified_business_income_deduction": None},
        "citation": "26 USC § 199A(b)(2)(B) - W-2/property limitation",
    },
    {
        "name": "QBI - No qualified business income",
        "inputs": {
            "employment_income": 100000,
            "filing_status": "SINGLE",
        },
        "expected": {"qualified_business_income_deduction": 0},
        "citation": "26 USC § 199A - only applies to QBI",
    },
]

PREMIUM_TAX_CREDIT_TEST_CASES = [
    {
        "name": "PTC - Income at 150% FPL, single",
        "inputs": {
            "employment_income": 21870,
            "filing_status": "SINGLE",
            "age": 40,
        },
        "expected": {"premium_tax_credit": None},
        "citation": "26 USC § 36B(b)(3)(A)(i) - 3-4% premium cap at 150% FPL",
    },
    {
        "name": "PTC - Income at 250% FPL, family",
        "inputs": {
            "employment_income": 73240,
            "filing_status": "JOINT",
            "num_children": 2,
            "age": 35,
        },
        "expected": {"premium_tax_credit": None},
        "citation": "26 USC § 36B(b)(3)(A)(i) - 6-8.5% premium cap at 250% FPL",
    },
    {
        "name": "PTC - Income at 400% FPL",
        "inputs": {
            "employment_income": 58320,
            "filing_status": "SINGLE",
            "age": 55,
        },
        "expected": {"premium_tax_credit": None},
        "citation": "26 USC § 36B - ARP removed 400% FPL cliff",
    },
    {
        "name": "PTC - Too high income",
        "inputs": {
            "employment_income": 200000,
            "filing_status": "SINGLE",
            "age": 45,
        },
        "expected": {"premium_tax_credit": 0},
        "citation": "26 USC § 36B(c)(1)(A) - limited to those under income threshold",
    },
    {
        "name": "PTC - Below 100% FPL (Medicaid gap)",
        "inputs": {
            "employment_income": 10000,
            "filing_status": "SINGLE",
            "age": 30,
        },
        "expected": {"premium_tax_credit": 0},
        "citation": "26 USC § 36B(c)(1)(A) - minimum 100% FPL in non-expansion states",
    },
]


def main():
    """Generate detailed validation report."""
    print_section("DETAILED VALIDATION REPORT")
    print(f"Generated on: 2024-12-24")
    print(f"Framework: cosilico-validators v0.1.0")
    print(f"Validator: PolicyEngine US")

    # Encode each variable
    variables = [
        (
            "net_investment_income_tax",
            "26 USC § 1411",
            NIIT_TEST_CASES,
            "Net Investment Income Tax (NIIT)",
        ),
        (
            "additional_medicare_tax",
            "26 USC § 3101(b)(2)",
            ADDITIONAL_MEDICARE_TAX_TEST_CASES,
            "Additional Medicare Tax",
        ),
        (
            "qualified_business_income_deduction",
            "26 USC § 199A",
            QBI_TEST_CASES,
            "Qualified Business Income Deduction (QBI)",
        ),
        (
            "premium_tax_credit",
            "26 USC § 36B",
            PREMIUM_TAX_CREDIT_TEST_CASES,
            "Premium Tax Credit (PTC)",
        ),
    ]

    results = {}
    for var_name, statute_ref, test_cases, display_name in variables:
        print_section(display_name)
        session = encode_variable(
            variable=var_name,
            statute_ref=statute_ref,
            test_cases=test_cases,
            plugin_version="v0.2.0",
            year=2024,
        )
        results[var_name] = session
        print_variable_detail(var_name, session)

    # Overall summary
    print_section("OVERALL SUMMARY")
    total = len(results)
    passed = sum(1 for s in results.values() if s.validation_result.passed)
    avg_match_rate = sum(
        s.validation_result.match_rate for s in results.values()
    ) / total
    avg_reward = sum(
        s.validation_result.reward_signal for s in results.values()
    ) / total

    print(f"\nVariables Validated: {total}")
    print(f"Passed: {passed} ({passed/total:.0%})")
    print(f"Failed: {total - passed}")
    print(f"Average Match Rate: {avg_match_rate:.1%}")
    print(f"Average Reward Signal: {avg_reward:+.2f}")

    if passed == total:
        print("\n✅ SUCCESS: All variables validated with 100% match rate!")
        print(
            "\nThese variables are ready for encoding in cosilico-us with full PolicyEngine compatibility."
        )
        return 0
    else:
        print("\n⚠️  WARNING: Some variables need attention")
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Encode new tax variables using cosilico-validators framework.

Variables to encode:
1. Net Investment Income Tax (NIIT) - 26 USC § 1411
2. Additional Medicare Tax - 26 USC § 3101(b)(2)
3. Qualified Business Income Deduction (QBI) - 26 USC § 199A
4. Premium Tax Credit (PTC) - 26 USC § 36B
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cosilico_validators.encoding_orchestrator import encode_variable


# ==============================================================================
# 1. NET INVESTMENT INCOME TAX (NIIT) - 26 USC § 1411
# ==============================================================================

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
        "expected": {
            "net_investment_income_tax": None
        },  # Let PE calculate: 3.8% of lesser of NII or excess MAGI
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
        "expected": {
            "net_investment_income_tax": None
        },  # Let PE calculate: threshold is $250k for joint
        "citation": "26 USC § 1411(b) - $250k threshold for joint filers",
    },
    {
        "name": "NIIT - Large capital gains",
        "inputs": {
            "employment_income": 150000,
            "long_term_capital_gains": 100000,
            "filing_status": "SINGLE",
        },
        "expected": {
            "net_investment_income_tax": None
        },  # Expect ~3.8% of capital gains above threshold
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


# ==============================================================================
# 2. ADDITIONAL MEDICARE TAX - 26 USC § 3101(b)(2)
# ==============================================================================

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
        "expected": {
            "additional_medicare_tax": None
        },  # 0.9% of $50k = $450
        "citation": "26 USC § 3101(b)(2) - 0.9% on wages over $200k",
    },
    {
        "name": "Additional Medicare Tax - Joint filers",
        "inputs": {
            "employment_income": 275000,
            "filing_status": "JOINT",
        },
        "expected": {
            "additional_medicare_tax": None
        },  # 0.9% of $25k = $225 (threshold $250k for joint)
        "citation": "26 USC § 3101(b)(2)(B)(i)(II) - $250k threshold for joint",
    },
    {
        "name": "Additional Medicare Tax - Self-employment income",
        "inputs": {
            "self_employment_income": 250000,
            "filing_status": "SINGLE",
        },
        "expected": {
            "additional_medicare_tax": None
        },  # Also applies to SE income
        "citation": "26 USC § 1401(b)(2) - applies to self-employment income",
    },
    {
        "name": "Additional Medicare Tax - Mixed income",
        "inputs": {
            "employment_income": 150000,
            "self_employment_income": 100000,
            "filing_status": "SINGLE",
        },
        "expected": {
            "additional_medicare_tax": None
        },  # 0.9% on $50k over threshold
        "citation": "26 USC § 3101(b)(2) - combined wages and SE income",
    },
]


# ==============================================================================
# 3. QUALIFIED BUSINESS INCOME DEDUCTION (QBI) - 26 USC § 199A
# ==============================================================================

QBI_TEST_CASES = [
    {
        "name": "QBI - Simple case below threshold",
        "inputs": {
            "self_employment_income": 50000,
            "filing_status": "SINGLE",
        },
        "expected": {
            "qualified_business_income_deduction": None
        },  # 20% of $50k = $10k
        "citation": "26 USC § 199A(a) - 20% deduction for QBI",
    },
    {
        "name": "QBI - Single filer below taxable income threshold",
        "inputs": {
            "self_employment_income": 100000,
            "employment_income": 50000,
            "filing_status": "SINGLE",
        },
        "expected": {
            "qualified_business_income_deduction": None
        },  # 20% of QBI, capped by taxable income
        "citation": "26 USC § 199A(b)(2) - threshold $191,950 (2024)",
    },
    {
        "name": "QBI - Joint filers with substantial business income",
        "inputs": {
            "self_employment_income": 300000,
            "filing_status": "JOINT",
        },
        "expected": {
            "qualified_business_income_deduction": None
        },  # Let PE calculate with phase-out rules
        "citation": "26 USC § 199A(b)(3) - phase-out for specified service trades",
    },
    {
        "name": "QBI - Above threshold, limited by W-2/property",
        "inputs": {
            "self_employment_income": 250000,
            "filing_status": "SINGLE",
        },
        "expected": {
            "qualified_business_income_deduction": None
        },  # Limited by W-2 wages/property
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


# ==============================================================================
# 4. PREMIUM TAX CREDIT (PTC) - 26 USC § 36B
# ==============================================================================

PREMIUM_TAX_CREDIT_TEST_CASES = [
    {
        "name": "PTC - Income at 150% FPL, single",
        "inputs": {
            "employment_income": 21870,  # ~150% FPL 2024
            "filing_status": "SINGLE",
            "age": 40,
        },
        "expected": {
            "premium_tax_credit": None
        },  # Should get substantial credit
        "citation": "26 USC § 36B(b)(3)(A)(i) - 3-4% premium cap at 150% FPL",
    },
    {
        "name": "PTC - Income at 250% FPL, family",
        "inputs": {
            "employment_income": 73240,  # ~250% FPL for family of 4
            "filing_status": "JOINT",
            "num_children": 2,
            "age": 35,
        },
        "expected": {
            "premium_tax_credit": None
        },  # Let PE calculate with benchmark plan
        "citation": "26 USC § 36B(b)(3)(A)(i) - 6-8.5% premium cap at 250% FPL",
    },
    {
        "name": "PTC - Income at 400% FPL",
        "inputs": {
            "employment_income": 58320,  # ~400% FPL single
            "filing_status": "SINGLE",
            "age": 55,
        },
        "expected": {
            "premium_tax_credit": None
        },  # Credit phases out after ARP/IRA changes
        "citation": "26 USC § 36B - ARP removed 400% FPL cliff",
    },
    {
        "name": "PTC - Too high income",
        "inputs": {
            "employment_income": 200000,
            "filing_status": "SINGLE",
            "age": 45,
        },
        "expected": {
            "premium_tax_credit": 0
        },  # No credit at very high income
        "citation": "26 USC § 36B(c)(1)(A) - limited to those under income threshold",
    },
    {
        "name": "PTC - Below 100% FPL (Medicaid gap)",
        "inputs": {
            "employment_income": 10000,
            "filing_status": "SINGLE",
            "age": 30,
        },
        "expected": {
            "premium_tax_credit": 0
        },  # Below 100% FPL - no credit
        "citation": "26 USC § 36B(c)(1)(A) - minimum 100% FPL in non-expansion states",
    },
]


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================


def main():
    """Run encoding validation for all new variables."""
    print("=" * 80)
    print("ENCODING NEW TAX VARIABLES")
    print("=" * 80)

    results = {}

    # 1. Net Investment Income Tax
    print("\n\n" + "=" * 80)
    print("1. NET INVESTMENT INCOME TAX (NIIT)")
    print("=" * 80)
    results["niit"] = encode_variable(
        variable="net_investment_income_tax",
        statute_ref="26 USC § 1411",
        test_cases=NIIT_TEST_CASES,
        plugin_version="v0.2.0",
        year=2024,
    )

    # 2. Additional Medicare Tax
    print("\n\n" + "=" * 80)
    print("2. ADDITIONAL MEDICARE TAX")
    print("=" * 80)
    results["medicare"] = encode_variable(
        variable="additional_medicare_tax",
        statute_ref="26 USC § 3101(b)(2)",
        test_cases=ADDITIONAL_MEDICARE_TAX_TEST_CASES,
        plugin_version="v0.2.0",
        year=2024,
    )

    # 3. Qualified Business Income Deduction
    print("\n\n" + "=" * 80)
    print("3. QUALIFIED BUSINESS INCOME DEDUCTION (QBI)")
    print("=" * 80)
    results["qbi"] = encode_variable(
        variable="qualified_business_income_deduction",
        statute_ref="26 USC § 199A",
        test_cases=QBI_TEST_CASES,
        plugin_version="v0.2.0",
        year=2024,
    )

    # 4. Premium Tax Credit (note: this may have limited PE support)
    print("\n\n" + "=" * 80)
    print("4. PREMIUM TAX CREDIT (PTC)")
    print("=" * 80)
    results["ptc"] = encode_variable(
        variable="premium_tax_credit",
        statute_ref="26 USC § 36B",
        test_cases=PREMIUM_TAX_CREDIT_TEST_CASES,
        plugin_version="v0.2.0",
        year=2024,
    )

    # Summary
    print("\n\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    for var_name, session in results.items():
        status_icon = "✅" if session.validation_result.passed else "❌"
        print(
            f"{status_icon} {var_name.upper()}: "
            f"{session.validation_result.match_rate:.1%} match rate, "
            f"reward={session.validation_result.reward_signal:+.2f}"
        )
        if session.diagnosis:
            print(
                f"   └─ Diagnosis: {session.diagnosis.layer.value} "
                f"({session.diagnosis.confidence:.0%} confidence)"
            )

    # Count successes
    passed = sum(1 for s in results.values() if s.validation_result.passed)
    total = len(results)

    print(f"\nOverall: {passed}/{total} variables passed validation")

    if passed == total:
        print("\n🎉 All variables validated successfully!")
        return 0
    else:
        print("\n⚠️  Some variables need attention")
        return 1


if __name__ == "__main__":
    sys.exit(main())

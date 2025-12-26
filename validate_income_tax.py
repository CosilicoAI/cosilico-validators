"""
Validate Income Tax Brackets (26 USC Section 1) encoding against PolicyEngine.

Compares the Cosilico encoding to PolicyEngine US calculations for
ordinary income tax before credits.
"""
import numpy as np
from policyengine_us import Simulation

# 2024 Tax Bracket Thresholds (from Rev. Proc. 2023-34)
RATES = np.array([0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37])

# Thresholds by filing status
THRESHOLDS = {
    "single": np.array([0, 11600, 47150, 100525, 191950, 243725, 609350]),
    "married_filing_jointly": np.array([0, 23200, 94300, 201050, 383900, 487450, 731200]),
    "head_of_household": np.array([0, 16550, 63100, 100500, 191950, 243700, 609350]),
    "married_filing_separately": np.array([0, 11600, 47150, 100525, 191950, 243725, 365600]),
    "surviving_spouse": np.array([0, 23200, 94300, 201050, 383900, 487450, 731200]),
}


def cosilico_income_tax(taxable_income: np.ndarray, filing_status: str) -> np.ndarray:
    """
    Compute federal income tax using Cosilico encoding logic from 26 USC Section 1.

    This implements the progressive marginal rate structure.
    """
    thresholds = THRESHOLDS[filing_status]

    # Add infinity as top ceiling
    thresholds_with_inf = np.append(thresholds, np.inf)

    # Initialize tax array
    if isinstance(taxable_income, (int, float)):
        taxable_income = np.array([taxable_income])

    n = len(taxable_income)
    tax = np.zeros(n)

    # Apply each bracket
    for i, rate in enumerate(RATES):
        floor = thresholds_with_inf[i]
        ceiling = thresholds_with_inf[i + 1]

        # Income in this bracket = min(income, ceiling) - floor, clamped at 0
        income_in_bracket = np.maximum(
            np.minimum(taxable_income, ceiling) - floor,
            0
        )
        tax += income_in_bracket * rate

    return tax


def policyengine_income_tax(
    taxable_income: float,
    filing_status: str,
    tax_year: int = 2024,
) -> float:
    """Calculate federal income tax before credits using PolicyEngine-US."""
    is_married = filing_status in ("married_filing_jointly", "married_filing_separately")
    is_hoh = filing_status == "head_of_household"
    is_surviving = filing_status == "surviving_spouse"

    situation = {
        "people": {
            "adult": {
                "age": {tax_year: 40},
                # Use employment income as taxable income proxy
                "employment_income": {tax_year: taxable_income},
            }
        },
        "tax_units": {
            "tax_unit": {
                "members": ["adult"],
            }
        },
        "spm_units": {
            "spm_unit": {
                "members": ["adult"],
            }
        },
        "households": {
            "household": {
                "members": ["adult"],
                "state_code": {tax_year: "TX"},  # No state income tax
            }
        },
    }

    # Add spouse if married or surviving spouse
    if is_married or is_surviving:
        situation["people"]["spouse"] = {
            "age": {tax_year: 40},
            "employment_income": {tax_year: 0},
        }
        situation["tax_units"]["tax_unit"]["members"].append("spouse")
        situation["spm_units"]["spm_unit"]["members"].append("spouse")
        situation["households"]["household"]["members"].append("spouse")

    # Add child if HoH or surviving spouse
    if is_hoh or is_surviving:
        situation["people"]["child"] = {
            "age": {tax_year: 10},
            "employment_income": {tax_year: 0},
        }
        situation["tax_units"]["tax_unit"]["members"].append("child")
        situation["spm_units"]["spm_unit"]["members"].append("child")
        situation["households"]["household"]["members"].append("child")

    sim = Simulation(situation=situation)

    # Get income tax before credits
    result = sim.calculate("income_tax_before_credits", tax_year)
    return float(result.sum())


def run_validation():
    """Run validation tests comparing Cosilico to PolicyEngine."""
    print("=" * 70)
    print("Income Tax Brackets (26 USC Section 1) Validation")
    print("=" * 70)

    # Test cases: (filing_status, taxable_income, description)
    test_cases = [
        # Single filer tests
        ("single", 10000, "Single - 10% bracket"),
        ("single", 11600, "Single - at 10%/12% boundary"),
        ("single", 25000, "Single - 10%+12% brackets"),
        ("single", 47150, "Single - at 12%/22% boundary"),
        ("single", 75000, "Single - 22% bracket"),
        ("single", 100000, "Single - $100k income"),
        ("single", 150000, "Single - 24% bracket"),
        ("single", 200000, "Single - 32% bracket"),
        ("single", 300000, "Single - 35% bracket"),
        ("single", 700000, "Single - 37% bracket"),

        # Joint filer tests
        ("married_filing_jointly", 20000, "Joint - 10% bracket"),
        ("married_filing_jointly", 23200, "Joint - at 10%/12% boundary"),
        ("married_filing_jointly", 100000, "Joint - $100k"),
        ("married_filing_jointly", 200000, "Joint - $200k"),
        ("married_filing_jointly", 400000, "Joint - 32% bracket"),
        ("married_filing_jointly", 800000, "Joint - 37% bracket"),

        # Head of Household tests
        ("head_of_household", 50000, "HoH - $50k"),
        ("head_of_household", 100000, "HoH - $100k"),

        # Married Filing Separately tests
        ("married_filing_separately", 50000, "MFS - $50k"),
        ("married_filing_separately", 400000, "MFS - $400k (37% bracket)"),

        # Edge cases
        ("single", 0, "Zero income"),
        ("single", 100, "Very small income"),
        ("single", 609350, "Single - exactly at 37% threshold"),
        ("single", 1000000, "Single - $1M income"),
    ]

    passed = 0
    failed = 0
    results = []

    print("\nRunning test cases...\n")

    for filing_status, income, description in test_cases:
        # Calculate using Cosilico encoding
        cosilico_tax = cosilico_income_tax(income, filing_status)[0]

        # Calculate using PolicyEngine
        try:
            pe_tax = policyengine_income_tax(income, filing_status)
        except Exception as e:
            pe_tax = None
            print(f"  PolicyEngine error for {description}: {e}")

        # Compare results
        if pe_tax is not None:
            diff = abs(cosilico_tax - pe_tax)
            pct_diff = (diff / max(cosilico_tax, 1)) * 100 if cosilico_tax > 0 else 0

            # Allow $1 tolerance (rounding differences)
            if diff <= 1.0:
                status = "PASS"
                passed += 1
            else:
                status = "FAIL"
                failed += 1

            results.append({
                "description": description,
                "filing_status": filing_status,
                "income": income,
                "cosilico": cosilico_tax,
                "policyengine": pe_tax,
                "diff": diff,
                "pct_diff": pct_diff,
                "status": status,
            })

            status_marker = "[PASS]" if status == "PASS" else "[FAIL]"
            print(f"{status_marker} {description}")
            print(f"        Income: ${income:,.0f} | Cosilico: ${cosilico_tax:,.2f} | PE: ${pe_tax:,.2f} | Diff: ${diff:.2f}")
        else:
            print(f"[SKIP] {description} - PolicyEngine calculation failed")

    # Summary
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total:  {passed + failed}")

    if failed > 0:
        print("\nFailed tests:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"  - {r['description']}: Cosilico=${r['cosilico']:.2f}, PE=${r['policyengine']:.2f}, Diff=${r['diff']:.2f}")

    # Detail comparison for specific cases
    print("\n" + "=" * 70)
    print("DETAILED BRACKET ANALYSIS (Single Filer)")
    print("=" * 70)

    single_thresholds = THRESHOLDS["single"]
    print("\n2024 Single Filer Brackets:")
    for i, rate in enumerate(RATES):
        floor = single_thresholds[i]
        ceiling = single_thresholds[i+1] if i+1 < len(single_thresholds) else float('inf')
        print(f"  {int(rate*100):2d}%: ${floor:>10,.0f} - ${ceiling:>10,.0f}" if ceiling != float('inf') else f"  {int(rate*100):2d}%: ${floor:>10,.0f} - unlimited")

    return passed, failed


if __name__ == "__main__":
    run_validation()

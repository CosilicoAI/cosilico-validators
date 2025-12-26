#!/usr/bin/env python3
"""Check current status of cosilico-us encodings without complex imports."""

from pathlib import Path

# Variable mappings from cosilico.py
VARIABLE_MAPPING = {
    "eitc": {
        "file": "statute/26/32/eitc_validation.cosilico",
        "variable": "earned_income_credit",
    },
    "ctc": {
        "file": "statute/26/24/child_tax_credit.cosilico",
        "variable": "child_tax_credit",
    },
    "agi": {
        "file": "statute/26/62/a/adjusted_gross_income.cosilico",
        "variable": "adjusted_gross_income",
    },
    "adjusted_gross_income": {
        "file": "statute/26/62/a/adjusted_gross_income.cosilico",
        "variable": "adjusted_gross_income",
    },
    "standard_deduction": {
        "file": "statute/26/63/standard_deduction.cosilico",
        "variable": "standard_deduction",
    },
    "net_investment_income_tax": {
        "file": "statute/26/1411/net_investment_income_tax.cosilico",
        "variable": "net_investment_income_tax",
    },
    "niit": {
        "file": "statute/26/1411/net_investment_income_tax.cosilico",
        "variable": "net_investment_income_tax",
    },
    "additional_medicare_tax": {
        "file": "statute/26/3101/b/2/additional_medicare_tax.cosilico",
        "variable": "additional_medicare_tax",
    },
    "self_employment_tax": {
        "file": "statute/26/1401/self_employment_tax.cosilico",
        "variable": "self_employment_tax",
    },
    "capital_gains_tax": {
        "file": "statute/26/1/h/capital_gains_tax.cosilico",
        "variable": "capital_gains_tax",
    },
    "qualified_business_income_deduction": {
        "file": "statute/26/199A/qbi_deduction.cosilico",
        "variable": "qualified_business_income_deduction",
    },
    "qbi_deduction": {
        "file": "statute/26/199A/qbi_deduction.cosilico",
        "variable": "qualified_business_income_deduction",
    },
    "premium_tax_credit": {
        "file": "statute/26/36B/premium_tax_credit.cosilico",
        "variable": "premium_tax_credit",
    },
    "taxable_social_security": {
        "file": "statute/26/86/taxable_social_security.cosilico",
        "variable": "taxable_social_security",
    },
    "snap": {
        "file": "statute/7/2017/a/allotment.cosilico",
        "variable": "snap_allotment",
    },
}

def check_file_exists(cosilico_us_path: Path, file_path: str) -> tuple[bool, str]:
    """Check if a cosilico file exists and return status."""
    full_path = cosilico_us_path / file_path
    if full_path.exists():
        with open(full_path) as f:
            lines = len(f.readlines())
        return True, f"✅ {lines:3d} lines"
    return False, "❌ Missing"

def main():
    cosilico_us = Path.home() / "CosilicoAI/cosilico-us"

    print("=" * 80)
    print("COSILICO-US POLICY ENCODING STATUS")
    print("=" * 80)
    print()

    print(f"cosilico-us path: {cosilico_us}")
    total_files = len(list(cosilico_us.glob('**/*.cosilico')))
    print(f"Total .cosilico files in repo: {total_files}")
    print()

    # Group variables by category
    categories = {
        "Tax Credits": ["eitc", "ctc"],
        "Income Measures": ["agi"],
        "Deductions": ["standard_deduction", "qbi_deduction"],
        "Additional Taxes": [
            "niit",
            "additional_medicare_tax",
            "self_employment_tax",
            "capital_gains_tax",
        ],
        "Other Tax": [
            "premium_tax_credit",
            "taxable_social_security",
        ],
        "Benefits": ["snap"],
    }

    # Track stats
    total_checked = 0
    total_exists = 0
    unique_files = set()

    # Check each category
    for category, variables in categories.items():
        print(f"\n{category}")
        print("-" * 80)

        seen_files = set()
        for var in variables:
            if var not in VARIABLE_MAPPING:
                print(f"  {var:35s} ⚠️  Not in mapping")
                continue

            mapping = VARIABLE_MAPPING[var]
            file_path = mapping["file"]
            cosilico_var = mapping["variable"]

            # Skip duplicates
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            unique_files.add(file_path)

            exists, status = check_file_exists(cosilico_us, file_path)
            if exists:
                total_exists += 1
            total_checked += 1

            # Extract statute reference from path
            parts = file_path.split("/")
            if parts[0] == "statute":
                if parts[1] == "26":  # IRC
                    statute_ref = f"26 USC § {'/'.join(parts[2:-1])}"
                elif parts[1] == "7":  # SNAP
                    statute_ref = f"7 USC § {'/'.join(parts[2:-1])}"
                else:
                    statute_ref = "/".join(parts[1:-1])
            else:
                statute_ref = "Unknown"

            print(f"  {var:35s} {status:15s} {statute_ref}")

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print(f"Unique statute files checked: {total_checked}")
    print(f"Files implemented: {total_exists}/{total_checked}")
    print(f"Completion rate: {total_exists/total_checked*100:.1f}%")
    print()

    # List missing files
    missing = [
        f for f in unique_files
        if not (cosilico_us / f).exists()
    ]

    if missing:
        print("Missing Implementations:")
        print("-" * 80)
        for f in sorted(missing):
            var_names = [
                k for k, v in VARIABLE_MAPPING.items()
                if v["file"] == f
            ]
            print(f"  ❌ {f}")
            print(f"     Variables: {', '.join(sorted(set(var_names)))}")
        print()

    print()
    print("=" * 80)
    print("TOP 3 RECOMMENDED POLICIES TO ENCODE NEXT")
    print("=" * 80)
    print()

    recommendations = [
        {
            "rank": 1,
            "name": "Self-Employment Tax",
            "statute": "26 USC § 1401",
            "file": "statute/26/1401/self_employment_tax.cosilico",
            "complexity": "Low-Medium",
            "importance": "High",
            "impact": "16M+ self-employed individuals",
            "rationale": [
                "Already have net_earnings_self_employment encoded",
                "Straightforward: 15.3% rate (12.4% SS + 2.9% Medicare)",
                "SS portion capped at wage base ($168,600 in 2024)",
                "Widely used, well-documented formula",
            ],
            "dependencies": ["26 USC § 1402(a) - Net earnings (✅ exists)"],
        },
        {
            "rank": 2,
            "name": "Taxable Social Security Benefits",
            "statute": "26 USC § 86",
            "file": "statute/26/86/taxable_social_security.cosilico",
            "complexity": "Medium",
            "importance": "High",
            "impact": "40M+ Social Security recipients",
            "rationale": [
                "Clear statutory formula: up to 85% of benefits taxable",
                "Based on 'provisional income' (AGI + tax-exempt interest + 50% SS)",
                "Two-tier threshold system",
                "No complex phase-outs or edge cases",
            ],
            "dependencies": ["AGI (✅ exists)", "Social Security benefits (input)"],
        },
        {
            "rank": 3,
            "name": "Ordinary Income Tax (Progressive Brackets)",
            "statute": "26 USC § 1(a)-(d)",
            "file": "statute/26/1/ordinary_income_tax.cosilico",
            "complexity": "Medium",
            "importance": "Critical",
            "impact": "All taxpayers - largest revenue source",
            "rationale": [
                "Core tax calculation with 7 brackets (10%, 12%, 22%, 24%, 32%, 35%, 37%)",
                "Need for complete tax liability calculation",
                "Required before implementing capital gains preferential rates",
                "Well-established, inflation-adjusted parameters",
            ],
            "dependencies": [
                "Taxable income (AGI - deductions - exemptions)",
                "Filing status (✅ exists)",
            ],
        },
    ]

    for rec in recommendations:
        print(f"{rec['rank']}. {rec['name']}")
        print(f"   Statute: {rec['statute']}")
        print(f"   File: {rec['file']}")
        print(f"   Complexity: {rec['complexity']} | Importance: {rec['importance']}")
        print(f"   Impact: {rec['impact']}")
        print(f"   Rationale:")
        for reason in rec["rationale"]:
            print(f"     • {reason}")
        print(f"   Dependencies:")
        for dep in rec["dependencies"]:
            print(f"     • {dep}")
        print()

    print()
    print("=" * 80)
    print("VALIDATION READINESS")
    print("=" * 80)
    print()

    print("Variables ready for validation (implemented):")
    ready = [
        var for var in unique_files
        if (cosilico_us / var).exists()
    ]
    for f in sorted(ready)[:5]:
        var_names = [k for k, v in VARIABLE_MAPPING.items() if v["file"] == f]
        print(f"  ✅ {var_names[0]:30s} → {f}")

    print(f"\n... and {len(ready)-5} more" if len(ready) > 5 else "")
    print()

if __name__ == "__main__":
    main()

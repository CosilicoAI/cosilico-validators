#!/usr/bin/env python3
"""Check current status of cosilico-us encodings and validation readiness."""

import sys
from pathlib import Path

# Add paths
validators_root = Path(__file__).parent
sys.path.insert(0, str(validators_root / "src"))
sys.path.insert(0, str(Path.home() / "CosilicoAI/cosilico-engine/src"))

from cosilico_validators.microdata.cosilico import VARIABLE_MAPPING

def check_file_exists(cosilico_us_path: Path, file_path: str) -> tuple[bool, str]:
    """Check if a cosilico file exists and return status."""
    full_path = cosilico_us_path / file_path
    if full_path.exists():
        with open(full_path) as f:
            lines = len(f.readlines())
        return True, f"✅ {lines} lines"
    return False, "❌ Missing"

def main():
    cosilico_us = Path.home() / "CosilicoAI/cosilico-us"

    print("=" * 80)
    print("COSILICO-US POLICY ENCODING STATUS")
    print("=" * 80)
    print()

    print(f"cosilico-us path: {cosilico_us}")
    print(f"Total .cosilico files: {len(list(cosilico_us.glob('**/*.cosilico')))}")
    print()

    # Group variables by category
    categories = {
        "Tax Credits": ["eitc", "ctc"],
        "Income Measures": ["agi", "adjusted_gross_income"],
        "Deductions": ["standard_deduction", "qbi_deduction", "qualified_business_income_deduction"],
        "Additional Taxes": [
            "net_investment_income_tax", "niit",
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

    # Check each category
    for category, variables in categories.items():
        print(f"\n{category}")
        print("-" * 80)

        seen_files = set()
        for var in variables:
            if var not in VARIABLE_MAPPING:
                continue

            mapping = VARIABLE_MAPPING[var]
            file_path = mapping["file"]
            cosilico_var = mapping["variable"]

            # Skip duplicates (e.g., agi and adjusted_gross_income point to same file)
            if file_path in seen_files:
                continue
            seen_files.add(file_path)

            exists, status = check_file_exists(cosilico_us, file_path)

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

    total_vars = len(VARIABLE_MAPPING)
    # Count unique files
    unique_files = set(m["file"] for m in VARIABLE_MAPPING.values())
    existing_files = sum(
        1 for f in unique_files
        if (cosilico_us / f).exists()
    )

    print(f"Total variables mapped: {total_vars}")
    print(f"Unique statute files: {len(unique_files)}")
    print(f"Files implemented: {existing_files}/{len(unique_files)}")
    print(f"Completion rate: {existing_files/len(unique_files)*100:.1f}%")
    print()

    # List missing files
    missing = [
        f for f in unique_files
        if not (cosilico_us / f).exists()
    ]

    if missing:
        print("\nMissing Implementations:")
        for f in sorted(missing):
            var_names = [
                k for k, v in VARIABLE_MAPPING.items()
                if v["file"] == f
            ]
            print(f"  ❌ {f}")
            print(f"     Variables: {', '.join(var_names[:3])}")

    print()
    print("=" * 80)
    print("RECOMMENDATIONS FOR NEXT POLICIES TO ENCODE")
    print("=" * 80)
    print()

    recommendations = [
        {
            "name": "Self-Employment Tax",
            "statute": "26 USC § 1401",
            "file": "statute/26/1401/self_employment_tax.cosilico",
            "complexity": "Medium",
            "importance": "High - affects 16M+ self-employed individuals",
            "rationale": "Already have net_earnings_self_employment; just need to apply 15.3% rate with cap",
        },
        {
            "name": "Capital Gains Tax",
            "statute": "26 USC § 1(h)",
            "file": "statute/26/1/h/capital_gains_tax.cosilico",
            "complexity": "Medium-High",
            "importance": "High - major revenue source, complex preferential rates",
            "rationale": "Have capital_gains components; need to implement 0%/15%/20% brackets",
        },
        {
            "name": "Taxable Social Security",
            "statute": "26 USC § 86",
            "file": "statute/26/86/taxable_social_security.cosilico",
            "complexity": "Medium",
            "importance": "High - affects 40M+ Social Security recipients",
            "rationale": "Straightforward formula: up to 85% taxable based on provisional income",
        },
    ]

    for i, rec in enumerate(recommendations, 1):
        print(f"{i}. {rec['name']} ({rec['statute']})")
        print(f"   File: {rec['file']}")
        print(f"   Complexity: {rec['complexity']}")
        print(f"   Importance: {rec['importance']}")
        print(f"   Rationale: {rec['rationale']}")
        print()

if __name__ == "__main__":
    main()

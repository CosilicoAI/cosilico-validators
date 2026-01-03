"""
Validate 26 USC 1 (Income Tax Rates) against TAXSIM-35.

TAXSIM requires full tax return inputs, so we construct realistic scenarios
where taxable income can be computed and compared.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple


def find_taxsim_executable() -> Path:
    """Find TAXSIM-35 executable."""
    search_paths = [
        Path("/Users/maxghenis/CosilicoAI/rac-validators/resources/taxsim/taxsim35-osx.exe"),
        Path.cwd() / "resources" / "taxsim" / "taxsim35-osx.exe",
    ]

    for path in search_paths:
        if path.exists():
            return path

    raise FileNotFoundError("TAXSIM-35 executable not found")


def run_taxsim(records: List[Dict]) -> List[Dict]:
    """
    Run TAXSIM-35 locally.

    Input format: taxsimid year state mstat page sage depx age1 age2 age3
                  pwages swages psemp ssemp dividends intrec stcg ltcg
                  otherprop nonprop pensions gssi pui sui transfers
                  rentpaid proptax otheritem childcare mortgage
                  scorp pbusinc pprofinc sbusinc sprofinc idtl

    Output columns (idtl=2): taxsimid year state fiitax siitax fica frate srate
                            ficar v10 v11 v12 v13 v14 v15 v16 v17 v18 v19
                            v20 v21 v22 v23 v24 v25 v26 v27 v28 v29 v30 v31
                            v32 v33 v34 v35 v36 v37 v38 v39
    """
    taxsim_path = find_taxsim_executable()

    # Create input file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        input_file = f.name
        for record in records:
            # Build input line
            line_parts = [
                str(record.get('taxsimid', 1)),
                str(record.get('year', 2024)),
                str(record.get('state', 6)),  # CA
                str(record.get('mstat', 1)),  # 1=single, 2=joint, 3=HOH
                str(record.get('page', 40)),  # Primary age
                str(record.get('sage', 0)),   # Spouse age
                str(record.get('depx', 0)),   # Dependents
                str(record.get('age1', 0)),   # Age of dependent 1
                str(record.get('age2', 0)),   # Age of dependent 2
                str(record.get('age3', 0)),   # Age of dependent 3
                str(record.get('pwages', 0)),
                str(record.get('swages', 0)),
                str(record.get('psemp', 0)),  # Primary self-emp
                str(record.get('ssemp', 0)),  # Spouse self-emp
                str(record.get('dividends', 0)),
                str(record.get('intrec', 0)),  # Interest
                str(record.get('stcg', 0)),
                str(record.get('ltcg', 0)),
                str(record.get('otherprop', 0)),
                str(record.get('nonprop', 0)),
                str(record.get('pensions', 0)),
                str(record.get('gssi', 0)),  # Gross social security
                str(record.get('pui', 0)),
                str(record.get('sui', 0)),
                str(record.get('transfers', 0)),
                str(record.get('rentpaid', 0)),
                str(record.get('proptax', 0)),
                str(record.get('otheritem', 0)),
                str(record.get('childcare', 0)),
                str(record.get('mortgage', 0)),
                str(record.get('scorp', 0)),
                str(record.get('pbusinc', 0)),
                str(record.get('pprofinc', 0)),
                str(record.get('sbusinc', 0)),
                str(record.get('sprofinc', 0)),
                str(record.get('idtl', 2)),  # Full output
            ]
            f.write(' '.join(line_parts) + '\n')

    # Run TAXSIM
    try:
        result = subprocess.run(
            [str(taxsim_path)],
            stdin=open(input_file, 'r'),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            raise RuntimeError(f"TAXSIM error: {result.stderr}")

        # Parse output
        output_records = []
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.strip().split()
            if len(parts) >= 39:
                output_records.append({
                    'taxsimid': int(parts[0]),
                    'year': int(parts[1]),
                    'state': int(parts[2]),
                    'fiitax': float(parts[3]),  # Federal income tax
                    'siitax': float(parts[4]),  # State income tax
                    'fica': float(parts[5]),
                    'v10': float(parts[9]),   # Federal AGI
                    'v13': float(parts[12]),  # Standard deduction / zero bracket
                    'v18': float(parts[17]),  # Federal taxable income
                    'v19': float(parts[18]),  # Tax before credits
                    'v22': float(parts[21]),  # CTC
                    'v23': float(parts[22]),  # ACTC
                    'v24': float(parts[23]),  # CDCTC
                    'v25': float(parts[24]),  # EITC
                })

        return output_records

    finally:
        Path(input_file).unlink(missing_ok=True)


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

    # Test cases with full TAXSIM inputs
    # For simplicity, we use wages-only scenarios where:
    # AGI = wages
    # Taxable Income = AGI - standard deduction
    test_cases = [
        {
            "name": "Single filer, $50k wages (2024)",
            "year": 2024,
            "mstat": 1,  # Single
            "pwages": 50000,
            "page": 40,
            "filing_status": "SINGLE",
            "standard_deduction_2024": 14600,
            "expected_taxable_income": 50000 - 14600,
        },
        {
            "name": "Married filing jointly, $100k wages (2024)",
            "year": 2024,
            "mstat": 2,  # Joint
            "pwages": 100000,
            "page": 40,
            "sage": 38,
            "filing_status": "JOINT",
            "standard_deduction_2024": 29200,
            "expected_taxable_income": 100000 - 29200,
        },
        {
            "name": "Head of household, $75k wages (2024)",
            "year": 2024,
            "mstat": 3,  # HOH
            "pwages": 75000,
            "page": 40,
            "depx": 1,  # One dependent for HOH status
            "age1": 10,
            "filing_status": "HOH",
            "standard_deduction_2024": 21900,
            "expected_taxable_income": 75000 - 21900,
        },
        {
            "name": "Single filer, high income $250k (2024)",
            "year": 2024,
            "mstat": 1,
            "pwages": 250000,
            "page": 40,
            "filing_status": "SINGLE",
            "standard_deduction_2024": 14600,
            "expected_taxable_income": 250000 - 14600,
        },
        {
            "name": "Joint filers, boundary test $117.5k (2024)",
            "year": 2024,
            "mstat": 2,
            "pwages": 117500,
            "page": 40,
            "sage": 38,
            "filing_status": "JOINT",
            "standard_deduction_2024": 29200,
            "expected_taxable_income": 117500 - 29200,
        },
    ]

    print("=" * 80)
    print("26 USC 1 TAXSIM VALIDATION REPORT - Income Tax Before Credits")
    print("=" * 80)
    print()

    # Build TAXSIM input records
    taxsim_records = []
    for i, test in enumerate(test_cases):
        record = {
            'taxsimid': i + 1,
            'year': test['year'],
            'state': 6,  # California
            'mstat': test['mstat'],
            'page': test['page'],
            'sage': test.get('sage', 0),
            'depx': test.get('depx', 0),
            'age1': test.get('age1', 0),
            'pwages': test['pwages'],
            'idtl': 2,  # Full output
        }
        taxsim_records.append(record)

    # Run TAXSIM
    try:
        taxsim_results = run_taxsim(taxsim_records)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        print()
        print("TAXSIM-35 executable not found.")
        print("Download from: https://taxsim.nber.org/taxsim35/")
        print("Place at: /Users/maxghenis/CosilicoAI/rac-validators/resources/taxsim/taxsim35-osx.exe")
        return

    # Compare results
    results = []
    matches = 0
    total = 0

    for test, taxsim_result in zip(test_cases, taxsim_results):
        name = test['name']
        expected_taxable_income = test['expected_taxable_income']
        taxsim_taxable_income = taxsim_result['v18']

        # Calculate expected tax from statute
        expected_tax = calculate_expected_tax_2024(expected_taxable_income, test['filing_status'])

        # TAXSIM v19 is "tax before credits"
        taxsim_tax_before_credits = taxsim_result['v19']

        diff = abs(taxsim_tax_before_credits - expected_tax)
        matches_within_1 = diff <= 1.0

        if matches_within_1:
            matches += 1
        total += 1

        result = {
            "name": name,
            "wages": test['pwages'],
            "filing_status": test['filing_status'],
            "expected_taxable_income": expected_taxable_income,
            "taxsim_taxable_income": taxsim_taxable_income,
            "expected_tax": expected_tax,
            "taxsim_tax_before_credits": taxsim_tax_before_credits,
            "difference": diff,
            "matches": matches_within_1,
        }

        results.append(result)

        # Print
        print(f"Test: {name}")
        print(f"  Wages: ${test['pwages']:,.0f}")
        print(f"  Filing Status: {test['filing_status']}")
        print(f"  Expected Taxable Income: ${expected_taxable_income:,.0f}")
        print(f"  TAXSIM Taxable Income: ${taxsim_taxable_income:,.0f}")
        print(f"  Expected Tax (from statute): ${expected_tax:,.2f}")
        print(f"  TAXSIM Tax Before Credits: ${taxsim_tax_before_credits:,.2f}")

        status_icon = "✓" if matches_within_1 else "✗"
        print(f"  Match: {status_icon}")
        if not matches_within_1:
            print(f"  Difference: ${diff:,.2f}")
        print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    match_rate = (matches / total) * 100 if total > 0 else 0
    print(f"TAXSIM Match Rate: {matches}/{total} ({match_rate:.1f}%)")
    print(f"Match threshold: ±$1.00")

    print()
    print("=" * 80)
    print("DISCREPANCIES")
    print("=" * 80)

    discrepancies = [r for r in results if not r['matches']]

    if discrepancies:
        for disc in discrepancies:
            print(f"\nCase: {disc['name']}")
            print(f"  Expected: ${disc['expected_tax']:,.2f}")
            print(f"  TAXSIM: ${disc['taxsim_tax_before_credits']:,.2f}")
            print(f"  Difference: ${disc['difference']:,.2f}")
            print(f"  Possible reasons:")
            print(f"    - Rounding differences in standard deduction application")
            print(f"    - TAXSIM uses different indexed amounts")
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
            "match_rate": match_rate / 100,
            "results": results,
        }, f, indent=2)

    print()
    print(f"Results saved to: {output_file}")


if __name__ == "__main__":
    run_validation()

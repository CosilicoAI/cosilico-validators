#!/usr/bin/env python3
"""
Generate precomputed oracle values for PE and TAXSIM on CPS ASEC.

Usage:
    python generate_oracles.py --pe --years 2021,2022,2023,2024
    python generate_oracles.py --taxsim --years 2018,2019,2020,2021,2022,2023,2024
    python generate_oracles.py --all
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

import pandas as pd
from tqdm import tqdm

# Tax variables to compute
PE_VARIABLES = [
    # Income
    "adjusted_gross_income",
    "taxable_income",
    "employment_income",
    "self_employment_income",
    # Deductions
    "standard_deduction",
    "itemized_taxable_income_deductions",
    # Credits
    "eitc",
    "ctc",
    "refundable_ctc",
    "non_refundable_ctc",
    "cdcc",  # Child and dependent care credit
    # Taxes
    "income_tax",
    "income_tax_before_credits",
    "payroll_tax",
    "employee_social_security_tax",
    "employee_medicare_tax",
    # Other
    "is_tax_unit_head",
    "is_tax_unit_spouse",
    "mars",  # Filing status
]

# TAXSIM output variables
TAXSIM_VARIABLES = [
    "fiitax",  # Federal income tax
    "siitax",  # State income tax
    "tfica",   # FICA (Social Security + Medicare)
    "v10",     # State bracket rate
    "v11",     # Federal bracket rate
    "v12",     # State AGI
    "v18",     # EITC
    "v25",     # Child tax credit
]


def generate_pe_oracle(years: list[int], output_dir: Path) -> None:
    """Generate PolicyEngine oracle for given years."""
    from policyengine_us import Microsimulation

    print(f"Generating PE oracle for years: {years}")

    all_data = []

    for year in tqdm(years, desc="PE years"):
        sim = Microsimulation()

        # Get tax unit IDs and person IDs
        tax_unit_ids = sim.calculate("tax_unit_id", year)
        person_ids = sim.calculate("person_id", year)
        household_ids = sim.calculate("household_id", year)

        # Compute each variable
        row = {
            "year": year,
            "tax_unit_id": tax_unit_ids,
            "person_id": person_ids,
            "household_id": household_ids,
        }

        for var in tqdm(PE_VARIABLES, desc=f"  Variables ({year})", leave=False):
            try:
                values = sim.calculate(var, year)
                row[var] = values
            except Exception as e:
                print(f"  Warning: {var} failed for {year}: {e}")
                row[var] = None

        # Create DataFrame for this year
        df = pd.DataFrame(row)
        all_data.append(df)

    # Combine all years
    result = pd.concat(all_data, ignore_index=True)

    # Save
    output_path = output_dir / "pe_cps_oracle.parquet"
    result.to_parquet(output_path, index=False)
    print(f"Saved PE oracle: {output_path} ({len(result):,} rows)")

    # Summary stats
    print("\nPE Oracle Summary:")
    for var in PE_VARIABLES[:5]:
        if var in result.columns and result[var] is not None:
            print(f"  {var}: mean=${result[var].mean():,.0f}")


def generate_taxsim_oracle(years: list[int], output_dir: Path) -> None:
    """Generate TAXSIM oracle for given tax years using PE 2024 CPS population."""
    from policyengine_us import Microsimulation
    from io import StringIO

    print(f"Generating TAXSIM oracle for tax years: {years}")
    print("Note: Using PE 2024 CPS population for all years")

    # Path to TAXSIM executable
    taxsim_exe = output_dir / "taxsim35.exe"
    if not taxsim_exe.exists():
        raise FileNotFoundError(f"TAXSIM executable not found: {taxsim_exe}")

    # Load population from 2024 (only year with proper tax unit structure)
    import numpy as np
    sim = Microsimulation()
    pop_year = 2024

    # Get person-level data as numpy arrays (once, reused for all tax years)
    person_tax_unit = np.array(sim.calculate("person_tax_unit_id", pop_year))
    unique_tu = sorted(set(person_tax_unit))
    ages = np.array(sim.calculate("age", pop_year))
    is_head = np.array(sim.calculate("is_tax_unit_head", pop_year))
    is_spouse = np.array(sim.calculate("is_tax_unit_spouse", pop_year))
    is_dep = np.array(sim.calculate("is_tax_unit_dependent", pop_year))
    emp_income = np.array(sim.calculate("employment_income", pop_year))
    se_income = np.array(sim.calculate("self_employment_income", pop_year))

    print(f"  Population: {len(unique_tu):,} tax units from {pop_year} CPS")

    all_data = []

    for tax_year in tqdm(years, desc="TAXSIM tax years"):

        # TAXSIM only supports up to 2023
        if tax_year > 2023:
            print(f"  Skipping {tax_year} (TAXSIM only supports up to 2023)")
            continue

        # Build tax unit level aggregates
        tu_data = []
        for tu_id in tqdm(unique_tu, desc=f"  Tax units ({tax_year})", leave=False):
            mask = person_tax_unit == tu_id
            tu_ages = ages[mask]
            tu_is_head = is_head[mask]
            tu_is_spouse = is_spouse[mask]
            tu_is_dep = is_dep[mask]
            tu_emp = emp_income[mask]
            tu_se = se_income[mask]

            # Primary filer
            head_idx = tu_is_head.argmax() if tu_is_head.any() else 0
            page = int(tu_ages[head_idx]) if len(tu_ages) > 0 else 40

            # Spouse
            has_spouse = tu_is_spouse.any()
            if has_spouse:
                spouse_idx = tu_is_spouse.argmax()
                sage = int(tu_ages[spouse_idx])
                swages = float(tu_emp[spouse_idx] + tu_se[spouse_idx])
            else:
                sage = 0
                swages = 0

            # Dependents
            depx = int(tu_is_dep.sum())

            # Primary wages
            pwages = float(tu_emp[head_idx] + tu_se[head_idx]) if len(tu_emp) > 0 else 0

            # Filing status: 1=single, 2=married filing jointly
            mstat = 2 if has_spouse else 1

            tu_data.append({
                "taxsimid": tu_id,
                "year": tax_year,
                "state": 0,  # Federal only
                "mstat": mstat,
                "page": max(1, min(page, 120)),
                "sage": max(0, min(sage, 120)),
                "depx": min(depx, 20),
                "pwages": max(0, pwages),
                "swages": max(0, swages),
            })

        taxsim_input = pd.DataFrame(tu_data)

        # Write CSV for TAXSIM
        csv_input = taxsim_input.to_csv(index=False)

        try:
            # Run TAXSIM
            result = subprocess.run(
                [str(taxsim_exe)],
                input=csv_input,
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode != 0:
                print(f"  TAXSIM error for {tax_year}: {result.stderr[:200]}")
                continue

            # Parse TAXSIM output
            output_df = pd.read_csv(StringIO(result.stdout))
            output_df["tax_year"] = tax_year
            output_df["pop_year"] = pop_year
            all_data.append(output_df)
            print(f"  {tax_year}: {len(output_df):,} tax units processed")

        except subprocess.TimeoutExpired:
            print(f"  TAXSIM timeout for {tax_year}")
        except Exception as e:
            print(f"  TAXSIM failed for {tax_year}: {e}")

    if all_data:
        result = pd.concat(all_data, ignore_index=True)
        output_path = output_dir / "taxsim_cps_oracle.parquet"
        result.to_parquet(output_path, index=False)
        print(f"Saved TAXSIM oracle: {output_path} ({len(result):,} rows)")
    else:
        print("No TAXSIM data generated")


def main():
    parser = argparse.ArgumentParser(description="Generate PE/TAXSIM oracles")
    parser.add_argument("--pe", action="store_true", help="Generate PE oracle")
    parser.add_argument("--taxsim", action="store_true", help="Generate TAXSIM oracle")
    parser.add_argument("--all", action="store_true", help="Generate both oracles")
    parser.add_argument(
        "--years",
        type=str,
        default="2021,2022,2023,2024",
        help="Comma-separated years",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Output directory",
    )

    args = parser.parse_args()
    years = [int(y) for y in args.years.split(",")]

    if args.all:
        args.pe = True
        args.taxsim = True

    if args.pe:
        generate_pe_oracle(years, args.output_dir)

    if args.taxsim:
        generate_taxsim_oracle(years, args.output_dir)


if __name__ == "__main__":
    main()

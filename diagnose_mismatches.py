"""Diagnose remaining mismatches between Cosilico and PolicyEngine."""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

# Add engine to path
sys.path.insert(0, str(Path.home() / "CosilicoAI/cosilico-engine/src"))

from policyengine_us import Microsimulation


def diagnose_niit():
    """Investigate NIIT mismatches."""
    print("=" * 80)
    print("NIIT Mismatch Diagnosis")
    print("=" * 80)

    sim = Microsimulation()
    year = 2024

    # Get PE values
    pe_niit = np.asarray(sim.calculate("net_investment_income_tax", year))
    pe_agi = np.asarray(sim.calculate("adjusted_gross_income", year))
    pe_nii = np.asarray(sim.calculate("net_investment_income", year))
    fs = np.asarray(sim.calculate("filing_status", year))

    # Get component incomes using CORRECT variables
    # Taxable interest (excludes tax-exempt muni bonds)
    taxable_interest_person = np.asarray(sim.calculate("taxable_interest_income", year))
    dividend_person = np.asarray(sim.calculate("dividend_income", year))
    rental_person = np.asarray(sim.calculate("rental_income", year))

    # Loss-limited capital gains is already at TaxUnit level
    loss_lim_cg = np.asarray(sim.calculate("loss_limited_net_capital_gains", year))

    # Get entity mappings for aggregation
    person_tu_id = np.asarray(sim.calculate("person_tax_unit_id", year))
    tu_id = np.asarray(sim.calculate("tax_unit_id", year))
    unique_tu = np.unique(tu_id)
    tu_id_to_idx = {int(tid): i for i, tid in enumerate(unique_tu)}

    # Aggregate person-level to tax unit
    n_tu = len(unique_tu)
    interest = np.zeros(n_tu)
    dividends = np.zeros(n_tu)
    rental = np.zeros(n_tu)

    for tu, int_inc, div_inc, rent_inc in zip(
        person_tu_id, taxable_interest_person, dividend_person, rental_person
    ):
        tu_idx = tu_id_to_idx[int(tu)]
        interest[tu_idx] += int_inc
        dividends[tu_idx] += div_inc
        rental[tu_idx] += rent_inc

    # Capital gains already at TU level
    ltcg = loss_lim_cg
    stcg = np.zeros(n_tu)  # Now included in loss_lim_cg

    # Filing status mapping
    fs_map = {
        "SINGLE": 0,
        "JOINT": 1,
        "SEPARATE": 2,
        "HEAD_OF_HOUSEHOLD": 3,
        "SURVIVING_SPOUSE": 4,
    }
    fs_names = {v: k for k, v in fs_map.items()}

    # Calculate what Cosilico would compute
    # Per §1411(b): JOINT/SURVIVING_SPOUSE=$250k, SEPARATE=$125k, all others=$200k
    threshold = np.where(
        (fs == "JOINT") | (fs == "SURVIVING_SPOUSE"), 250000,
        np.where(fs == "SEPARATE", 125000, 200000)
    )

    # Our NII calculation
    our_nii = np.maximum(0, interest + dividends + ltcg + stcg + rental)

    # Our NIIT calculation
    excess_magi = np.maximum(0, pe_agi - threshold)
    taxable_amount = np.minimum(our_nii, excess_magi)
    our_niit = 0.038 * taxable_amount

    # Find mismatches
    diff = np.abs(pe_niit - our_niit)
    mismatch_mask = diff > 1  # More than $1 difference

    n_total = len(pe_niit)
    n_mismatch = mismatch_mask.sum()

    print(f"\nTotal tax units: {n_total:,}")
    print(f"Mismatches (>$1 diff): {n_mismatch:,} ({100*n_mismatch/n_total:.1f}%)")

    if n_mismatch > 0:
        # Analyze mismatches
        mismatch_idx = np.where(mismatch_mask)[0]

        print(f"\nSample of mismatches (first 20):")
        print("-" * 100)
        print(f"{'Idx':>8} {'FS':>6} {'AGI':>12} {'PE_NII':>12} {'Our_NII':>12} {'PE_NIIT':>10} {'Our_NIIT':>10} {'Diff':>10}")
        print("-" * 100)

        for idx in mismatch_idx[:20]:
            print(f"{idx:>8} {fs[idx]:>6} {pe_agi[idx]:>12,.0f} {pe_nii[idx]:>12,.0f} {our_nii[idx]:>12,.0f} {pe_niit[idx]:>10,.0f} {our_niit[idx]:>10,.0f} {diff[idx]:>10,.0f}")

        # Analyze by filing status
        print("\n\nMismatches by filing status:")
        print("-" * 40)
        for fs_val in np.unique(fs):
            fs_mask = (fs == fs_val) & mismatch_mask
            if fs_mask.sum() > 0:
                print(f"  {fs_val}: {fs_mask.sum():,} mismatches")

        # Check if NII is the issue
        nii_diff = np.abs(pe_nii - our_nii)
        nii_mismatch = (nii_diff > 1) & mismatch_mask
        print(f"\n\nMismatches where NII differs: {nii_mismatch.sum():,}")

        # Check if it's threshold issue
        for idx in mismatch_idx[:5]:
            print(f"\nDetailed case {idx}:")
            print(f"  Filing status: {fs[idx]}")
            print(f"  AGI: ${pe_agi[idx]:,.0f}")
            print(f"  Threshold: ${threshold[idx]:,.0f}")
            print(f"  Excess MAGI: ${excess_magi[idx]:,.0f}")
            print(f"  PE NII: ${pe_nii[idx]:,.0f}")
            print(f"  Our NII: ${our_nii[idx]:,.0f} (int={interest[idx]:.0f} + div={dividends[idx]:.0f} + ltcg={ltcg[idx]:.0f} + stcg={stcg[idx]:.0f} + rent={rental[idx]:.0f})")
            print(f"  Taxable amount: ${taxable_amount[idx]:,.0f}")
            print(f"  PE NIIT: ${pe_niit[idx]:,.0f}")
            print(f"  Our NIIT: ${our_niit[idx]:,.0f}")


def diagnose_medicare_tax():
    """Investigate Additional Medicare Tax mismatches."""
    print("\n\n" + "=" * 80)
    print("Additional Medicare Tax Mismatch Diagnosis")
    print("=" * 80)

    sim = Microsimulation()
    year = 2024

    # Get PE values
    pe_amt = np.asarray(sim.calculate("additional_medicare_tax", year))
    pe_earned = np.asarray(sim.calculate("tax_unit_earned_income", year))

    # Get CORRECT employment income - IRS wages per §3121(a)
    irs_employment_person = np.asarray(sim.calculate("irs_employment_income", year))
    # Taxable SE income (net of deductions, includes S-corp)
    taxable_se_person = np.asarray(sim.calculate("taxable_self_employment_income", year))

    # Get entity mappings
    person_tu_id = np.asarray(sim.calculate("person_tax_unit_id", year))
    tu_id = np.asarray(sim.calculate("tax_unit_id", year))
    unique_tu = np.unique(tu_id)
    tu_id_to_idx = {int(tid): i for i, tid in enumerate(unique_tu)}

    n_tu = len(unique_tu)
    employment = np.zeros(n_tu)
    se = np.zeros(n_tu)

    for tu, emp, se_inc in zip(person_tu_id, irs_employment_person, taxable_se_person):
        tu_idx = tu_id_to_idx[int(tu)]
        employment[tu_idx] += emp
        se[tu_idx] += se_inc

    fs = np.asarray(sim.calculate("filing_status", year))

    # What we'd calculate (simple combined approach)
    # Per §3101(b)(2): JOINT=$250k, SEPARATE=$125k, all others=$200k
    threshold = np.where(
        fs == "JOINT", 250000,
        np.where(fs == "SEPARATE", 125000, 200000)
    )

    # Combined wages + SE
    medicare_wages = employment + se
    excess = np.maximum(0, medicare_wages - threshold)
    our_amt = 0.009 * excess

    # Find mismatches
    diff = np.abs(pe_amt - our_amt)
    mismatch_mask = diff > 1

    n_total = len(pe_amt)
    n_mismatch = mismatch_mask.sum()

    print(f"\nTotal tax units: {n_total:,}")
    print(f"Mismatches (>$1 diff): {n_mismatch:,} ({100*n_mismatch/n_total:.1f}%)")

    if n_mismatch > 0:
        mismatch_idx = np.where(mismatch_mask)[0]

        print(f"\nSample of mismatches (first 20):")
        print("-" * 110)
        print(f"{'Idx':>8} {'FS':>6} {'Employment':>12} {'SE':>12} {'Total':>12} {'PE_AMT':>10} {'Our_AMT':>10} {'Diff':>10}")
        print("-" * 110)

        for idx in mismatch_idx[:20]:
            total = medicare_wages[idx]
            print(f"{idx:>8} {fs[idx]:>6} {employment[idx]:>12,.0f} {se[idx]:>12,.0f} {total:>12,.0f} {pe_amt[idx]:>10,.0f} {our_amt[idx]:>10,.0f} {diff[idx]:>10,.0f}")

        # Check by filing status
        print("\n\nMismatches by filing status:")
        for fs_val in np.unique(fs):
            fs_mask = (fs == fs_val) & mismatch_mask
            if fs_mask.sum() > 0:
                print(f"  {fs_val}: {fs_mask.sum():,} mismatches")

        # Detailed cases
        for idx in mismatch_idx[:3]:
            print(f"\nDetailed case {idx}:")
            print(f"  Filing status: {fs[idx]}")
            print(f"  Employment income: ${employment[idx]:,.0f}")
            print(f"  Self-employment: ${se[idx]:,.0f}")
            print(f"  Total Medicare wages: ${medicare_wages[idx]:,.0f}")
            print(f"  Threshold: ${threshold[idx]:,.0f}")
            print(f"  Excess: ${excess[idx]:,.0f}")
            print(f"  PE Additional Medicare Tax: ${pe_amt[idx]:,.0f}")
            print(f"  Our Additional Medicare Tax: ${our_amt[idx]:,.0f}")


if __name__ == "__main__":
    diagnose_niit()
    diagnose_medicare_tax()

"""
Validate Child Tax Credit (26 USC § 24) encoding against PolicyEngine.

Compares the Cosilico encoding to PolicyEngine US calculations.
"""
import numpy as np
from policyengine_us import Microsimulation

# 2024 CTC Parameters (from Rev. Proc. 2023-34)
CREDIT_PER_CHILD = 2000
CREDIT_PER_OTHER_DEPENDENT = 500  # $500 for non-qualifying dependents (17+, etc.)
PHASEOUT_THRESHOLD_JOINT = 400000
PHASEOUT_THRESHOLD_SINGLE = 200000
PHASEOUT_RATE = 50  # $50 per $1,000 over threshold
REFUNDABLE_MAX_PER_CHILD = 1700
EARNED_INCOME_THRESHOLD = 2500
EARNED_INCOME_RATE = 0.15

def cosilico_ctc(
    num_ctc_children: np.ndarray,
    num_other_dependents: np.ndarray,
    num_actc_qualifying_children: np.ndarray,  # Children with SSN for ACTC
    filing_status_is_joint: np.ndarray,
    adjusted_gross_income: np.ndarray,
    earned_income: np.ndarray,
    tax_liability_before_credits: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute CTC using Cosilico encoding logic from 26 USC § 24.

    Returns (tentative_ctc, nonrefundable_portion, refundable_actc)

    Note: PolicyEngine's non_refundable_ctc is the portion NOT covered by ACTC,
    NOT the amount actually applied against tax liability.
    """
    # Step 1: Credit before phase-out - § 24(a)
    # $2,000 per qualifying child + $500 per other dependent
    credit_before_phaseout = (
        num_ctc_children * CREDIT_PER_CHILD +
        num_other_dependents * CREDIT_PER_OTHER_DEPENDENT
    )

    # Step 2: Determine phase-out threshold based on filing status - § 24(b)(1)
    threshold = np.where(
        filing_status_is_joint,
        PHASEOUT_THRESHOLD_JOINT,
        PHASEOUT_THRESHOLD_SINGLE
    )

    # Step 3: Calculate phase-out reduction - § 24(b)(2)
    # $50 for each $1,000 (or fraction thereof) over threshold
    excess = np.maximum(0, adjusted_gross_income - threshold)
    increments = np.ceil(excess / 1000)
    phaseout_reduction = increments * PHASEOUT_RATE

    # Step 4: Tentative credit after phase-out
    tentative_ctc = np.maximum(0, credit_before_phaseout - phaseout_reduction)

    # Step 5: Calculate ACTC (refundable portion) - § 24(d)
    # Only children with SSN qualify for refundable portion
    # 15% of earned income over $2,500 - § 24(d)(1)(B)(i)
    excess_earned = np.maximum(0, earned_income - EARNED_INCOME_THRESHOLD)
    actc_earned_portion = EARNED_INCOME_RATE * excess_earned

    # Per-child cap - § 24(h)(5) - only for SSN-qualified children
    actc_per_child_cap = num_actc_qualifying_children * REFUNDABLE_MAX_PER_CHILD

    # ACTC is limited by the earned income formula and per-child cap
    actc_limit = np.minimum(actc_earned_portion, actc_per_child_cap)

    # ACTC is also limited by tentative credit
    actc = np.minimum(tentative_ctc, actc_limit)

    # Step 6: Non-refundable portion = tentative CTC - ACTC
    # This is what PolicyEngine calls non_refundable_ctc
    nonrefundable_portion = tentative_ctc - actc

    return tentative_ctc, nonrefundable_portion, actc


def run_validation():
    """Run validation against PolicyEngine."""
    print("=" * 60)
    print("Child Tax Credit (26 USC § 24) Validation")
    print("=" * 60)

    # Load PolicyEngine simulation
    print("\nLoading PolicyEngine US simulation...")
    sim = Microsimulation()
    year = 2024

    # Get tax unit level variables directly (no aggregation needed)
    # These are already at tax_unit entity level
    pe_ctc_nonref = np.array(sim.calculate("non_refundable_ctc", year))
    pe_ctc_ref = np.array(sim.calculate("refundable_ctc", year))

    # Inputs for Cosilico calculation - all at tax_unit level
    # Note: ctc_qualifying_children counts children with SSN (for ACTC)
    # But PolicyEngine's CTC includes all children under 17
    # We need to compute the actual child count from person-level data
    ctc_qualifying_children = np.array(sim.calculate("ctc_qualifying_children", year))

    # Count all CTC-eligible children (not just those with SSN)
    person_tu_id = np.array(sim.calculate("person_tax_unit_id", year))
    ctc_child_max = np.array(sim.calculate("ctc_child_individual_maximum", year))
    tu_id = np.array(sim.calculate("tax_unit_id", year))

    # Count children with ctc_child_max > 0 per tax unit
    num_ctc_children = np.zeros(len(tu_id))
    for i, tu in enumerate(tu_id):
        mask = person_tu_id == tu
        num_ctc_children[i] = np.sum(ctc_child_max[mask] > 0)

    # Also count other dependents (for $500 ODC)
    ctc_adult_max = np.array(sim.calculate("ctc_adult_individual_maximum", year))
    num_other_dependents = np.zeros(len(tu_id))
    for i, tu in enumerate(tu_id):
        mask = person_tu_id == tu
        num_other_dependents[i] = np.sum(ctc_adult_max[mask] > 0)

    filing_status = np.array(sim.calculate("filing_status", year))
    agi = np.array(sim.calculate("adjusted_gross_income", year))
    earned_income = np.array(sim.calculate("tax_unit_earned_income", year))
    tax_before_credits = np.array(sim.calculate("income_tax_before_credits", year))

    n_tax_units = len(tu_id)
    print(f"Processing {n_tax_units:,} tax units...")

    # Check if joint filing
    # In PolicyEngine, filing_status is a string enum
    filing_status_is_joint = (filing_status == "JOINT") | (filing_status == "SURVIVING_SPOUSE")

    # Ensure tax liability is non-negative
    tax_liability = np.maximum(0, tax_before_credits)

    # Run Cosilico calculation
    print("Running Cosilico CTC calculation...")
    cosilico_tentative, cosilico_nonref_portion, cosilico_actc = cosilico_ctc(
        num_ctc_children,
        num_other_dependents,
        ctc_qualifying_children,  # SSN-qualified children for ACTC
        filing_status_is_joint,
        agi,
        earned_income,
        tax_liability
    )

    # Calculate totals
    # PE: non_refundable_ctc + refundable_ctc = total CTC (before tax limit)
    pe_total = pe_ctc_nonref + pe_ctc_ref
    # Cosilico: nonref_portion + actc = tentative (should equal pe_total)
    cosilico_total = cosilico_nonref_portion + cosilico_actc

    # Compute differences
    diff_total = np.abs(pe_total - cosilico_total)

    # Filter to tax units with any CTC-eligible dependents
    has_dependents = (num_ctc_children + num_other_dependents) > 0
    n_with_dependents = int(np.sum(has_dependents))

    print(f"\nTax units with CTC-eligible dependents: {n_with_dependents:,}")

    # Compute match rates (within $1 tolerance)
    tolerance = 1.0
    matches_total = diff_total[has_dependents] <= tolerance
    match_rate = np.mean(matches_total) * 100

    # Compute statistics
    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    print(f"\nTotal CTC Match Rate: {match_rate:.2f}%")
    print(f"  (within ${tolerance:.0f} tolerance)")

    print("\nSummary Statistics (tax units with dependents):")
    print(f"  Mean PE CTC:       ${np.mean(pe_total[has_dependents]):,.2f}")
    print(f"  Mean Cosilico CTC: ${np.mean(cosilico_total[has_dependents]):,.2f}")
    print(f"  Mean difference:   ${np.mean(diff_total[has_dependents]):,.2f}")
    print(f"  Max difference:    ${np.max(diff_total[has_dependents]):,.2f}")

    # Breakdown by component
    diff_nonref = np.abs(pe_ctc_nonref - cosilico_nonref_portion)
    diff_ref = np.abs(pe_ctc_ref - cosilico_actc)

    print("\nComponent Analysis:")
    print(f"  Nonrefundable portion match rate: {np.mean(diff_nonref[has_dependents] <= 1)*100:.2f}%")
    print(f"  Refundable ACTC match rate:       {np.mean(diff_ref[has_dependents] <= 1)*100:.2f}%")

    # Show mismatches
    mismatches = ~matches_total
    n_mismatches = int(np.sum(mismatches))

    if n_mismatches > 0:
        print(f"\nMismatches: {n_mismatches:,} ({n_mismatches/n_with_dependents*100:.1f}%)")

        # Sample mismatches
        mismatch_indices = np.where(has_dependents)[0][mismatches][:5]
        print("\nSample mismatches:")
        for idx in mismatch_indices:
            print(f"  Tax Unit {idx}:")
            print(f"    CTC children: {num_ctc_children[idx]:.0f}, Other deps: {num_other_dependents[idx]:.0f}, ACTC-eligible: {ctc_qualifying_children[idx]:.0f}")
            print(f"    AGI: ${agi[idx]:,.0f}")
            print(f"    Earned income: ${earned_income[idx]:,.0f}")
            print(f"    Tax liability: ${tax_liability[idx]:,.0f}")
            print(f"    Joint: {filing_status_is_joint[idx]}")
            print(f"    PE: ${pe_ctc_nonref[idx]:,.0f} nonref + ${pe_ctc_ref[idx]:,.0f} ref = ${pe_total[idx]:,.0f}")
            print(f"    Cosilico: ${cosilico_nonref_portion[idx]:,.0f} nonref + ${cosilico_actc[idx]:,.0f} ref = ${cosilico_total[idx]:,.0f}")
            print(f"    Diff: ${diff_total[idx]:,.0f}")

    return match_rate


if __name__ == "__main__":
    match_rate = run_validation()
    print("\n" + "=" * 60)
    if match_rate >= 99:
        print("✅ VALIDATION PASSED: >=99% match rate")
    elif match_rate >= 95:
        print("⚠️  VALIDATION WARNING: 95-99% match rate")
    else:
        print("❌ VALIDATION FAILED: <95% match rate")

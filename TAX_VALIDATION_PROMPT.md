# Federal Individual Income Tax Validation

## Goal
Validate and align Cosilico's federal individual income tax calculations against:
1. **TAXSIM** (NBER) - Primary benchmark
2. **PolicyEngine** - Secondary benchmark
3. **Tax-Calculator** (PSL) - Additional validation
4. **Yale Tax Simulator** - If accessible

## Current State
Check `src/cosilico_validators/comparison/record_comparison.py` for latest match rates.

## Success Criteria
All of these must be TRUE for completion:

1. **EITC**: 98%+ match rate vs PolicyEngine AND TAXSIM
2. **CTC (non-refundable)**: 95%+ match rate vs PolicyEngine AND TAXSIM
3. **CTC (refundable)**: 98%+ match rate vs PolicyEngine
4. **Income tax before credits**: 95%+ match rate vs PolicyEngine AND TAXSIM
5. **Self-employment tax**: 95%+ match rate vs PolicyEngine AND TAXSIM
6. **All tests pass**: `pytest` in cosilico-validators passes

## Work Process Each Iteration

1. **Run comparison**:
   ```python
   from cosilico_validators.comparison.record_comparison import compare_records
   results = compare_records(year=2024, sample_size=1000)
   ```

2. **Identify worst-performing variable** (lowest match rate)

3. **Analyze mismatches**:
   - Find records with largest differences
   - Identify pattern (income type? filing status? child count?)
   - Compare calculation step-by-step

4. **Fix the issue**:
   - If data mapping issue: fix `record_comparison.py`
   - If Cosilico formula issue: fix `cosilico_runner.py`
   - If missing statute: create `.rac` file in `cosilico-us`

5. **Validate fix**: Re-run comparison, confirm improvement

6. **Commit changes** with descriptive message

## Key Files

- `/Users/maxghenis/CosilicoAI/cosilico-data-sources/micro/us/cosilico_runner.py` - Cosilico calculations
- `/Users/maxghenis/CosilicoAI/cosilico-validators/src/cosilico_validators/comparison/record_comparison.py` - Comparison infrastructure
- `/Users/maxghenis/CosilicoAI/cosilico-us/statute/26/` - Statute encodings

## Architecture Rules

**CRITICAL**:
- Policy calculations ONLY in `cosilico_runner.py` or `.rac` files
- `tax_unit_builder.py` is DATA ONLY - run validator if you touch it:
  ```bash
  python validate_data_policy_separation.py
  ```

## Current Issues to Investigate

1. Non-refundable CTC: ~91% match (need 95%+)
2. EITC: ~92% match (need 98%+)
3. Income tax before credits: not yet compared directly
4. SE tax: not yet compared directly

## Adding New Variables

To add income_tax_before_credits comparison:
1. Add to `run_policyengine()` output in record_comparison.py
2. Add to TAXSIM output parsing
3. Add to `compare_records()` variables list
4. Run comparison and analyze

## When Complete

Output exactly this when ALL success criteria are met:
```
<promise>FEDERAL TAX VALIDATED</promise>
```

DO NOT output this promise unless:
- EITC match rate ≥ 98% vs PE AND TAXSIM
- CTC non-refundable match rate ≥ 95% vs PE AND TAXSIM
- CTC refundable match rate ≥ 98% vs PE
- Income tax match rate ≥ 95% vs PE AND TAXSIM
- SE tax match rate ≥ 95% vs PE AND TAXSIM
- All pytest tests pass

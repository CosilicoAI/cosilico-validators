# CPS Validation Run - December 25, 2025

## Summary

Ran CPS-scale validation on 30,182 tax units from PolicyEngine's enhanced CPS dataset.

### Results by Variable

| Variable | Match Rate | Status | Issue |
|----------|------------|--------|-------|
| AGI | **100.0%** | PASSED | Perfect match |
| CTC | 76.8% | NEEDS FIX | Depends on unresolved references |
| SE Tax | 94.9% | NEEDS FIX | Edge cases returning 0 |
| EITC | - | DSL ERROR | Multi-reference syntax not supported |
| Medicare Tax | - | DSL ERROR | Multi-reference syntax not supported |
| Capital Gains | - | DSL ERROR | Syntax error: Expected '}' at line 85 |
| Social Security | - | DSL ERROR | Syntax error: Expected 'then' at line 169 |
| SNAP | - | DSL ERROR | Ternary operator (?) not supported |
| NIIT | - | RUNTIME ERROR | Entity aggregation length mismatch |
| Std Deduction | - | WRONG PATH | Fixed: statute/26/63/c/ |
| QBI | - | WRONG PATH | Fixed: statute/26/199A/a/ |
| PTC | - | WRONG PATH | Fixed: statute/26/36B/a/ |

## Issues Created

### DSL Core Features (cosilico-engine)

1. **CosilicoAI-btk**: Support multi-reference syntax `reference ("ref1", "ref2")`
   - Affects: EITC, Medicare Tax
   - Error: "Expected reference string at line X"

2. **CosilicoAI-evz**: Support ternary operator `?:`
   - Affects: SNAP
   - Error: "Unexpected character '?' at line 33"
   - Alternative: Ensure inline `if X then Y else Z` works

3. **CosilicoAI-67a**: Fix entity aggregation length mismatch
   - Affects: NIIT
   - Error: "The weights and list don't have the same length"

### Encoding Fixes (cosilico-us)

4. **CosilicoAI-hnd**: Fix capital_gains_tax.cosilico syntax error
   - Error: "Expected '}' at line 85"

5. **CosilicoAI-8mz**: Fix taxable_social_security.cosilico syntax error
   - Error: "Expected 'then' at line 169"

### Validator Improvements

6. **CosilicoAI-y42**: Throw clear error for missing .cosilico files
   - Currently silently fails with message instead of raising exception

## Path Fixes Applied

Updated `variable_mapping.py` with correct file paths:

```python
# Fixed paths:
standard_deduction: statute/26/63/c/standard_deduction.cosilico
qbi_deduction: statute/26/199A/a/qbi_deduction.cosilico
ptc: statute/26/36B/a/premium_tax_credit.cosilico
```

## Next Steps

1. Add DSL features for multi-reference and ternary (or convert to if/then/else)
2. Fix entity aggregation bug in vectorized executor
3. Fix syntax errors in capital gains and social security encodings
4. Improve CTC encoding to resolve references or compute inline
5. Run validation again after fixes

## Raw Output

```
Dataset: 21,676 households, 30,182 tax units

AGI: 100.0% match (MAE: $0.00)
CTC: 76.8% match (MAE: $739.72)
SE Tax: 94.9% match (MAE: $205.89)
```

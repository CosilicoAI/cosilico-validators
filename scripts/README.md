# Encoding Scripts

Scripts for encoding and validating new tax variables using the cosilico-validators framework.

## Scripts

### `encode_new_variables.py`

Main encoding script that validates 4 new tax variables:

1. **Net Investment Income Tax (NIIT)** - 26 USC § 1411
2. **Additional Medicare Tax** - 26 USC § 3101(b)(2)
3. **Qualified Business Income Deduction (QBI)** - 26 USC § 199A
4. **Premium Tax Credit (PTC)** - 26 USC § 36B

**Usage**:
```bash
cd /Users/maxghenis/CosilicoAI/cosilico-validators
.venv/bin/python scripts/encode_new_variables.py
```

**Output**:
- Match rate for each variable
- Reward signal for RL training
- Diagnosis for any failures
- Improvement decisions for plugin refinements

### `generate_validation_report.py`

Generates detailed validation report with test case breakdown.

**Usage**:
```bash
.venv/bin/python scripts/generate_validation_report.py
```

**Output**:
- Detailed test case results
- Consensus levels
- PolicyEngine calculated values
- Issues and upstream bugs (if any)

## Test Cases

Each variable has 5 comprehensive test cases covering:

### NIIT (Net Investment Income Tax)
- Below threshold (no tax)
- Above threshold with investment income
- Joint filers
- Large capital gains
- No investment income (edge case)

### Additional Medicare Tax
- Below threshold
- Single filer above threshold
- Joint filers
- Self-employment income only
- Mixed W-2 and SE income

### QBI (Qualified Business Income Deduction)
- Simple case below threshold
- Below taxable income threshold
- Joint filers with substantial income
- Above threshold with W-2/property limitations
- No qualified business income (edge case)

### PTC (Premium Tax Credit)
- 150% FPL (substantial credit)
- 250% FPL with family
- 400% FPL (after ARP changes)
- Very high income (no credit)
- Below 100% FPL (Medicaid gap)

## Results

All 4 variables achieved:
- ✅ 100% match rate with PolicyEngine US
- ✅ FULL_AGREEMENT consensus on all test cases
- ✅ +1.00 reward signal for RL training

See [VALIDATION_RESULTS.md](../VALIDATION_RESULTS.md) for complete report.

## Dependencies

Requires Python 3.10-3.12 (PolicyEngine US constraint):

```bash
# Create venv with Python 3.12
python3.12 -m venv .venv

# Install dependencies
.venv/bin/pip install -e ".[policyengine]"
```

## Framework Components Used

- **EncodingOrchestrator**: Main validation workflow
- **PolicyEngineValidator**: Validates against PolicyEngine US
- **ConsensusEngine**: Determines agreement levels
- **DiagnosisLayer**: Identifies failure causes
- **ImprovementDecisions**: Suggests fixes for failed encodings

## Next Steps

1. Port test cases to cosilico-us repository
2. Implement DSL encodings based on validation results
3. Add W-2 wages and property inputs for QBI
4. Add health insurance premium inputs for PTC
5. Validate additional variables (AMT, SALT, mortgage interest, charitable)

# Pre-Registration: RL-Guided Tax Code Encoding

## Study Overview

**Objective:** Demonstrate that reinforcement learning with consensus validation can systematically encode the US federal income tax code into executable DSL, achieving parity with PolicyEngine.

**Hypothesis:** Each tax variable can achieve FULL_AGREEMENT with PolicyEngine within 1-5 prompt revision rounds, with complexity correlating to revision count.

**Reward Function:** ConsensusEngine validation against PolicyEngine-US (primary) and TAXSIM-35 (secondary).

---

## Dependency Graph: Federal Income Tax

The tax code forms a directed acyclic graph. Variables must be encoded in topological order.

```
LEVEL 0: INPUT VARIABLES (from microdata)
├── wages (§61(a)(1))
├── self_employment_income (§1402)
├── interest_income (§61(a)(4))
├── dividend_income (§61(a)(7))
├── capital_gains (§1222)
├── rental_income
├── age
├── filing_status (§1)
├── is_blind
└── num_dependents

LEVEL 1: GROSS INCOME
├── gross_income (§61) = sum of all income sources
└── earned_income (§32(c)(2)) = wages + SE income

LEVEL 2: ABOVE-THE-LINE DEDUCTIONS (§62)
├── educator_expenses (§62(a)(2)(D))
├── self_employment_tax_deduction (§164(f))
├── self_employed_health_insurance (§162(l))
├── ira_deduction (§219)
├── student_loan_interest (§221)
└── total_above_line_deductions

LEVEL 3: ADJUSTED GROSS INCOME
└── adjusted_gross_income (§62) = gross_income - above_line_deductions

LEVEL 4: DEDUCTIONS
├── standard_deduction (§63(c)) ✅ ENCODED
│   ├── basic_standard_deduction
│   ├── additional_aged_blind (§63(f))
│   └── dependent_limitation (§63(c)(5))
├── itemized_deductions (§63(d))
│   ├── medical_expenses (§213) - 7.5% AGI floor
│   ├── salt_deduction (§164) - $10K cap ⚠️ PARTIAL
│   ├── mortgage_interest (§163(h))
│   ├── charitable_contributions (§170)
│   └── casualty_losses (§165)
└── deduction = max(standard, itemized)

LEVEL 5: TAXABLE INCOME
└── taxable_income (§63(a)) = AGI - deduction - QBI_deduction

LEVEL 6: TAX BEFORE CREDITS
├── regular_tax (§1) ✅ BRACKETS ENCODED
│   └── Uses tax brackets by filing status
└── tentative_minimum_tax (§55(b))
    ├── amt_income = taxable_income + preferences
    ├── amt_exemption (§55(d)) ✅ ENCODED
    └── amt_tax = 26%/28% rates

LEVEL 7: CREDITS (reduce tax liability)
├── NON-REFUNDABLE (limited to tax liability)
│   ├── child_tax_credit_nonrefundable (§24) ✅ ENCODED
│   ├── child_dependent_care_credit (§21)
│   ├── education_credits (§25A)
│   ├── retirement_savings_credit (§25B)
│   ├── residential_energy_credit (§25C/D)
│   └── foreign_tax_credit (§27)
├── REFUNDABLE (can exceed liability)
│   ├── earned_income_credit (§32) ✅ ENCODED
│   ├── additional_child_tax_credit (§24(d)) ✅ ENCODED
│   └── american_opportunity_credit (§25A(i))
└── alternative_minimum_tax (§55) = max(0, TMT - regular_tax) ⚠️ PARTIAL

LEVEL 8: FINAL TAX
├── income_tax = regular_tax - credits + AMT
├── self_employment_tax (§1401)
├── net_investment_income_tax (§1411)
└── total_federal_tax
```

---

## Encoding Status

| Variable | Section | Level | Status | PE Variable | Rounds |
|----------|---------|-------|--------|-------------|--------|
| wages | §61(a)(1) | 0 | ✅ Input | employment_income | - |
| filing_status | §1 | 0 | ✅ Input | filing_status | - |
| age | - | 0 | ✅ Input | age | - |
| earned_income | §32(c)(2) | 1 | ✅ Encoded | earned_income | ? |
| gross_income | §61 | 1 | ❌ Missing | adjusted_gross_income | - |
| above_line_deductions | §62 | 2 | ❌ Missing | above_the_line_deductions | - |
| adjusted_gross_income | §62 | 3 | ⚠️ Partial | adjusted_gross_income | ? |
| standard_deduction | §63(c) | 4 | ✅ Encoded | standard_deduction | ? |
| itemized_deductions | §63(d) | 4 | ❌ Missing | itemized_taxable_income_deductions | - |
| salt_deduction | §164 | 4 | ⚠️ Partial | salt_deduction | ? |
| taxable_income | §63(a) | 5 | ❌ Missing | taxable_income | - |
| regular_tax | §1 | 6 | ⚠️ Partial | income_tax_before_credits | ? |
| amt_exemption | §55(d) | 6 | ✅ Encoded | amt_exemption | ? |
| tentative_minimum_tax | §55(b) | 6 | ❌ Missing | tentative_minimum_tax | - |
| eitc | §32 | 7 | ✅ Encoded | eitc | ? |
| ctc | §24 | 7 | ✅ Encoded | ctc | ? |
| alternative_minimum_tax | §55 | 7 | ⚠️ Partial | alternative_minimum_tax | ? |
| income_tax | §1 | 8 | ❌ Missing | income_tax | - |

**Legend:**
- ✅ Encoded: DSL exists in cosilico-us
- ⚠️ Partial: Encoded but not validated against PE
- ❌ Missing: Not yet encoded
- Rounds: RL iterations to achieve FULL_AGREEMENT (to be filled during study)

---

## Validation Protocol

### For Each Variable:

1. **Initial Encoding**
   - Claude encodes statute section into Cosilico DSL
   - Create test cases covering all code paths
   - Record: prompt used, time taken

2. **Validation Round 1**
   ```python
   result = validate_encoding(
       variable=var_name,
       test_cases=test_cases,
       year=2024,
   )
   ```
   - Record: match_rate, reward_signal, issues

3. **Iteration (if needed)**
   - Analyze discrepancies
   - Determine: encoding error vs upstream bug
   - Revise prompt/encoding
   - Re-validate
   - Record: changes made, new match_rate

4. **Completion Criteria**
   - FULL_AGREEMENT achieved, OR
   - POTENTIAL_UPSTREAM_BUG documented with citation

### Test Case Requirements:

Each variable must have test cases covering:
- [ ] Zero/edge values
- [ ] Phase-in region (if applicable)
- [ ] Plateau region (if applicable)
- [ ] Phase-out region (if applicable)
- [ ] All filing statuses
- [ ] Threshold boundaries (±$1)
- [ ] Historical years (2018-2024)

---

## Encoding Order (Topological)

### Phase 1: Foundation (Levels 0-3)
```
1. gross_income (§61)
2. above_line_deductions (§62)
3. adjusted_gross_income (§62)
```

### Phase 2: Deductions (Level 4)
```
4. itemized_deductions components:
   - medical_expense_deduction (§213)
   - salt_deduction (§164) - VALIDATE existing
   - mortgage_interest_deduction (§163(h))
   - charitable_deduction (§170)
5. standard_deduction (§63(c)) - VALIDATE existing
6. deduction (§63) - max(standard, itemized)
```

### Phase 3: Tax Calculation (Levels 5-6)
```
7. taxable_income (§63(a))
8. regular_tax (§1) - VALIDATE existing brackets
9. tentative_minimum_tax (§55(b))
```

### Phase 4: Credits (Level 7)
```
10. eitc (§32) - VALIDATE existing
11. ctc (§24) - VALIDATE existing
12. child_dependent_care_credit (§21)
13. education_credits (§25A)
14. alternative_minimum_tax (§55) - depends on TMT
```

### Phase 5: Final (Level 8)
```
15. income_tax_before_refundable_credits
16. income_tax (final)
17. self_employment_tax (§1401)
18. total_federal_tax
```

---

## Metrics to Track

### Per Variable:
- `encoding_rounds`: Number of prompt revisions
- `time_to_parity`: Time from start to FULL_AGREEMENT
- `test_cases_count`: Number of test cases
- `initial_match_rate`: First validation match rate
- `final_match_rate`: After all revisions
- `upstream_bugs_found`: PE/TAXSIM issues discovered

### Aggregate:
- Total encoding time
- Average rounds per variable
- Correlation: statute complexity vs rounds
- Upstream bugs filed

---

## Data Collection

Results stored in: `cosilico-validators/results/`

```
results/
├── encoding_log.jsonl       # All encoding attempts
├── validation_results.jsonl # All validation runs
├── upstream_bugs.jsonl      # Discovered PE/TAXSIM bugs
└── summary_stats.json       # Aggregate metrics
```

### Log Format:
```json
{
  "timestamp": "2024-12-23T...",
  "variable": "adjusted_gross_income",
  "section": "26 USC § 62",
  "round": 1,
  "prompt_hash": "abc123",
  "match_rate": 0.85,
  "reward_signal": 0.42,
  "issues": [...],
  "duration_seconds": 45
}
```

---

## Success Criteria

**Study succeeds if:**
1. All Level 0-6 variables achieve FULL_AGREEMENT
2. Average rounds ≤ 3 per variable
3. ≥ 90% of Level 7 credits achieve FULL_AGREEMENT
4. Any discrepancies are documented as upstream bugs with citations

**Study provides evidence for:**
- RL with consensus validation can encode complex legal rules
- Iteration count correlates with statute complexity
- Process discovers bugs in existing implementations

---

## Timeline

| Week | Phase | Variables |
|------|-------|-----------|
| 1 | Foundation | gross_income, above_line, AGI |
| 2 | Deductions | itemized components, standard |
| 3 | Tax Calc | taxable_income, regular_tax, TMT |
| 4 | Credits | Validate existing, add CDCTC, education |
| 5 | Final | AMT, income_tax, SE tax |
| 6 | Analysis | Aggregate results, write paper |

---

## Pre-Registration Date

**Registered:** 2024-12-23

**Investigators:**
- Max Ghenis (PolicyEngine)
- Claude (Anthropic) - encoding agent

**Repository:** https://github.com/CosilicoAI/cosilico-validators

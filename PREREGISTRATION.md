# Pre-Registration: Validation-Driven Tax Code Encoding

## Study Overview

**Objective:** Develop a continuously-improving AI system for encoding US tax and benefit law into executable DSL, validated against PolicyEngine and TAXSIM.

**Key Innovation:** Rather than per-variable debugging, we optimize the **encoding plugin** (instructions, subagents, prompts) and use **forecasted improvement decisions** to guide changes. Failures trigger multi-layer diagnosis to identify whether the issue is in the plugin, DSL, parameters, tests, or validators.

**Framework:** Claude Code plugin with subagent architecture, validated via consensus engine, with improvements tracked through [farness](https://github.com/MaxGhenis/farness) for forecast calibration.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ENCODING SYSTEM ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                      CLAUDE CODE PLUGIN                                 │ │
│  │                                                                         │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │ │
│  │  │   Statute    │  │   Formula    │  │  Test Case   │                  │ │
│  │  │   Parser     │──▶│  Generator   │──▶│  Generator   │                  │ │
│  │  │  Subagent    │  │  Subagent    │  │  Subagent    │                  │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘                  │ │
│  │                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                           │                                                  │
│                           ▼                                                  │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    CONSENSUS VALIDATION ENGINE                          │ │
│  │         PolicyEngine-US (primary) + TAXSIM-35 (secondary)              │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                           │                                                  │
│            ┌──────────────┴──────────────┐                                  │
│            ▼                             ▼                                  │
│     ┌─────────────┐              ┌─────────────┐                           │
│     │   Success   │              │   Failure   │                           │
│     └──────┬──────┘              └──────┬──────┘                           │
│            │                            │                                   │
│            ▼                            ▼                                   │
│  ┌──────────────────┐        ┌──────────────────────┐                      │
│  │ Suggest improve- │        │   MULTI-LAYER        │                      │
│  │ ments? (optional)│        │   DIAGNOSIS          │                      │
│  └────────┬─────────┘        │                      │                      │
│           │                  │  Which layer failed? │                      │
│           │                  │  • Plugin?           │                      │
│           │                  │  • DSL/Core?         │                      │
│           │                  │  • Parameters?       │                      │
│           │                  │  • Test cases?       │                      │
│           │                  │  • Validators?       │                      │
│           │                  │  • Variable schema?  │                      │
│           │                  └──────────┬───────────┘                      │
│           │                             │                                   │
│           └──────────────┬──────────────┘                                   │
│                          ▼                                                  │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    FARNESS IMPROVEMENT DECISION                         │ │
│  │                                                                         │ │
│  │  Claude suggests improvements with FORECASTS:                          │ │
│  │  • Expected success rate change: +5% [2%, 10%]                         │ │
│  │  • Expected regressions: 1 [0, 3]                                      │ │
│  │  • Implementation time: 0.5h [0.25h, 1h]                               │ │
│  │                                                                         │ │
│  │  After implementation, actuals are recorded for calibration.           │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Multi-Layer Diagnosis

When encoding fails, the problem could be at multiple layers:

| Layer | Repository | Example Issue | Example Fix |
|-------|------------|---------------|-------------|
| **1. Plugin** | cosilico-claude | "Claude misunderstood phase-out" | Improve prompt, add examples |
| **2. DSL/Core** | cosilico-engine | "Can't express circular dependency" | Add `iterate_until_stable()` primitive |
| **3. Parameters** | cosilico-data-sources | "Missing 2024 EITC threshold" | Add parameter with citation |
| **4. Test Cases** | cosilico-validators | "Expected value is wrong" | Correct test, add edge cases |
| **5. Validators** | cosilico-validators | "PE and TAXSIM disagree" | File upstream bug with citation |
| **6. Variable Schema** | cosilico-us | "Need investment_income input" | Add to inputs/variables.yaml |

### Diagnosis Flow

```python
class FailureDiagnosis:
    def diagnose(self, failure: EncodingAttempt) -> LayerDiagnosis:
        # Check each layer in order of likelihood

        if self.validators_disagree(failure):
            return LayerDiagnosis(layer="validator", ...)

        if self.missing_input_variable(failure):
            return LayerDiagnosis(layer="variable_schema", ...)

        if self.missing_parameter(failure):
            return LayerDiagnosis(layer="parameters", ...)

        if self.dsl_cant_express(failure):
            return LayerDiagnosis(layer="dsl_core", ...)

        if self.test_case_suspicious(failure):
            return LayerDiagnosis(layer="test_case", ...)

        # Default: plugin issue
        return LayerDiagnosis(layer="plugin", ...)
```

---

## Adaptive Validation Strategy

### Declining Sample Fraction

As confidence grows, we test fewer variables per plugin update:

```
Sample Fraction
100%│ ████
    │ ████
 50%│ ████ ████
    │ ████ ████ ████
 10%│ ████ ████ ████ ████ ████ ████
    └────────────────────────────────▶
      0    50   100  200  300  400  variables encoded
```

| Stage | Variables Encoded | Sample Fraction | Rationale |
|-------|-------------------|-----------------|-----------|
| Early | 0-50 | 100% | Building confidence |
| Middle | 50-200 | 30% | Established patterns |
| Late | 200-500 | 10% | High confidence |
| Scale | 500+ | 5% | Focus on new/risky |

### Multi-Version Testing (Explore/Exploit)

Plugin versions are treated as arms in a multi-armed bandit:

```python
class AdaptiveValidator:
    def select_plugin(self, strategy: str = "thompson") -> str:
        """Balance exploration of new plugins vs exploitation of proven ones."""
        if strategy == "thompson":
            # Thompson sampling: sample from Beta(successes+1, failures+1)
            samples = {
                v: np.random.beta(arm.successes + 1, arm.failures + 1)
                for v, arm in self.arms.items()
            }
            return max(samples, key=samples.get)
```

| Allocation | Plugin Type | Purpose |
|------------|-------------|---------|
| 70% | Stable (best proven) | Exploit: reliable encoding |
| 25% | Current (latest) | Exploit: incremental improvement |
| 5% | Experimental | Explore: test new approaches |

---

## Forecasted Improvement Decisions

Using [farness](https://github.com/MaxGhenis/farness), every improvement suggestion requires quantified forecasts:

### KPIs for Plugin Changes

```python
PLUGIN_KPIS = [
    KPI(name="success_rate_delta", unit="%", weight=1.0),
    KPI(name="regression_count", unit="count", weight=0.8),
    KPI(name="encoding_speed_delta", unit="ms", weight=0.3),
]
```

### Suggestion Format

Claude must provide forecasts for every suggested change:

```yaml
suggestions:
  - name: "Add filing status reminder to formula_gen"
    layer: "plugin"
    subagent: "formula_gen"
    change: "Add 'Always check filing status edge cases (MFS, HOH)' to prompt"
    forecasts:
      success_rate_delta:
        point: 5  # +5% success rate
        ci: [2, 10]  # 80% confidence interval
        reasoning: "Filing status errors caused 3 of last 10 failures"
      regression_count:
        point: 1
        ci: [0, 3]
        reasoning: "Minor prompt addition, low regression risk"
    base_rate: "Similar prompt additions improved success by 3-7% historically"
```

### Calibration Tracking

After implementation, actuals are recorded:

```python
decision.actual_outcomes = {
    "success_rate_delta": actual_improvement,
    "regression_count": regressions_detected,
}
decision.scored_at = datetime.now()

# Track calibration over time
tracker = CalibrationTracker(all_decisions)
print(tracker.summary())
# "Overconfident: only 65% of actuals in 80% CIs"
```

Claude sees its calibration history and adjusts forecasts accordingly.

---

## Tool-Based History Access

History is **queryable, not dumped** into context. Claude decides what's relevant:

```python
class PluginHistoryTools:
    """MCP-style tools for exploring history."""

    def get_recent_failures(self, n: int = 10) -> list[FailureSummary]:
        """Last N encoding failures."""

    def get_similar_failures(self, variable: str) -> list[FailureSummary]:
        """Failures on similar variable types."""

    def get_suggestion_outcomes(self, suggestion_type: str) -> list[SuggestionOutcome]:
        """How did similar suggestions perform?"""

    def get_calibration(self, kpi: str = None) -> CalibrationSummary:
        """Forecast accuracy stats."""

    def get_plugin_diff(self, v1: str, v2: str) -> str:
        """What changed between plugin versions?"""

    def search_history(self, query: str) -> list[HistoryMatch]:
        """Semantic search over encoding history."""

    def get_subagent_stats(self, subagent: str) -> SubagentStats:
        """Performance breakdown by subagent."""
```

### Storage Structure

```
results/
├── encoding_log.jsonl      # All encoding attempts
├── suggestions.jsonl       # All improvement suggestions
├── decisions.jsonl         # Farness decisions with forecasts
├── outcomes.jsonl          # Actual outcomes after implementation
├── calibration_cache.json  # Pre-computed calibration stats
└── index/                  # Search index for semantic queries
```

---

## Dependency Graph: Federal Income Tax

The tax code forms a DAG. Variables must be encoded in topological order.

```
LEVEL 0: INPUT VARIABLES (from microdata)
├── wages (§61(a)(1))
├── self_employment_income (§1402)
├── interest_income (§61(a)(4))
├── dividend_income (§61(a)(7))
├── capital_gains (§1222)
├── filing_status (§1)
├── age, is_blind, num_dependents

LEVEL 1: GROSS INCOME
├── gross_income (§61)
└── earned_income (§32(c)(2))

LEVEL 2: ABOVE-THE-LINE DEDUCTIONS (§62)
├── educator_expenses, ira_deduction, student_loan_interest
└── total_above_line_deductions

LEVEL 3: ADJUSTED GROSS INCOME
└── adjusted_gross_income (§62) = gross_income - above_line_deductions

LEVEL 4: DEDUCTIONS
├── standard_deduction (§63(c))
├── itemized_deductions (§63(d))
│   ├── medical_expenses (§213)
│   ├── salt_deduction (§164) - $10K cap
│   ├── mortgage_interest (§163(h))
│   └── charitable_contributions (§170)
└── deduction = max(standard, itemized)

LEVEL 5: TAXABLE INCOME
└── taxable_income (§63(a)) = AGI - deduction - QBI_deduction

LEVEL 6: TAX BEFORE CREDITS
├── regular_tax (§1)
└── tentative_minimum_tax (§55(b))

LEVEL 7: CREDITS
├── NON-REFUNDABLE: ctc, cdctc, education_credits, ...
├── REFUNDABLE: eitc, additional_ctc, ...
└── alternative_minimum_tax (§55)

LEVEL 8: FINAL TAX
└── total_federal_tax
```

---

## Metrics and Data Collection

### Per-Encoding Attempt

```python
@dataclass
class EncodingAttempt:
    # Identity
    variable: str
    section: str  # "26 USC § 32(a)(2)"
    plugin_version: str
    timestamp: datetime

    # Bandit context
    selection_strategy: str  # "thompson" | "exploit" | "explore"
    sample_fraction_used: float

    # Results
    passed: bool
    match_rate: float
    deviations: list[TestDeviation]
    generation_time_ms: int

    # Diagnosis (if failed)
    diagnosed_layer: str  # "plugin" | "dsl_core" | "parameters" | ...
    diagnosis_confidence: float
```

### Per-Plugin Version

```python
@dataclass
class PluginVersion:
    version: str
    subagent_versions: dict[str, str]

    # Bandit stats
    attempts: int
    successes: int
    failures: int
    success_rate: float

    # Breakdown
    failure_by_layer: dict[str, int]
    failure_by_subagent: dict[str, int]
```

### Per-Improvement Decision

```python
@dataclass
class ImprovementDecision:
    # Farness decision
    decision_id: str
    suggested_change: str
    target_layer: str
    target_repo: str

    # Forecasts
    forecasted_success_delta: Forecast
    forecasted_regressions: Forecast

    # Actuals (after implementation)
    actual_success_delta: float
    actual_regressions: int

    # Calibration
    forecast_error: float
    in_confidence_interval: bool
```

---

## Success Criteria

### Primary Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Federal tax coverage | ≥95% of variables pass | Variables with FULL_AGREEMENT / total |
| Average plugin iterations | ≤3 per variable type | Mean iterations across variable categories |
| Regression rate | ≤2% per plugin update | Regressions / sampled variables |
| Forecast calibration | 75-85% coverage | Actuals in 80% CIs |

### Learning Signals

1. **Plugin improvement rate**: Do success rates increase over time?
2. **Layer diagnosis accuracy**: Does fixing diagnosed layer solve the problem?
3. **Forecast calibration**: Is Claude learning to predict improvement impact?
4. **Transfer learning**: Do later variables encode faster than early ones?

---

## Bi-Temporal Model (Vintage × Policy Date)

See `cosilico-engine/docs/DESIGN.md` Section 12 for full architecture.

**Three temporal dimensions:**
1. **Vintage** (law-as-of) - explicitly modeled in parameters
2. **Policy date** (tax year) - explicitly modeled in parameters
3. **Model version** (Cosilico code) - tracked via git commit hash

| Vintage (law-as-of) | Policy Year | 2026 CTC | Why |
|---------------------|-------------|----------|-----|
| 2025-01-15 | 2026 | $1,000 | TCJA sunset (pre-OBBBA) |
| 2025-08-01 | 2026 | $2,000 | OBBBA passed July 2025 |
| 2025-01-15 | 2024 | $2,000 | TCJA still in effect |

---

## Multi-Jurisdiction Scale

| Component | Jurisdictions | Variables | Test Cases |
|-----------|---------------|-----------|------------|
| Federal Tax | 1 | ~50 | ~500 |
| Federal Benefits | 1 | ~30 | ~300 |
| State Taxes | 51 | ~20 each | ~10,000 |
| State Benefits | 51 | ~15 each | ~7,500 |
| **Total** | **51** | **~2,000** | **~18,000** |

---

## Research Questions

1. **Plugin vs other layers**: What fraction of failures are plugin issues vs DSL limitations vs parameter gaps?
2. **Forecast calibration**: Can Claude learn to accurately predict improvement impact?
3. **Explore/exploit tradeoff**: What's the optimal exploration rate for plugin versions?
4. **Transfer learning**: How much does encoding federal tax help with state taxes?
5. **DSL evolution**: What primitives should be added based on encoding failures?
6. **Upstream bugs**: How many PE/TAXSIM bugs are discovered through consensus validation?

---

## Timeline

| Phase | Weeks | Scope | Focus |
|-------|-------|-------|-------|
| Infrastructure | 0-2 | Build plugin, validators, farness integration | Architecture |
| A1 | 3-4 | Federal Tax Foundation | gross_income → AGI |
| A2 | 5-6 | Federal Tax Calc | taxable_income → income_tax |
| A3 | 7-8 | Federal Credits | EITC, CTC, AMT |
| B1 | 9-14 | State Taxes (Top 10) | CA, NY, TX, FL, PA, ... |
| B2 | 15-20 | State Taxes + Benefits | Remaining states |

---

## Pre-Registration Date

**Registered:** 2024-12-23 (updated 2024-12-24)

**Investigators:**
- Max Ghenis (PolicyEngine)
- Claude (Anthropic) - encoding agent

**Repository:** https://github.com/CosilicoAI/cosilico-validators

**Related:**
- [farness](https://github.com/MaxGhenis/farness) - forecast tracking
- [cosilico-engine](https://github.com/CosilicoAI/cosilico-engine) - DSL/core
- [cosilico-us](https://github.com/CosilicoAI/cosilico-us) - US statute encodings

# cosilico-validators

Multi-system tax/benefit validation framework for Cosilico DSL encodings.

## Overview

`cosilico-validators` validates tax and benefit calculations against multiple authoritative systems to compute a **consensus-based reward signal** for training AI encoding systems. When Claude encodes tax law into DSL and is highly confident, but validators disagree, it can automatically file issues to upstream repositories.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Cosilico DSL Test Cases                          │
│                    (with expected values from statute)               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Consensus Engine                              │
├──────────────────┬──────────────────┬──────────────────────────────┤
│    PRIMARY       │    REFERENCE     │        SUPPLEMENTARY         │
│    TaxAct        │   PolicyEngine   │      PSL Tax-Calculator      │
│  (ground truth)  │     TAXSIM       │      Atlanta Fed PRD         │
└──────────────────┴──────────────────┴──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Outputs                                       │
│  • Reward signal (-1.0 to +1.0) for training                        │
│  • Consensus level (FULL_AGREEMENT, PRIMARY_CONFIRMED, etc.)        │
│  • Confidence score (0.0 to 1.0)                                    │
│  • Potential upstream bugs (auto-filed to GitHub)                   │
└─────────────────────────────────────────────────────────────────────┘
```

## Installation

```bash
# Basic installation (TAXSIM only)
pip install cosilico-validators

# With PolicyEngine support
pip install cosilico-validators[policyengine]

# All validators
pip install cosilico-validators[all]

# Development
pip install cosilico-validators[dev]
```

## Quick Start

### Python API

```python
from cosilico_validators import ConsensusEngine, TestCase
from cosilico_validators.validators.policyengine import PolicyEngineValidator
from cosilico_validators.validators.taxsim import TaxsimValidator

# Create validators
validators = [
    PolicyEngineValidator(),
    TaxsimValidator(),
]

# Create consensus engine
engine = ConsensusEngine(validators, tolerance=15.0)

# Define test case
test_case = TestCase(
    name="EITC single no children",
    inputs={
        "earned_income": 15000,
        "filing_status": "SINGLE",
        "eitc_qualifying_children_count": 0,
    },
    expected={"eitc": 600},
    citation="26 USC § 32",
)

# Validate with Claude's confidence
result = engine.validate(
    test_case,
    variable="eitc",
    year=2024,
    claude_confidence=0.95,
)

print(f"Consensus: {result.consensus_level.value}")
print(f"Reward signal: {result.reward_signal:+.2f}")
print(f"Matches expected: {result.matches_expected}")

# Check for potential upstream bugs
if result.potential_bugs:
    for bug in result.potential_bugs:
        print(f"Potential bug in {bug['validator']}: "
              f"expected ${bug['expected']}, got ${bug['actual']}")
```

### CLI

```bash
# Validate test cases
cosilico-validators validate tests.yaml --variable eitc --year 2024

# With Claude confidence for bug detection
cosilico-validators validate tests.yaml -v eitc --claude-confidence 0.95

# Save results to JSON
cosilico-validators validate tests.yaml -v eitc -o results.json

# List available validators
cosilico-validators validators

# File issues for potential bugs (dry run)
cosilico-validators file-issues results.json --dry-run

# Actually file issues
export GITHUB_TOKEN=your_token
cosilico-validators file-issues results.json --repo PolicyEngine/policyengine-us
```

## Consensus Levels

| Level | Description | Reward Bonus |
|-------|-------------|--------------|
| `FULL_AGREEMENT` | All validators agree within tolerance | +0.5 |
| `PRIMARY_CONFIRMED` | Primary (TaxAct) + majority agree | +0.4 |
| `MAJORITY_AGREEMENT` | >50% of validators agree | +0.2 |
| `DISAGREEMENT` | No consensus reached | -0.2 |
| `POTENTIAL_UPSTREAM_BUG` | Claude confident, validators disagree | +0.1 |

## Reward Signal

The reward signal ranges from -1.0 to +1.0:

```python
reward = consensus_bonus + match_bonus
# consensus_bonus: Based on consensus level (-0.2 to +0.5)
# match_bonus: Weighted by validator type (PRIMARY = 2x weight)
```

Higher rewards indicate:
- More validators agree with expected value
- Primary validator confirms
- Higher consensus level

## Upstream Bug Detection

When Claude is highly confident (>90%) but validators disagree with the expected value:

1. The system flags a `POTENTIAL_UPSTREAM_BUG`
2. Details are captured with citation and inputs
3. Issues can be auto-filed to GitHub

```python
from cosilico_validators.upstream import GitHubIssueManager

manager = GitHubIssueManager(token="github_token")
results = manager.file_all_bugs(
    validation_result.potential_bugs,
    dry_run=False,
    confidence_threshold=0.9,
)
```

## Supported Variables

### TAXSIM
- `federal_income_tax`, `state_income_tax`
- `eitc`, `ctc`, `actc`, `cdctc`
- `agi`, `taxable_income`, `amt`
- `fica`, `state_eitc`

### PolicyEngine
- `eitc`, `ctc`, `income_tax`
- `snap`, `medicaid`, `tanf`
- And all 2000+ variables in policyengine-us

## Test Case Format

```yaml
# tests.yaml
test_cases:
  - name: "EITC single filer, one child"
    inputs:
      earned_income: 25000
      filing_status: SINGLE
      eitc_qualifying_children_count: 1
    expected:
      eitc: 3995
    citation: "26 USC § 32(b)(1)(A)"
    notes: "Phase-in complete, before plateau ends"

  - name: "CTC married filing jointly, two children"
    inputs:
      earned_income: 150000
      filing_status: JOINT
      num_children: 2
    expected:
      ctc: 4000
    citation: "26 USC § 24"
```

## Development

```bash
# Clone the repo
git clone https://github.com/CosilicoAI/cosilico-validators.git
cd cosilico-validators

# Install with dev dependencies
pip install -e ".[dev,policyengine]"

# Run tests
pytest

# Type check
mypy src/
```

## Architecture

```
cosilico-validators/
├── src/cosilico_validators/
│   ├── validators/           # Validator implementations
│   │   ├── base.py          # BaseValidator, TestCase, ValidatorResult
│   │   ├── policyengine.py  # PolicyEngine US integration
│   │   ├── taxsim.py        # NBER TAXSIM web service
│   │   └── taxact.py        # TaxAct (manual/primary)
│   ├── consensus/
│   │   └── engine.py        # Multi-system consensus & reward
│   ├── upstream/
│   │   └── github.py        # GitHub issue filing
│   └── cli.py               # Command-line interface
└── tests/
```

## Related Projects

- [cosilico-lawarchive](https://github.com/CosilicoAI/cosilico-lawarchive) - Statute encoding pipeline
- [policyengine-us](https://github.com/PolicyEngine/policyengine-us) - US tax-benefit microsimulation
- [TAXSIM](https://taxsim.nber.org/taxsim35/) - NBER tax calculator
- [PSL Tax-Calculator](https://github.com/PSLmodels/Tax-Calculator) - Policy Simulation Library

## License

MIT

# rac-validators

Validation infrastructure for RAC encodings against external calculators.

## Purpose

Validates RAC file outputs against authoritative sources:
- **PolicyEngine** - Open-source tax-benefit microsimulation
- **TAXSIM** - NBER tax calculator

## Structure

```
rac-validators/
├── src/                  # Validation logic
├── baselines/            # Known-good test baselines
├── taxsim/              # TAXSIM integration
├── examples/            # Example validation runs
├── experiments/         # Calibration experiments
└── scripts/             # CLI tools
```

## Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Run validation
python -m validators.policyengine --rac-file path/to.rac
python -m validators.taxsim --rac-file path/to.rac

# Run tests
pytest tests/ -v
```

## Related Repos

- **rac** - DSL parser, executor, runtime
- **rac-us** - US statute encodings
- **autorac** - AI-assisted encoding harness (uses validators)

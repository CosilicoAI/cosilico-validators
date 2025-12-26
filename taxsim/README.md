# TaxSim 35 Validation Infrastructure

This module provides tools for validating Cosilico tax calculations against NBER's [TaxSim 35](https://taxsim.nber.org/taxsim35/) web API.

## Overview

TaxSim is the NBER's Tax Simulator, widely used for federal and state income tax calculations. This infrastructure enables:

- Submitting tax scenarios to the TaxSim 35 web API
- Parsing and mapping TaxSim output to Cosilico variable names
- Comparing Cosilico calculations against TaxSim results
- Generating detailed validation reports

## Installation

The TaxSim validation module is part of cosilico-validators:

```bash
pip install cosilico-validators
```

No additional dependencies are required - TaxSim is accessed via web API.

## Quick Start

### Basic TaxSim Calculation

```python
from cosilico_validators.taxsim import TaxSimClient, TaxSimCase

# Create client
client = TaxSimClient()

# Define a tax case
case = TaxSimCase(
    year=2023,
    filing_status="SINGLE",
    primary_age=35,
    primary_wages=50000,
)

# Calculate
result = client.calculate(case)

# Access results
print(f"AGI: ${result.cosilico_output['adjusted_gross_income']:,.2f}")
print(f"Federal Tax: ${result.cosilico_output['total_federal_income_tax']:,.2f}")
print(f"EITC: ${result.cosilico_output['earned_income_credit']:,.2f}")
```

### Batch Calculations

```python
cases = [
    TaxSimCase(year=2023, filing_status="SINGLE", primary_wages=30000),
    TaxSimCase(year=2023, filing_status="JOINT", primary_wages=60000, spouse_wages=40000),
    TaxSimCase(year=2023, filing_status="HOH", primary_wages=45000, num_dependents=1),
]

results = client.calculate_batch(cases)
for result in results:
    print(f"Federal Tax: ${result.cosilico_output.get('total_federal_income_tax', 0):,.2f}")
```

### Comparing Against Cosilico

```python
from cosilico_validators.taxsim import TaxSimComparison, TaxSimCase

# Define your Cosilico calculator function
def cosilico_calc(case: TaxSimCase, variables: list) -> dict:
    # Your Cosilico DSL calculation here
    return {
        "adjusted_gross_income": 50000,
        "earned_income_credit": 0,
        # ... other variables
    }

# Create comparison engine
comparison = TaxSimComparison(
    cosilico_calculator=cosilico_calc,
    variables=["adjusted_gross_income", "earned_income_credit", "child_tax_credit"],
    tolerance=1.0,  # $1 tolerance
)

# Load test cases and run comparison
report = comparison.run_from_yaml("test_cases.yaml", year=2023)

# Output report
print(report.to_markdown())

# Or save to JSON
with open("validation_report.json", "w") as f:
    f.write(report.to_json())
```

## Test Cases

The `test_cases.yaml` file includes scenarios covering:

| Category | Scenarios |
|----------|-----------|
| Simple Cases | Single filer, low/high income |
| Married Filing Jointly | Two earners, single earner, CTC phase-out |
| Self-Employment | SE only, mixed wages+SE |
| Investment Income | Dividends, capital gains, mixed |
| EITC Eligible | No children, 1/2/3+ children, phase-out |
| AMT | High deductions, ISO income |
| Retirement Income | Social Security, pensions |
| Edge Cases | Zero income, age limits, NIIT |

## Variable Mapping

### Key TaxSim to Cosilico Mappings

| TaxSim Variable | Cosilico Variable | Description |
|-----------------|-------------------|-------------|
| `v10` | `adjusted_gross_income` | Federal AGI |
| `v18` | `taxable_income` | Taxable income |
| `v22` | `child_tax_credit` | Non-refundable CTC |
| `v23` | `additional_child_tax_credit` | Refundable ACTC |
| `v25` | `earned_income_credit` | EITC |
| `v27` | `amt` | Alternative Minimum Tax |
| `v29` | `total_fica_tax` | Employee FICA |
| `fiitax` | `total_federal_income_tax` | Federal income tax |

### Cosilico Aliases

For convenience, these aliases are also supported:

| Alias | Canonical Name |
|-------|----------------|
| `agi` | `adjusted_gross_income` |
| `ctc` | `child_tax_credit` |
| `actc` | `additional_child_tax_credit` |
| `eitc` | `earned_income_credit` |
| `cdctc` | `child_and_dependent_care_credit` |

## API Reference

### TaxSimCase

Represents a tax case to submit to TaxSim:

```python
case = TaxSimCase(
    taxsimid=1,                    # Unique record ID
    year=2023,                     # Tax year (1960-2023)
    state="CA",                    # State code or abbreviation
    filing_status="JOINT",         # SINGLE, JOINT, HOH, SEPARATE
    primary_age=40,                # Primary taxpayer age
    spouse_age=38,                 # Spouse age (0 if single)
    num_dependents=2,              # Number of dependents
    child_ages=[10, 8],            # Ages of dependents
    primary_wages=75000,           # Primary wages
    spouse_wages=45000,            # Spouse wages
    primary_self_employment=0,     # SE income
    dividends=1000,                # Dividend income
    interest=500,                  # Interest income
    long_term_gains=5000,          # LTCG
    # ... and more
)
```

### TaxSimClient

Client for the TaxSim 35 web API:

```python
client = TaxSimClient(
    timeout=120,        # Request timeout (seconds)
    max_retries=3,      # Retry attempts
    retry_delay=1.0,    # Delay between retries
)

result = client.calculate(case)
results = client.calculate_batch(cases)
```

### TaxSimComparison

Comparison engine for validating against Cosilico:

```python
comparison = TaxSimComparison(
    cosilico_calculator=calc_func,  # Your calculation function
    variables=["agi", "eitc"],      # Variables to compare
    tolerance=1.0,                  # Dollar tolerance
)

report = comparison.run(cases, year=2023)
```

## Connection Methods

TaxSim 35 supports multiple access methods:

### SSH (Recommended for Interactive Use)

```bash
ssh taxsim35@taxsimssh.nber.org < input.csv
```

The SSH method is fastest and most reliable. The client attempts SSH first when run from an interactive terminal with SSH agent access.

**Note**: SSH requires proper SSH key configuration. If running from automated environments (CI/CD, scripts), ensure SSH keys are properly configured or use the local executable method.

### Local Executable (Recommended for Automation)

For automated testing and CI/CD, download the TAXSIM executable and use the existing `TaxsimValidator` class in `cosilico_validators.validators.taxsim`:

```bash
# Download the executable for your platform
curl -O https://taxsim.nber.org/taxsim35/taxsim35-osx.exe  # macOS
curl -O https://taxsim.nber.org/taxsim35/taxsim35-unix.exe # Linux
```

### HTTP (Fallback)

The HTTP method is used as a fallback but has limitations for large batches (>2,000 records).

## TaxSim 35 Limitations

- **Supported Years**: 1960-2023 only (TAXSIM-35 does not support 2024+)
- **Rate Limits**: Large batches may be throttled via HTTP
- **State Taxes**: Not all state features are fully implemented
- **Recent Provisions**: Newer tax provisions may not be available
- **SSH Access**: Requires interactive terminal with SSH agent for automatic authentication

## Reporting Issues

If you find discrepancies between TaxSim and your calculations:

1. First verify your inputs match TaxSim's expectations
2. Check the TaxSim documentation for edge cases
3. If TaxSim appears incorrect, file an issue with the Cosilico validators repo
4. For TaxSim bugs, report to taxsim@nber.org

## References

- [TaxSim 35 Documentation](https://taxsim.nber.org/taxsim35/)
- [TaxSim Input Variables](https://taxsim.nber.org/taxsim35/taxsim.html)
- [TaxSim Output Variables](https://taxsim.nber.org/taxsim35/taxsim-output.html)
- [NBER TaxSim Working Papers](https://www.nber.org/research/data/taxsim)

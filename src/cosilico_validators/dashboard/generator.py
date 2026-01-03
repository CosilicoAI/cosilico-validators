"""
Validation Dashboard Generator

Generates validation results JSON for:
1. cosilico.ai dashboard display
2. LLM reviewer context
3. CI pass/fail checks

Usage:
    python -m cosilico_validators.dashboard.generator \
        --rac-repo rac-us \
        --variable income_tax_before_credits \
        --years 2018,2019,2020,2021,2022,2023
"""

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .schema import VariableValidation, ValidationDashboard, YearResult
from .oracle_runner import validate_variable, select_oracle


def get_git_version(repo_path: Path) -> str:
    """Get git SHA or tag for repo."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    return "unknown"


def generate_variable_validation(
    variable: str,
    citation: str,
    rac_repo: str,
    rac_path: Path,
    years: list[int],
    cps_data: Optional[any] = None,
) -> VariableValidation:
    """
    Generate validation results for a single variable.

    Args:
        variable: Variable name (e.g., "income_tax_before_credits")
        citation: Statute citation (e.g., "26 USC 1")
        rac_repo: Repository name (e.g., "rac-us")
        rac_path: Path to rac repo
        years: Years to validate
        cps_data: Pre-loaded CPS DataFrame (optional)

    Returns:
        VariableValidation with results for all years
    """
    validation = VariableValidation(
        variable=variable,
        citation=citation,
        rac_repo=rac_repo,
        rac_version=get_git_version(rac_path),
        generated_at=datetime.utcnow().isoformat() + "Z",
    )

    try:
        # Load CPS data if not provided
        if cps_data is None:
            cps_data = _load_cps_data()

        if cps_data is None or len(cps_data) == 0:
            validation.error = "Failed to load CPS data"
            validation.status = "error"
            return validation

        # Run RAC calculations on CPS data
        rac_results = _run_rac_calculations(cps_data, variable, rac_path)

        # Validate against oracles for each year
        for year in years:
            try:
                year_result = _validate_year(rac_results, variable, year)
                validation.years.append(year_result)
            except Exception as e:
                validation.years.append(YearResult(
                    year=year,
                    oracle=select_oracle(year),
                    match_rate=0.0,
                    sample_size=0,
                    rac_total=0.0,
                    oracle_total=0.0,
                    bias_pct=0.0,
                    mean_diff=0.0,
                    median_diff=0.0,
                    max_abs_diff=0.0,
                    correlation=0.0,
                    discrepancies=[f"Error: {e}"],
                ))

        validation.compute_aggregates()

    except Exception as e:
        validation.error = str(e)
        validation.status = "error"

    return validation


def _load_cps_data():
    """Load CPS microdata for validation."""
    import pandas as pd

    # Try multiple CPS data sources
    cps_paths = [
        Path.home() / "CosilicoAI/microplex-sources/micro/us/cps_2023.parquet",
        Path.home() / "CosilicoAI/microplex/data/cps_asec_households.parquet",
    ]

    for path in cps_paths:
        if path.exists():
            try:
                return pd.read_parquet(path)
            except Exception:
                continue

    # Fall back to PE CPS
    try:
        from policyengine_us import Microsimulation
        sim = Microsimulation()
        # Build DataFrame from PE simulation
        return _pe_sim_to_df(sim)
    except Exception:
        pass

    return None


def _pe_sim_to_df(sim) -> "pd.DataFrame":
    """Convert PE simulation to DataFrame."""
    import numpy as np
    import pandas as pd

    year = 2023
    return pd.DataFrame({
        "tax_unit_id": range(len(sim.calculate("tax_unit_id", year))),
        "wages": np.array(sim.calculate("employment_income", year)),
        "weight": np.array(sim.calculate("tax_unit_weight", year)),
        "age": np.array(sim.calculate("age", year)),
        "mstat": np.array(sim.calculate("filing_status", year)),
    })


def _run_rac_calculations(df, variable: str, rac_path: Path):
    """Run RAC calculations on CPS data."""
    # TODO: Implement actual RAC calculation
    # For now, return the DataFrame as-is with placeholder values
    import numpy as np

    # Placeholder: Copy wages as income_tax_before_credits * 0.15
    if "wages" in df.columns:
        df[f"rac_{variable}"] = df["wages"] * 0.15

    return df


def _validate_year(df, variable: str, year: int) -> YearResult:
    """Validate a single year against appropriate oracle."""
    from .oracle_runner import run_taxsim, run_policyengine, select_oracle

    oracle = select_oracle(year)

    if oracle == "taxsim":
        return run_taxsim(df, year, variable)
    else:
        return run_policyengine(df, year, variable)


def generate_dashboard(
    rac_repo: str,
    rac_path: Path,
    variables: list[tuple[str, str]],  # [(variable, citation), ...]
    years: list[int],
    output_dir: Path,
) -> ValidationDashboard:
    """
    Generate complete validation dashboard.

    Args:
        rac_repo: Repository name
        rac_path: Path to repo
        variables: List of (variable_name, citation) tuples
        years: Years to validate
        output_dir: Directory to write JSON files

    Returns:
        ValidationDashboard with all results
    """
    dashboard = ValidationDashboard(
        rac_repo=rac_repo,
        rac_version=get_git_version(rac_path),
        generated_at=datetime.utcnow().isoformat() + "Z",
    )

    # Load CPS data once
    cps_data = _load_cps_data()

    for variable, citation in variables:
        validation = generate_variable_validation(
            variable=variable,
            citation=citation,
            rac_repo=rac_repo,
            rac_path=rac_path,
            years=years,
            cps_data=cps_data,
        )
        dashboard.variables.append(validation)

        # Write individual variable JSON
        var_file = output_dir / f"{variable}.json"
        var_file.parent.mkdir(parents=True, exist_ok=True)
        var_file.write_text(validation.to_json())

    # Write complete dashboard JSON
    dashboard_file = output_dir / "dashboard.json"
    dashboard_file.write_text(dashboard.to_json())

    # Write LLM context file
    llm_file = output_dir / "llm_context.md"
    llm_context = "\n\n".join(v.to_llm_context() for v in dashboard.variables)
    llm_file.write_text(llm_context)

    return dashboard


def main():
    parser = argparse.ArgumentParser(description="Generate validation dashboard")
    parser.add_argument("--rac-repo", default="rac-us", help="RAC repo name")
    parser.add_argument("--rac-path", type=Path, help="Path to RAC repo")
    parser.add_argument("--variable", help="Variable to validate")
    parser.add_argument("--citation", help="Statute citation")
    parser.add_argument("--years", default="2018,2019,2020,2021,2022,2023",
                       help="Comma-separated years")
    parser.add_argument("--output", type=Path, default=Path("results"),
                       help="Output directory")

    args = parser.parse_args()

    years = [int(y) for y in args.years.split(",")]

    if args.rac_path is None:
        args.rac_path = Path.home() / "CosilicoAI" / args.rac_repo

    if args.variable:
        # Single variable mode
        validation = generate_variable_validation(
            variable=args.variable,
            citation=args.citation or "",
            rac_repo=args.rac_repo,
            rac_path=args.rac_path,
            years=years,
        )
        print(validation.to_json())

        # Write to file
        output_file = args.output / f"{args.variable}.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(validation.to_json())
        print(f"\nWritten to: {output_file}")

    else:
        # Full dashboard mode
        variables = [
            ("income_tax_before_credits", "26 USC 1"),
            ("eitc", "26 USC 32"),
            ("ctc", "26 USC 24"),
        ]

        dashboard = generate_dashboard(
            rac_repo=args.rac_repo,
            rac_path=args.rac_path,
            variables=variables,
            years=years,
            output_dir=args.output,
        )

        print(f"Dashboard generated: {len(dashboard.variables)} variables")
        print(f"  Passed: {dashboard.passed}")
        print(f"  Warned: {dashboard.warned}")
        print(f"  Failed: {dashboard.failed}")


if __name__ == "__main__":
    main()

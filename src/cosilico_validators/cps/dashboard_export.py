"""Export CPS validation results to dashboard JSON format."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import subprocess

from .runner import ValidationResult, VariableConfig, CPSValidationRunner


def get_git_commit() -> str:
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def get_policyengine_version() -> str:
    """Get installed PolicyEngine version."""
    try:
        from policyengine_us import __version__
        return __version__
    except ImportError:
        return "not installed"


def result_to_section(result: ValidationResult) -> Dict[str, Any]:
    """Convert ValidationResult to dashboard section format."""
    section = {
        "section": result.variable.section,
        "title": result.variable.title,
        "variable": result.variable.name,
        "households": result.households,
        "testCases": [],
        "summary": {
            "total": result.households,
            "matches": result.pe_results.get("policyengine", 0),
            "matchRate": result.pe_results.get("policyengine", 0) / result.households
            if result.households > 0
            else 0,
            "meanAbsoluteError": result.mean_absolute_error,
        },
    }

    # Add validator breakdown
    validator_breakdown = {}
    if "policyengine" in result.pe_results:
        pe_matches = result.pe_results["policyengine"]
        validator_breakdown["policyengine"] = {
            "matches": pe_matches,
            "total": result.households,
            "rate": pe_matches / result.households if result.households > 0 else 0,
        }

    if result.taxsim_results and "taxsim" in result.taxsim_results:
        ts_matches = result.taxsim_results["taxsim"]
        validator_breakdown["taxsim"] = {
            "matches": ts_matches,
            "total": result.households,
            "rate": ts_matches / result.households if result.households > 0 else 0,
        }

    if validator_breakdown:
        section["validatorBreakdown"] = validator_breakdown

    # Add mismatches
    if result.mismatches:
        # Group mismatches by pattern (simplified - real impl would analyze patterns)
        section["mismatches"] = [
            {
                "description": "Value differences exceeding tolerance",
                "count": len(result.mismatches),
                "explanation": f"Cases where PE and TAXSIM differ by more than ${result.variable.tolerance:.0f}",
                "citation": f"See {result.variable.section}",
            }
        ]

    return section


def export_dashboard_json(
    results: Dict[str, ValidationResult],
    output_path: Path,
    data_source: str = "CPS ASEC",
    year: int = 2024,
) -> None:
    """
    Export validation results to dashboard-compatible JSON.

    Args:
        results: Dict of variable name -> ValidationResult
        output_path: Where to write the JSON file
        data_source: Description of data source
        year: Tax year
    """
    # Calculate overall statistics
    total_households = max(r.households for r in results.values()) if results else 0
    total_tests = sum(r.households for r in results.values())
    total_matches = sum(r.pe_results.get("policyengine", 0) for r in results.values())

    # Build sections
    sections = [result_to_section(r) for r in results.values()]

    # Determine validator availability
    has_taxsim = any(r.taxsim_results for r in results.values())
    taxsim_households = sum(
        r.households for r in results.values() if r.taxsim_results
    )

    validators = [
        {
            "name": "policyengine",
            "available": True,
            "version": get_policyengine_version(),
            "householdsCovered": total_households,
        },
        {
            "name": "taxsim",
            "available": has_taxsim,
            "version": "35",
            "householdsCovered": taxsim_households if has_taxsim else 0,
        },
        {"name": "taxact", "available": False},
    ]

    # Calculate mean MAE across all variables
    maes = [r.mean_absolute_error for r in results.values() if r.mean_absolute_error > 0]
    overall_mae = sum(maes) / len(maes) if maes else 0

    report = {
        "isSampleData": False,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "commit": get_git_commit(),
        "dataSource": f"{data_source} {year}",
        "householdsTotal": total_households,
        "sections": sections,
        "overall": {
            "totalHouseholds": total_households,
            "totalTests": total_tests,
            "totalMatches": total_matches,
            "matchRate": total_matches / total_tests if total_tests > 0 else 0,
            "meanAbsoluteError": overall_mae,
        },
        "validators": validators,
    }

    # Write JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Exported results to {output_path}")


def run_and_export(
    output_path: Optional[Path] = None,
    year: int = 2024,
    dataset: str = "enhanced_cps",
) -> None:
    """
    Run CPS validation and export results.

    Args:
        output_path: Where to write JSON (default: validation-results.json)
        year: Tax year
        dataset: PolicyEngine dataset (default: enhanced_cps)
    """
    if output_path is None:
        output_path = Path("validation-results.json")

    runner = CPSValidationRunner(year=year, dataset=dataset)
    results = runner.run()

    export_dashboard_json(
        results,
        output_path,
        data_source=f"Enhanced CPS ({dataset})",
        year=year,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run CPS validation and export to JSON")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("validation-results.json"),
        help="Output JSON file path",
    )
    parser.add_argument(
        "-y", "--year",
        type=int,
        default=2024,
        help="Tax year",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="enhanced_cps",
        help="PolicyEngine dataset name (default: enhanced_cps)",
    )

    args = parser.parse_args()
    run_and_export(args.output, args.year, args.dataset)

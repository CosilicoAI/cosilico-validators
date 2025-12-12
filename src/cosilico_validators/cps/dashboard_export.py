"""Export CPS validation results to dashboard JSON format."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import subprocess

from .runner import ValidationResult, ComparisonResult, CPSValidationRunner


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


def get_cosilico_version() -> str:
    """Get Cosilico engine version."""
    try:
        # Try to get git commit from cosilico-engine
        engine_path = Path.home() / "CosilicoAI/cosilico-engine"
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=engine_path,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "dev"


def comparison_to_breakdown(comp: ComparisonResult) -> Dict[str, Any]:
    """Convert ComparisonResult to validator breakdown format."""
    return {
        "matches": comp.n_matches,
        "total": comp.n_compared,
        "rate": comp.match_rate,
    }


def result_to_section(result: ValidationResult) -> Dict[str, Any]:
    """Convert ValidationResult to dashboard section format."""
    section = {
        "section": result.variable.section,
        "title": result.variable.title,
        "variable": result.variable.name,
        "households": result.n_tax_units,  # Actually tax units
        "testCases": [],
        "summary": {
            "total": result.n_tax_units,
            "matches": 0,
            "matchRate": 0,
            "meanAbsoluteError": 0,
        },
    }

    # Add validator breakdown
    validator_breakdown = {}

    if result.pe_comparison:
        validator_breakdown["policyengine"] = comparison_to_breakdown(result.pe_comparison)
        section["summary"]["matches"] = result.pe_comparison.n_matches
        section["summary"]["matchRate"] = result.pe_comparison.match_rate
        section["summary"]["meanAbsoluteError"] = result.pe_comparison.mean_absolute_error

    if result.taxsim_comparison:
        validator_breakdown["taxsim"] = comparison_to_breakdown(result.taxsim_comparison)

    if validator_breakdown:
        section["validatorBreakdown"] = validator_breakdown

    # Add mismatches analysis
    mismatches = []
    if result.pe_comparison and result.pe_comparison.mismatches:
        n_mismatches = result.pe_comparison.n_compared - result.pe_comparison.n_matches
        if n_mismatches > 0:
            mismatches.append({
                "description": f"Cosilico differs from PolicyEngine",
                "count": n_mismatches,
                "explanation": f"Cases where Cosilico and PE differ by more than ${result.variable.tolerance:.0f}",
                "citation": f"See {result.variable.section}",
            })

    if result.taxsim_comparison and result.taxsim_comparison.mismatches:
        n_mismatches = result.taxsim_comparison.n_compared - result.taxsim_comparison.n_matches
        if n_mismatches > 0:
            mismatches.append({
                "description": f"Cosilico differs from TAXSIM",
                "count": n_mismatches,
                "explanation": f"Cases where Cosilico and TAXSIM differ by more than ${result.variable.tolerance:.0f}",
                "citation": f"See {result.variable.section}",
            })

    if mismatches:
        section["mismatches"] = mismatches

    return section


def export_dashboard_json(
    results: Dict[str, ValidationResult],
    output_path: Path,
    data_source: str = "Enhanced CPS",
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
    total_tax_units = max(r.n_tax_units for r in results.values()) if results else 0

    # Count matches across all comparisons
    total_comparisons = 0
    total_matches = 0
    total_mae = 0
    mae_count = 0

    for r in results.values():
        if r.pe_comparison:
            total_comparisons += r.pe_comparison.n_compared
            total_matches += r.pe_comparison.n_matches
            total_mae += r.pe_comparison.mean_absolute_error
            mae_count += 1

    # Build sections
    sections = [result_to_section(r) for r in results.values()]

    # Determine validator availability
    has_taxsim = any(r.taxsim_comparison for r in results.values())
    has_pe = any(r.pe_comparison for r in results.values())

    validators = [
        {
            "name": "cosilico",
            "available": True,
            "version": get_cosilico_version(),
            "householdsCovered": total_tax_units,
        },
        {
            "name": "policyengine",
            "available": has_pe,
            "version": get_policyengine_version(),
            "householdsCovered": total_tax_units if has_pe else 0,
        },
        {
            "name": "taxsim",
            "available": has_taxsim,
            "version": "35",
            "householdsCovered": total_tax_units if has_taxsim else 0,
        },
    ]

    report = {
        "isSampleData": False,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "commit": get_git_commit(),
        "dataSource": f"{data_source} {year}",
        "householdsTotal": total_tax_units,
        "sections": sections,
        "overall": {
            "totalHouseholds": total_tax_units,
            "totalTests": total_comparisons,
            "totalMatches": total_matches,
            "matchRate": total_matches / total_comparisons if total_comparisons > 0 else 0,
            "meanAbsoluteError": total_mae / mae_count if mae_count > 0 else 0,
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

    parser = argparse.ArgumentParser(
        description="Run CPS validation comparing Cosilico against PE and TAXSIM"
    )
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

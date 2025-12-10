"""CLI for cosilico-validators."""

import json
import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from cosilico_validators.validators.base import TestCase
from cosilico_validators.consensus.engine import ConsensusEngine, ConsensusLevel


console = Console()


def load_validators(include_policyengine: bool = True, include_taxsim: bool = True):
    """Load available validators."""
    validators = []

    if include_taxsim:
        from cosilico_validators.validators.taxsim import TaxsimValidator
        validators.append(TaxsimValidator())

    if include_policyengine:
        try:
            from cosilico_validators.validators.policyengine import PolicyEngineValidator
            validators.append(PolicyEngineValidator())
        except ImportError:
            console.print("[yellow]PolicyEngine not installed, skipping[/yellow]")

    return validators


@click.group()
def cli():
    """Multi-system tax/benefit validation for Cosilico DSL encodings."""
    pass


@cli.command()
@click.argument("test_file", type=click.Path(exists=True))
@click.option("--variable", "-v", required=True, help="Variable to validate (e.g., eitc, ctc)")
@click.option("--year", "-y", default=2024, help="Tax year")
@click.option("--tolerance", "-t", default=15.0, help="Dollar tolerance for matching")
@click.option("--no-policyengine", is_flag=True, help="Skip PolicyEngine validator")
@click.option("--no-taxsim", is_flag=True, help="Skip TAXSIM validator")
@click.option("--claude-confidence", type=float, help="Claude's confidence in expected value (0-1)")
@click.option("--output", "-o", type=click.Path(), help="Output file for results (JSON)")
def validate(test_file, variable, year, tolerance, no_policyengine, no_taxsim, claude_confidence, output):
    """Validate test cases against multiple systems."""
    # Load test cases
    test_path = Path(test_file)
    if test_path.suffix == ".json":
        with open(test_path) as f:
            test_data = json.load(f)
    elif test_path.suffix in [".yaml", ".yml"]:
        import yaml
        with open(test_path) as f:
            test_data = yaml.safe_load(f)
    else:
        raise click.ClickException(f"Unsupported file format: {test_path.suffix}")

    # Convert to TestCase objects
    test_cases = []
    if isinstance(test_data, list):
        for tc in test_data:
            test_cases.append(TestCase(
                name=tc.get("name", "unnamed"),
                inputs=tc.get("inputs", {}),
                expected=tc.get("expected", {}),
                citation=tc.get("citation"),
                notes=tc.get("notes"),
            ))
    elif isinstance(test_data, dict) and "test_cases" in test_data:
        for tc in test_data["test_cases"]:
            test_cases.append(TestCase(
                name=tc.get("name", "unnamed"),
                inputs=tc.get("inputs", {}),
                expected=tc.get("expected", {}),
                citation=tc.get("citation"),
                notes=tc.get("notes"),
            ))

    if not test_cases:
        raise click.ClickException("No test cases found in file")

    # Load validators
    validators = load_validators(
        include_policyengine=not no_policyengine,
        include_taxsim=not no_taxsim,
    )

    if not validators:
        raise click.ClickException("No validators available")

    # Create consensus engine
    engine = ConsensusEngine(validators, tolerance=tolerance)

    # Run validation
    results = []
    for tc in test_cases:
        result = engine.validate(tc, variable, year, claude_confidence)
        results.append(result)

    # Display results
    display_results(results)

    # Save output if requested
    if output:
        output_data = []
        for r in results:
            output_data.append({
                "test_case": r.test_case.name,
                "variable": r.variable,
                "expected": r.expected_value,
                "consensus_value": r.consensus_value,
                "consensus_level": r.consensus_level.value,
                "reward_signal": r.reward_signal,
                "confidence": r.confidence,
                "matches_expected": r.matches_expected,
                "validator_results": {
                    name: {
                        "calculated": vr.calculated_value,
                        "error": vr.error,
                        "success": vr.success,
                    }
                    for name, vr in r.validator_results.items()
                },
                "potential_bugs": r.potential_bugs,
            })

        with open(output, "w") as f:
            json.dump(output_data, f, indent=2)
        console.print(f"\n[green]Results saved to {output}[/green]")

    # Summary statistics
    display_summary(results)


def display_results(results):
    """Display validation results in a table."""
    table = Table(title="Validation Results")
    table.add_column("Test Case", style="cyan")
    table.add_column("Expected", justify="right")
    table.add_column("Consensus", justify="right")
    table.add_column("Level", style="magenta")
    table.add_column("Reward", justify="right")
    table.add_column("Match", justify="center")

    level_colors = {
        ConsensusLevel.FULL_AGREEMENT: "green",
        ConsensusLevel.PRIMARY_CONFIRMED: "green",
        ConsensusLevel.MAJORITY_AGREEMENT: "yellow",
        ConsensusLevel.DISAGREEMENT: "red",
        ConsensusLevel.POTENTIAL_UPSTREAM_BUG: "blue",
    }

    for r in results:
        consensus_str = f"${r.consensus_value:,.0f}" if r.consensus_value else "N/A"
        level_color = level_colors.get(r.consensus_level, "white")
        match_str = "✓" if r.matches_expected else "✗"
        match_color = "green" if r.matches_expected else "red"

        table.add_row(
            r.test_case.name[:30],
            f"${r.expected_value:,.0f}",
            consensus_str,
            f"[{level_color}]{r.consensus_level.value}[/{level_color}]",
            f"{r.reward_signal:+.2f}",
            f"[{match_color}]{match_str}[/{match_color}]",
        )

    console.print(table)

    # Show potential bugs
    all_bugs = []
    for r in results:
        all_bugs.extend(r.potential_bugs)

    if all_bugs:
        console.print("\n")
        bug_panel = Panel(
            "\n".join([
                f"• {bug['validator']}: expected ${bug['expected']:,.0f}, got ${bug['actual']:,.0f} "
                f"(diff: ${bug['difference']:,.0f})"
                for bug in all_bugs
            ]),
            title="[bold red]Potential Upstream Bugs Detected[/bold red]",
            border_style="red",
        )
        console.print(bug_panel)


def display_summary(results):
    """Display summary statistics."""
    total = len(results)
    matches = sum(1 for r in results if r.matches_expected)
    avg_reward = sum(r.reward_signal for r in results) / total if total else 0
    avg_confidence = sum(r.confidence for r in results) / total if total else 0

    level_counts = {}
    for r in results:
        level_counts[r.consensus_level.value] = level_counts.get(r.consensus_level.value, 0) + 1

    console.print("\n")
    summary = f"""[bold]Summary[/bold]
Total tests: {total}
Matches: {matches}/{total} ({matches/total*100:.1f}%)
Average reward: {avg_reward:+.3f}
Average confidence: {avg_confidence:.1%}

Consensus levels:
"""
    for level, count in sorted(level_counts.items()):
        summary += f"  {level}: {count}\n"

    console.print(Panel(summary, border_style="blue"))


@cli.command()
@click.option("--variable", "-v", help="Variable to check")
def validators(variable):
    """List available validators and their supported variables."""
    validators = load_validators()

    table = Table(title="Available Validators")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Variables")

    for v in validators:
        vars_list = sorted(v.supported_variables) if hasattr(v, "supported_variables") else ["(dynamic)"]
        if variable:
            supports = v.supports_variable(variable)
            vars_str = f"[green]✓ Supports {variable}[/green]" if supports else f"[red]✗ No {variable}[/red]"
        else:
            vars_str = ", ".join(vars_list[:5])
            if len(vars_list) > 5:
                vars_str += f" (+{len(vars_list)-5} more)"

        table.add_row(v.name, v.validator_type.value, vars_str)

    console.print(table)


@cli.command()
@click.argument("results_file", type=click.Path(exists=True))
@click.option("--repo", "-r", help="Target repo for issues (e.g., PolicyEngine/policyengine-us)")
@click.option("--dry-run", is_flag=True, help="Show what would be filed without creating issues")
def file_issues(results_file, repo, dry_run):
    """File GitHub issues for potential upstream bugs."""
    with open(results_file) as f:
        results = json.load(f)

    bugs = []
    for r in results:
        bugs.extend(r.get("potential_bugs", []))

    if not bugs:
        console.print("[green]No potential bugs to file![/green]")
        return

    console.print(f"[bold]Found {len(bugs)} potential bugs[/bold]\n")

    for bug in bugs:
        title = f"Potential calculation error in {bug['test_case']}"
        body = f"""## Bug Report (Auto-generated)

**Test Case:** {bug['test_case']}
**Variable:** Calculated value mismatch

### Expected vs Actual
- **Expected (from statute):** ${bug['expected']:,.2f}
- **Calculated:** ${bug['actual']:,.2f}
- **Difference:** ${bug['difference']:,.2f}

### Citation
{bug.get('citation', 'N/A')}

### Test Inputs
```json
{json.dumps(bug.get('inputs', {}), indent=2)}
```

### Confidence
Claude encoding confidence: {bug.get('claude_confidence', 'N/A')}

---
*This issue was automatically generated by cosilico-validators based on multi-system consensus analysis.*
"""
        console.print(Panel(
            f"[bold]{title}[/bold]\n\n{body[:500]}...",
            title=f"Issue for {bug['validator']}",
            border_style="yellow" if dry_run else "green",
        ))

        if not dry_run and repo:
            # TODO: Actually file the issue using GitHub API
            console.print(f"[yellow]Would file to {repo} (not implemented yet)[/yellow]")

    if dry_run:
        console.print("\n[yellow]Dry run - no issues were filed[/yellow]")


if __name__ == "__main__":
    cli()

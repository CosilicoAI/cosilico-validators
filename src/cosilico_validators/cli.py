"""CLI for cosilico-validators."""

import json
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cosilico_validators.consensus.engine import ConsensusEngine, ConsensusLevel
from cosilico_validators.validators.base import TestCase

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


@cli.command("validate-encoding")
@click.argument("cosilico_file", type=click.Path(exists=True))
@click.option("--variable", "-v", help="Variable name to validate (auto-detected from file if not specified)")
@click.option("--year", "-y", default=2024, type=int, help="Tax year for validation")
@click.option("--output", "-o", type=click.Path(), help="Output file for JSON results")
@click.option("--no-policyengine", is_flag=True, help="Skip PolicyEngine validation")
@click.option("--plugin-version", default="v0.1.0", help="Plugin version for tracking")
@click.option("--json-output", is_flag=True, help="Output only JSON (for machine parsing)")
def validate_encoding(cosilico_file, variable, year, output, no_policyengine, plugin_version, json_output):
    """Validate a .cosilico encoding against PolicyEngine.

    Takes a .cosilico file path and runs the full encoding -> validation -> diagnosis loop.
    Looks for tests.yaml in the same directory as the .cosilico file.

    Examples:

        cosilico-validators validate-encoding statute/26/32/a/1/earned_income_credit.cosilico

        cosilico-validators validate-encoding path/to/agi.cosilico -v adjusted_gross_income --output results.json
    """
    import yaml
    from dataclasses import asdict

    cosilico_path = Path(cosilico_file)

    # Find tests.yaml in the same directory or parent directories
    tests_yaml = None
    search_dir = cosilico_path.parent
    for _ in range(5):  # Search up to 5 levels
        candidate = search_dir / "tests.yaml"
        if candidate.exists():
            tests_yaml = candidate
            break
        search_dir = search_dir.parent

    if tests_yaml is None:
        if json_output:
            result = {"error": f"No tests.yaml found near {cosilico_file}"}
            console.print_json(data=result)
        else:
            raise click.ClickException(f"No tests.yaml found near {cosilico_file}")
        return

    # Load tests.yaml
    with open(tests_yaml) as f:
        test_data = yaml.safe_load(f)

    # Extract variable name if not specified
    if not variable:
        variable = test_data.get("variable")
        if not variable:
            # Try to infer from filename
            variable = cosilico_path.stem
        if not variable:
            if json_output:
                result = {"error": "Could not determine variable name. Use --variable option."}
                console.print_json(data=result)
            else:
                raise click.ClickException("Could not determine variable name. Use --variable option.")
            return

    # Extract test cases (support both "test_cases" and "tests" keys)
    test_cases = test_data.get("test_cases", test_data.get("tests", []))
    if not test_cases:
        if json_output:
            result = {"error": "No test_cases or tests found in tests.yaml"}
            console.print_json(data=result)
        else:
            raise click.ClickException("No test_cases or tests found in tests.yaml")
        return

    # Derive statute reference from path
    statute_ref = _derive_statute_ref(cosilico_path)

    if not json_output:
        console.print(f"\n[bold cyan]Validating:[/bold cyan] {variable}")
        console.print(f"[dim]Statute:[/dim] {statute_ref}")
        console.print(f"[dim]Tests:[/dim] {len(test_cases)} test cases from {tests_yaml}")
        console.print(f"[dim]Year:[/dim] {year}")
        console.print()

    # Run validation
    if no_policyengine:
        # Minimal validation without PE
        result = {
            "variable": variable,
            "statute_ref": statute_ref,
            "plugin_version": plugin_version,
            "test_count": len(test_cases),
            "match_rate": None,
            "passed": None,
            "status": "skipped",
            "message": "PolicyEngine validation skipped (--no-policyengine)",
        }
    else:
        try:
            from cosilico_validators.encoding_orchestrator import EncodingOrchestrator

            orchestrator = EncodingOrchestrator(plugin_version=plugin_version)
            session = orchestrator.encode_and_validate(
                variable=variable,
                statute_ref=statute_ref,
                test_cases=test_cases,
                year=year,
            )

            result = _session_to_dict(session)

            # Add farness forecast tracking info if diagnosis suggests improvement
            if session.diagnosis and session.improvement_decision_id:
                result["farness_tracking"] = {
                    "decision_id": session.improvement_decision_id,
                    "layer": session.diagnosis.layer.value,
                    "suggested_fix": session.diagnosis.suggested_fix,
                    "forecast_logged": True,
                }

        except ImportError as e:
            result = {
                "variable": variable,
                "error": f"Failed to import validation components: {e}",
                "status": "error",
            }
        except Exception as e:
            result = {
                "variable": variable,
                "error": str(e),
                "status": "error",
            }

    # Output results
    if json_output:
        console.print_json(data=result)
    else:
        _display_encoding_result(result)

    # Save to file if requested
    if output:
        with open(output, "w") as f:
            json.dump(result, f, indent=2)
        if not json_output:
            console.print(f"\n[green]Results saved to {output}[/green]")


def _derive_statute_ref(cosilico_path: Path) -> str:
    """Derive statute reference from file path.

    E.g., statute/26/32/a/1/earned_income_credit.cosilico -> "26 USC 32(a)(1)"
    """
    parts = cosilico_path.parts
    try:
        # Find 'statute' in path
        statute_idx = parts.index("statute")
        remaining = parts[statute_idx + 1:-1]  # Exclude filename

        if len(remaining) >= 2:
            title = remaining[0]
            section = remaining[1]

            # Build subsections
            subsections = ""
            for part in remaining[2:]:
                if part.isdigit():
                    subsections += f"({part})"
                else:
                    subsections += f"({part})"

            return f"{title} USC {section}{subsections}"
    except ValueError:
        pass

    return f"Unknown ({cosilico_path.name})"


def _session_to_dict(session) -> dict:
    """Convert EncodingSession to a JSON-serializable dict."""
    result = {
        "variable": session.variable,
        "statute_ref": session.statute_ref,
        "plugin_version": session.plugin_version,
        "timestamp": session.timestamp,
        "test_count": len(session.test_cases),
    }

    if session.validation_result:
        result.update({
            "match_rate": session.validation_result.match_rate,
            "passed": session.validation_result.passed,
            "status": session.validation_result.status.value,
            "reward_signal": session.validation_result.reward_signal,
            "issues": session.validation_result.issues,
            "upstream_bugs": session.validation_result.upstream_bugs,
        })
    else:
        result["status"] = "no_result"

    if session.diagnosis:
        result["diagnosis"] = {
            "layer": session.diagnosis.layer.value,
            "confidence": session.diagnosis.confidence,
            "explanation": session.diagnosis.explanation,
            "suggested_fix": session.diagnosis.suggested_fix,
            "evidence": session.diagnosis.evidence if hasattr(session.diagnosis, "evidence") else [],
        }

    if session.improvement_decision_id:
        result["improvement_decision_id"] = session.improvement_decision_id

    return result


def _display_encoding_result(result: dict):
    """Display encoding validation result in a nice format."""
    status = result.get("status", "unknown")
    passed = result.get("passed")
    match_rate = result.get("match_rate")

    # Status header
    if status == "passed" or passed:
        status_str = "[bold green]PASSED[/bold green]"
    elif status == "error":
        status_str = "[bold red]ERROR[/bold red]"
    elif status == "skipped":
        status_str = "[bold yellow]SKIPPED[/bold yellow]"
    else:
        status_str = "[bold red]FAILED[/bold red]"

    console.print(Panel(
        f"Variable: [cyan]{result.get('variable', 'unknown')}[/cyan]\n"
        f"Status: {status_str}\n"
        f"Match Rate: {f'{match_rate:.1%}' if match_rate is not None else 'N/A'}\n"
        f"Test Count: {result.get('test_count', 0)}",
        title="[bold]Validation Result[/bold]",
        border_style="green" if passed else "red" if status == "error" else "yellow",
    ))

    # Show diagnosis if present
    if "diagnosis" in result:
        diag = result["diagnosis"]
        console.print(Panel(
            f"Layer: [magenta]{diag.get('layer', 'unknown')}[/magenta]\n"
            f"Confidence: {diag.get('confidence', 0):.0%}\n"
            f"Explanation: {diag.get('explanation', 'N/A')}\n"
            f"Suggested Fix: [yellow]{diag.get('suggested_fix', 'N/A')}[/yellow]",
            title="[bold]Diagnosis[/bold]",
            border_style="yellow",
        ))

    # Show farness tracking if present
    if "farness_tracking" in result:
        ft = result["farness_tracking"]
        console.print(Panel(
            f"Decision ID: [cyan]{ft.get('decision_id', 'N/A')}[/cyan]\n"
            f"Forecast Logged: {'Yes' if ft.get('forecast_logged') else 'No'}",
            title="[bold]Farness Tracking[/bold]",
            border_style="blue",
        ))

    # Show error if present
    if "error" in result:
        console.print(Panel(
            f"[red]{result['error']}[/red]",
            title="[bold red]Error[/bold red]",
            border_style="red",
        ))


@cli.command("record-outcome")
@click.argument("decision_id")
@click.option("--match-rate", "-m", type=float, required=True, help="Actual match rate achieved (0-1)")
@click.option("--reflections", "-r", default="", help="Reflections on why actuals differed from forecast")
@click.option("--json-output", is_flag=True, help="Output only JSON (for machine parsing)")
def record_outcome(decision_id, match_rate, reflections, json_output):
    """Record actual outcome for a forecasted improvement decision.

    This closes the farness calibration loop by recording what actually happened
    after applying a suggested fix. The system uses this to calibrate future
    forecasts.

    Examples:

        cosilico-validators record-outcome abc123 --match-rate 0.95

        cosilico-validators record-outcome abc123 -m 0.85 -r "Phase-out was more complex than expected"
    """
    from cosilico_validators.improvement_decisions import get_decision_log

    log = get_decision_log()

    # Convert match rate to percentage points for consistency with forecasts
    actual_outcomes = {"match_rate": match_rate * 100 if match_rate <= 1 else match_rate}

    try:
        calibration = log.record_outcome(
            decision_id=decision_id,
            actual_outcomes=actual_outcomes,
            reflections=reflections,
        )

        if json_output:
            console.print_json(data=calibration)
        else:
            if "error" in calibration:
                console.print(Panel(
                    f"[red]{calibration['error']}[/red]",
                    title="[bold red]Error[/bold red]",
                    border_style="red",
                ))
            else:
                # Display calibration result
                kpi_results = []
                for kpi_name, kpi_data in calibration.get("kpis", {}).items():
                    in_interval = kpi_data.get("in_interval", False)
                    status = "[green]IN CI[/green]" if in_interval else "[red]OUTSIDE CI[/red]"
                    kpi_results.append(
                        f"{kpi_name}: predicted {kpi_data.get('predicted', 'N/A'):.1f}pp, "
                        f"actual {kpi_data.get('actual', 'N/A'):.1f}pp {status}"
                    )

                console.print(Panel(
                    f"Decision: [cyan]{decision_id}[/cyan]\n"
                    f"Option: {calibration.get('option', 'N/A')}\n\n"
                    f"Results:\n" + "\n".join(kpi_results) + "\n\n"
                    f"Coverage: {calibration.get('coverage', 0):.0%}\n"
                    f"Mean Error: {calibration.get('overall_error', 0):.1f}pp",
                    title="[bold]Outcome Recorded[/bold]",
                    border_style="green" if calibration.get("overall_in_interval") else "yellow",
                ))

    except Exception as e:
        if json_output:
            console.print_json(data={"error": str(e)})
        else:
            console.print(Panel(
                f"[red]{str(e)}[/red]",
                title="[bold red]Error[/bold red]",
                border_style="red",
            ))


@cli.command("calibration-summary")
@click.option("--json-output", is_flag=True, help="Output only JSON (for machine parsing)")
def calibration_summary(json_output):
    """Show calibration summary for improvement forecasts.

    Displays how well past forecasts have matched actual outcomes,
    helping identify if the system is overconfident or underconfident.
    """
    from cosilico_validators.improvement_decisions import get_decision_log

    log = get_decision_log()
    summary = log.get_calibration_summary()

    if json_output:
        console.print_json(data=summary)
    else:
        coverage = summary.get('coverage')
        coverage_str = f"{coverage:.0%}" if coverage is not None else "N/A"
        cal_error = summary.get('calibration_error')
        cal_error_str = f"{cal_error:+.1%}" if cal_error is not None else "N/A"
        mae = summary.get('mean_absolute_error')
        mae_str = f"{mae:.1f}pp" if mae is not None else "N/A"

        console.print(Panel(
            f"Total Decisions: {summary.get('n_decisions', 0)}\n"
            f"Expected Coverage: {summary.get('expected_coverage', 0.8):.0%}\n"
            f"Actual Coverage: {coverage_str}\n"
            f"Calibration Error: {cal_error_str}\n"
            f"Mean Absolute Error: {mae_str}\n\n"
            f"[dim]{summary.get('interpretation', 'No forecasts scored yet')}[/dim]",
            title="[bold]Calibration Summary[/bold]",
            border_style="blue",
        ))


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

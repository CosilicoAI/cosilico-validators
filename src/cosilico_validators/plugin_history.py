"""Plugin History Tools - MCP-style queryable tools for encoding history.

These tools allow Claude to query relevant parts of the encoding history
without loading the entire context. Supports:
- Recent failures lookup
- Similar failure search
- Suggestion outcome tracking
- Calibration metrics
- Plugin version diffs
"""

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


RESULTS_DIR = Path(__file__).parent.parent.parent.parent / "results"


@dataclass
class FailureSummary:
    """Summary of an encoding failure."""

    variable: str
    timestamp: str
    match_rate: float
    error_type: str  # "encoding_error", "validator_disagreement", "missing_input", etc.
    root_cause: Optional[str]  # Diagnosed root cause
    layer: str  # "plugin", "dsl_core", "parameters", "test_case", "validator", "variable_schema"
    plugin_version: str
    test_cases_failed: int
    test_cases_total: int
    details: dict = field(default_factory=dict)


@dataclass
class SuggestionOutcome:
    """Outcome of a plugin improvement suggestion."""

    suggestion_id: str
    timestamp: str
    suggestion_type: str  # "prompt_refinement", "subagent_update", "error_handling", etc.
    description: str
    predicted_improvement: float  # Forecasted match rate improvement
    predicted_ci: tuple[float, float]  # 80% confidence interval
    actual_improvement: Optional[float]  # After validation
    variables_tested: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)  # Variables that got worse


@dataclass
class CalibrationSummary:
    """Summary of forecast calibration."""

    n_forecasts: int
    coverage: float  # Fraction of actuals in predicted CIs
    expected_coverage: float  # What we stated (e.g., 0.80)
    calibration_error: float  # coverage - expected (negative = overconfident)
    mean_absolute_error: float
    by_suggestion_type: dict = field(default_factory=dict)


@dataclass
class HistoryMatch:
    """A match from searching history."""

    timestamp: str
    type: str  # "failure", "suggestion", "validation"
    relevance_score: float
    summary: str
    details: dict = field(default_factory=dict)


class PluginHistoryTools:
    """MCP-style tools for querying encoding history.

    These tools allow Claude to explore the relevant parts of history
    when diagnosing failures or suggesting improvements.
    """

    def __init__(self, results_dir: Optional[Path] = None):
        self.results_dir = results_dir or RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Log files
        self.failures_log = self.results_dir / "failures.jsonl"
        self.suggestions_log = self.results_dir / "suggestions.jsonl"
        self.calibration_log = self.results_dir / "calibration.jsonl"

    # -------------------------------------------------------------------------
    # Query Tools (MCP-style interface)
    # -------------------------------------------------------------------------

    def get_recent_failures(self, n: int = 10, variable: Optional[str] = None) -> list[FailureSummary]:
        """Get the n most recent failures.

        Args:
            n: Number of failures to return
            variable: Optional filter by variable name

        Returns:
            List of FailureSummary objects, most recent first
        """
        if not self.failures_log.exists():
            return []

        failures = []
        with open(self.failures_log) as f:
            for line in f:
                entry = json.loads(line)
                if variable and entry.get("variable") != variable:
                    continue
                failures.append(FailureSummary(**entry))

        # Sort by timestamp descending, take n
        failures.sort(key=lambda x: x.timestamp, reverse=True)
        return failures[:n]

    def get_similar_failures(self, variable: str, error_type: Optional[str] = None) -> list[FailureSummary]:
        """Find failures similar to a given variable's encoding.

        Similarity is based on:
        - Same or related variable (e.g., eitc_* variables)
        - Same error type
        - Same layer diagnosed

        Args:
            variable: Variable to find similar failures for
            error_type: Optional filter by error type

        Returns:
            List of similar failures, sorted by relevance
        """
        if not self.failures_log.exists():
            return []

        # Extract variable family (e.g., "eitc" from "eitc_phase_in_amount")
        var_parts = variable.lower().split("_")
        var_family = var_parts[0] if var_parts else variable.lower()

        similar = []
        with open(self.failures_log) as f:
            for line in f:
                entry = json.loads(line)
                entry_var = entry.get("variable", "").lower()

                # Skip exact match (we want similar, not same)
                if entry_var == variable.lower():
                    continue

                # Check family match
                if entry_var.startswith(var_family):
                    score = 0.8
                elif any(part in entry_var for part in var_parts[1:]):
                    score = 0.5
                else:
                    continue

                # Boost if same error type
                if error_type and entry.get("error_type") == error_type:
                    score += 0.2

                failure = FailureSummary(**entry)
                failure.details["relevance_score"] = score
                similar.append(failure)

        # Sort by relevance
        similar.sort(key=lambda x: x.details.get("relevance_score", 0), reverse=True)
        return similar[:10]

    def get_suggestion_outcomes(self, suggestion_type: Optional[str] = None) -> list[SuggestionOutcome]:
        """Get outcomes of past plugin improvement suggestions.

        Args:
            suggestion_type: Optional filter by type (e.g., "prompt_refinement")

        Returns:
            List of SuggestionOutcome objects
        """
        if not self.suggestions_log.exists():
            return []

        outcomes = []
        with open(self.suggestions_log) as f:
            for line in f:
                entry = json.loads(line)
                if suggestion_type and entry.get("suggestion_type") != suggestion_type:
                    continue
                # Convert tuple fields
                if "predicted_ci" in entry and isinstance(entry["predicted_ci"], list):
                    entry["predicted_ci"] = tuple(entry["predicted_ci"])
                outcomes.append(SuggestionOutcome(**entry))

        return outcomes

    def get_calibration(self, kpi: Optional[str] = None) -> CalibrationSummary:
        """Get calibration metrics for forecasted improvements.

        Shows how well Claude's predicted improvements match actual results.

        Args:
            kpi: Optional filter by KPI (e.g., "match_rate", "test_pass_rate")

        Returns:
            CalibrationSummary with coverage, error metrics, etc.
        """
        outcomes = self.get_suggestion_outcomes()

        if not outcomes:
            return CalibrationSummary(
                n_forecasts=0,
                coverage=0.0,
                expected_coverage=0.80,
                calibration_error=0.0,
                mean_absolute_error=0.0,
            )

        # Filter to suggestions with actual outcomes
        scored = [o for o in outcomes if o.actual_improvement is not None]

        if not scored:
            return CalibrationSummary(
                n_forecasts=0,
                coverage=0.0,
                expected_coverage=0.80,
                calibration_error=0.0,
                mean_absolute_error=0.0,
            )

        # Calculate coverage (actuals in predicted CIs)
        in_interval = sum(
            1 for o in scored
            if o.predicted_ci[0] <= o.actual_improvement <= o.predicted_ci[1]
        )
        coverage = in_interval / len(scored)

        # Calculate MAE
        mae = sum(abs(o.actual_improvement - o.predicted_improvement) for o in scored) / len(scored)

        # Group by suggestion type
        by_type: dict[str, dict] = {}
        for o in scored:
            if o.suggestion_type not in by_type:
                by_type[o.suggestion_type] = {"count": 0, "in_interval": 0, "total_error": 0}
            by_type[o.suggestion_type]["count"] += 1
            if o.predicted_ci[0] <= o.actual_improvement <= o.predicted_ci[1]:
                by_type[o.suggestion_type]["in_interval"] += 1
            by_type[o.suggestion_type]["total_error"] += abs(o.actual_improvement - o.predicted_improvement)

        # Convert to coverage rates
        by_type_summary = {
            k: {
                "coverage": v["in_interval"] / v["count"] if v["count"] > 0 else 0,
                "mae": v["total_error"] / v["count"] if v["count"] > 0 else 0,
                "count": v["count"],
            }
            for k, v in by_type.items()
        }

        return CalibrationSummary(
            n_forecasts=len(scored),
            coverage=coverage,
            expected_coverage=0.80,
            calibration_error=coverage - 0.80,
            mean_absolute_error=mae,
            by_suggestion_type=by_type_summary,
        )

    def get_plugin_diff(self, v1: str, v2: str) -> str:
        """Get diff between two plugin versions.

        Args:
            v1: First plugin version (git commit or tag)
            v2: Second plugin version

        Returns:
            Unified diff string
        """
        # This would integrate with git in the cosilico-claude repo
        # For now, return placeholder
        return f"# Diff between {v1} and {v2}\n# (Git integration pending)"

    def search_history(self, query: str, max_results: int = 10) -> list[HistoryMatch]:
        """Full-text search across all history.

        Args:
            query: Search terms (space-separated, OR logic)
            max_results: Maximum results to return

        Returns:
            List of HistoryMatch objects
        """
        terms = query.lower().split()
        matches = []

        # Search failures
        for failure in self.get_recent_failures(n=100):
            score = sum(
                1 for term in terms
                if term in failure.variable.lower()
                or term in failure.error_type.lower()
                or term in (failure.root_cause or "").lower()
            )
            if score > 0:
                matches.append(HistoryMatch(
                    timestamp=failure.timestamp,
                    type="failure",
                    relevance_score=score / len(terms),
                    summary=f"{failure.variable}: {failure.error_type} ({failure.layer})",
                    details=asdict(failure),
                ))

        # Search suggestions
        for suggestion in self.get_suggestion_outcomes():
            score = sum(
                1 for term in terms
                if term in suggestion.suggestion_type.lower()
                or term in suggestion.description.lower()
            )
            if score > 0:
                matches.append(HistoryMatch(
                    timestamp=suggestion.timestamp,
                    type="suggestion",
                    relevance_score=score / len(terms),
                    summary=f"{suggestion.suggestion_type}: {suggestion.description[:50]}...",
                    details=asdict(suggestion),
                ))

        # Sort by relevance, take top n
        matches.sort(key=lambda x: x.relevance_score, reverse=True)
        return matches[:max_results]

    # -------------------------------------------------------------------------
    # Logging Tools (for recording outcomes)
    # -------------------------------------------------------------------------

    def log_failure(
        self,
        variable: str,
        match_rate: float,
        error_type: str,
        layer: str,
        plugin_version: str,
        test_cases_failed: int,
        test_cases_total: int,
        root_cause: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> FailureSummary:
        """Log an encoding failure for future reference."""
        failure = FailureSummary(
            variable=variable,
            timestamp=datetime.utcnow().isoformat() + "Z",
            match_rate=match_rate,
            error_type=error_type,
            root_cause=root_cause,
            layer=layer,
            plugin_version=plugin_version,
            test_cases_failed=test_cases_failed,
            test_cases_total=test_cases_total,
            details=details or {},
        )

        with open(self.failures_log, "a") as f:
            f.write(json.dumps(asdict(failure)) + "\n")

        return failure

    def log_suggestion(
        self,
        suggestion_type: str,
        description: str,
        predicted_improvement: float,
        predicted_ci: tuple[float, float],
        plugin_version: str,
    ) -> SuggestionOutcome:
        """Log a plugin improvement suggestion with its forecast."""
        suggestion = SuggestionOutcome(
            suggestion_id=f"sug_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            timestamp=datetime.utcnow().isoformat() + "Z",
            suggestion_type=suggestion_type,
            description=description,
            predicted_improvement=predicted_improvement,
            predicted_ci=predicted_ci,
            actual_improvement=None,
        )

        with open(self.suggestions_log, "a") as f:
            # Convert tuple to list for JSON
            data = asdict(suggestion)
            data["predicted_ci"] = list(suggestion.predicted_ci)
            f.write(json.dumps(data) + "\n")

        return suggestion

    def record_suggestion_outcome(
        self,
        suggestion_id: str,
        actual_improvement: float,
        variables_tested: list[str],
        regressions: Optional[list[str]] = None,
    ) -> None:
        """Record the actual outcome of a suggestion after validation."""
        if not self.suggestions_log.exists():
            return

        # Read all suggestions
        suggestions = []
        with open(self.suggestions_log) as f:
            for line in f:
                suggestions.append(json.loads(line))

        # Update the matching suggestion
        for s in suggestions:
            if s.get("suggestion_id") == suggestion_id:
                s["actual_improvement"] = actual_improvement
                s["variables_tested"] = variables_tested
                s["regressions"] = regressions or []
                break

        # Write back
        with open(self.suggestions_log, "w") as f:
            for s in suggestions:
                f.write(json.dumps(s) + "\n")


# Global instance
_history_tools = None


def get_history_tools() -> PluginHistoryTools:
    """Get the global history tools instance."""
    global _history_tools
    if _history_tools is None:
        _history_tools = PluginHistoryTools()
    return _history_tools

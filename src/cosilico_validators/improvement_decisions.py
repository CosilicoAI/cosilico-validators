"""Improvement Decisions - Farness-style forecasted decisions for plugin changes.

Integrates with the Farness decision framework to:
1. Require forecasts before making plugin changes
2. Track actual outcomes to measure calibration
3. Learn which suggestion types Claude over/under-estimates

Every plugin improvement suggestion must include:
- Point estimate of impact (e.g., +5% match rate)
- Confidence interval (e.g., [+2%, +8%])
- Reasoning and assumptions
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


RESULTS_DIR = Path(__file__).parent.parent.parent.parent / "results"


@dataclass
class ImprovementKPI:
    """A measurable outcome for plugin improvements."""

    name: str
    description: str
    unit: str = "%"  # Usually percentage points
    target: Optional[float] = None
    weight: float = 1.0


# Standard KPIs for plugin improvements
STANDARD_KPIS = [
    ImprovementKPI(
        name="match_rate",
        description="Percentage of test cases achieving FULL_AGREEMENT",
        unit="%",
        target=99.0,
        weight=1.0,
    ),
    ImprovementKPI(
        name="encoding_success_rate",
        description="Percentage of variables that pass validation first try",
        unit="%",
        target=80.0,
        weight=0.5,
    ),
    ImprovementKPI(
        name="regression_rate",
        description="Percentage of previously-passing variables that fail",
        unit="%",
        target=0.0,
        weight=0.8,
    ),
]


@dataclass
class ImprovementForecast:
    """A forecast about the impact of a plugin change."""

    kpi_name: str
    point_estimate: float  # Expected change (e.g., +5.0 percentage points)
    confidence_interval: tuple[float, float]  # (low, high)
    confidence_level: float = 0.80  # 80% CI by default
    reasoning: str = ""
    assumptions: list[str] = field(default_factory=list)
    base_rate: Optional[float] = None  # Historical rate for similar changes
    base_rate_source: Optional[str] = None


@dataclass
class ImprovementOption:
    """A possible plugin improvement action."""

    name: str
    description: str
    layer: str  # "plugin", "dsl_core", "parameters", etc.
    effort_level: str  # "trivial", "small", "medium", "large"
    forecasts: dict[str, ImprovementForecast] = field(default_factory=dict)

    def expected_value(self, kpis: list[ImprovementKPI]) -> float:
        """Weighted expected value across KPIs."""
        total_weight = sum(k.weight for k in kpis if k.name in self.forecasts)
        if total_weight == 0:
            return 0.0
        return sum(
            k.weight * self.forecasts[k.name].point_estimate
            for k in kpis
            if k.name in self.forecasts
        ) / total_weight


@dataclass
class ImprovementDecision:
    """A decision about which plugin improvement to make."""

    id: str = field(default_factory=lambda: str(uuid4())[:8])
    question: str = ""  # What improvement should we make?
    context: str = ""  # Why are we considering changes?

    kpis: list[ImprovementKPI] = field(default_factory=list)
    options: list[ImprovementOption] = field(default_factory=list)

    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    decided_at: Optional[str] = None
    chosen_option: Optional[str] = None

    # For scoring later
    review_date: Optional[str] = None
    actual_outcomes: dict[str, float] = field(default_factory=dict)  # KPI name -> actual
    scored_at: Optional[str] = None
    reflections: str = ""

    def best_option(self) -> Optional[ImprovementOption]:
        """Return option with highest expected value."""
        if not self.options:
            return None
        return max(self.options, key=lambda o: o.expected_value(self.kpis))


class ImprovementDecisionLog:
    """Tracks plugin improvement decisions and their outcomes."""

    def __init__(self, results_dir: Optional[Path] = None):
        self.results_dir = results_dir or RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.decisions_file = self.results_dir / "improvement_decisions.jsonl"
        self.calibration_file = self.results_dir / "calibration_data.jsonl"

    def create_decision(
        self,
        question: str,
        context: str,
        options: list[ImprovementOption],
        kpis: Optional[list[ImprovementKPI]] = None,
    ) -> ImprovementDecision:
        """Create a new improvement decision.

        Args:
            question: What improvement decision are we making?
            context: Why are we considering this change?
            options: List of possible improvements with forecasts
            kpis: KPIs to evaluate (defaults to STANDARD_KPIS)

        Returns:
            Created ImprovementDecision
        """
        decision = ImprovementDecision(
            question=question,
            context=context,
            options=options,
            kpis=kpis or STANDARD_KPIS.copy(),
        )

        self._save_decision(decision)
        return decision

    def record_choice(
        self,
        decision_id: str,
        chosen_option: str,
    ) -> None:
        """Record which option was chosen.

        Args:
            decision_id: ID of the decision
            chosen_option: Name of the chosen option
        """
        decision = self._load_decision(decision_id)
        if decision:
            decision.chosen_option = chosen_option
            decision.decided_at = datetime.utcnow().isoformat() + "Z"
            self._save_decision(decision)

    def record_outcome(
        self,
        decision_id: str,
        actual_outcomes: dict[str, float],
        reflections: str = "",
    ) -> dict[str, Any]:
        """Record actual outcomes and compute calibration.

        Args:
            decision_id: ID of the decision
            actual_outcomes: Actual KPI changes {kpi_name: actual_change}
            reflections: Any reflections on why actuals differed from forecast

        Returns:
            Calibration summary for this decision
        """
        decision = self._load_decision(decision_id)
        if not decision:
            return {"error": f"Decision {decision_id} not found"}

        decision.actual_outcomes = actual_outcomes
        decision.scored_at = datetime.utcnow().isoformat() + "Z"
        decision.reflections = reflections
        self._save_decision(decision)

        # Compute calibration for the chosen option
        calibration = self._compute_calibration(decision)

        # Log calibration data
        self._log_calibration(decision, calibration)

        return calibration

    def _compute_calibration(self, decision: ImprovementDecision) -> dict[str, Any]:
        """Compute calibration metrics for a scored decision."""
        if not decision.chosen_option:
            return {"error": "No option chosen"}

        # Find the chosen option
        chosen = None
        for opt in decision.options:
            if opt.name == decision.chosen_option:
                chosen = opt
                break

        if not chosen:
            return {"error": "Chosen option not found"}

        calibration = {
            "decision_id": decision.id,
            "option": chosen.name,
            "kpis": {},
            "overall_in_interval": True,
            "overall_error": 0.0,
        }

        n_scored = 0
        n_in_interval = 0
        total_error = 0.0

        for kpi_name, actual in decision.actual_outcomes.items():
            if kpi_name not in chosen.forecasts:
                continue

            forecast = chosen.forecasts[kpi_name]
            predicted = forecast.point_estimate
            ci_low, ci_high = forecast.confidence_interval

            in_interval = ci_low <= actual <= ci_high
            error = abs(actual - predicted)

            calibration["kpis"][kpi_name] = {
                "predicted": predicted,
                "actual": actual,
                "ci": [ci_low, ci_high],
                "in_interval": in_interval,
                "error": error,
            }

            n_scored += 1
            if in_interval:
                n_in_interval += 1
            total_error += error

        calibration["overall_in_interval"] = n_in_interval == n_scored
        calibration["coverage"] = n_in_interval / n_scored if n_scored > 0 else 0
        calibration["overall_error"] = total_error / n_scored if n_scored > 0 else 0

        return calibration

    def get_calibration_summary(self) -> dict[str, Any]:
        """Get overall calibration summary across all scored decisions."""
        if not self.calibration_file.exists():
            return {
                "n_decisions": 0,
                "coverage": None,
                "expected_coverage": 0.80,
                "calibration_error": None,
                "mean_absolute_error": None,
            }

        entries = []
        with open(self.calibration_file) as f:
            for line in f:
                entries.append(json.loads(line))

        if not entries:
            return {
                "n_decisions": 0,
                "coverage": None,
                "expected_coverage": 0.80,
                "calibration_error": None,
                "mean_absolute_error": None,
            }

        # Aggregate
        total_in_interval = sum(1 for e in entries if e.get("overall_in_interval"))
        total_error = sum(e.get("overall_error", 0) for e in entries)

        coverage = total_in_interval / len(entries)

        return {
            "n_decisions": len(entries),
            "coverage": coverage,
            "expected_coverage": 0.80,
            "calibration_error": coverage - 0.80,
            "mean_absolute_error": total_error / len(entries),
            "interpretation": self._interpret_calibration(coverage),
        }

    def _interpret_calibration(self, coverage: float) -> str:
        """Human-readable interpretation of calibration."""
        cal_err = coverage - 0.80

        if abs(cal_err) < 0.05:
            return "Well-calibrated: actual coverage matches stated confidence."
        elif cal_err < -0.1:
            return f"Overconfident: only {coverage:.0%} of actuals in CIs (expected 80%)."
        elif cal_err < 0:
            return f"Slightly overconfident: {coverage:.0%} coverage vs 80% expected."
        elif cal_err > 0.1:
            return f"Underconfident: {coverage:.0%} of actuals in CIs (expected 80%)."
        else:
            return f"Slightly underconfident: {coverage:.0%} coverage vs 80% expected."

    def _save_decision(self, decision: ImprovementDecision) -> None:
        """Save decision to log file."""
        # Read existing decisions
        decisions = {}
        if self.decisions_file.exists():
            with open(self.decisions_file) as f:
                for line in f:
                    d = json.loads(line)
                    decisions[d["id"]] = d

        # Update/add this decision
        decisions[decision.id] = self._decision_to_dict(decision)

        # Write back
        with open(self.decisions_file, "w") as f:
            for d in decisions.values():
                f.write(json.dumps(d) + "\n")

    def _load_decision(self, decision_id: str) -> Optional[ImprovementDecision]:
        """Load a decision by ID."""
        if not self.decisions_file.exists():
            return None

        with open(self.decisions_file) as f:
            for line in f:
                d = json.loads(line)
                if d["id"] == decision_id:
                    return self._dict_to_decision(d)

        return None

    def _log_calibration(self, decision: ImprovementDecision, calibration: dict) -> None:
        """Log calibration data for later analysis."""
        entry = {
            "decision_id": decision.id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **calibration,
        }

        with open(self.calibration_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _decision_to_dict(self, decision: ImprovementDecision) -> dict:
        """Convert decision to dictionary for storage."""
        return {
            "id": decision.id,
            "question": decision.question,
            "context": decision.context,
            "kpis": [asdict(k) for k in decision.kpis],
            "options": [
                {
                    "name": o.name,
                    "description": o.description,
                    "layer": o.layer,
                    "effort_level": o.effort_level,
                    "forecasts": {
                        k: {
                            "kpi_name": f.kpi_name,
                            "point_estimate": f.point_estimate,
                            "confidence_interval": list(f.confidence_interval),
                            "confidence_level": f.confidence_level,
                            "reasoning": f.reasoning,
                            "assumptions": f.assumptions,
                            "base_rate": f.base_rate,
                            "base_rate_source": f.base_rate_source,
                        }
                        for k, f in o.forecasts.items()
                    }
                }
                for o in decision.options
            ],
            "created_at": decision.created_at,
            "decided_at": decision.decided_at,
            "chosen_option": decision.chosen_option,
            "review_date": decision.review_date,
            "actual_outcomes": decision.actual_outcomes,
            "scored_at": decision.scored_at,
            "reflections": decision.reflections,
        }

    def _dict_to_decision(self, data: dict) -> ImprovementDecision:
        """Convert dictionary to decision object."""
        decision = ImprovementDecision(
            id=data["id"],
            question=data["question"],
            context=data.get("context", ""),
            created_at=data["created_at"],
            decided_at=data.get("decided_at"),
            chosen_option=data.get("chosen_option"),
            review_date=data.get("review_date"),
            actual_outcomes=data.get("actual_outcomes", {}),
            scored_at=data.get("scored_at"),
            reflections=data.get("reflections", ""),
        )

        decision.kpis = [
            ImprovementKPI(**k) for k in data.get("kpis", [])
        ]

        decision.options = []
        for o in data.get("options", []):
            option = ImprovementOption(
                name=o["name"],
                description=o["description"],
                layer=o["layer"],
                effort_level=o["effort_level"],
            )
            for k, f in o.get("forecasts", {}).items():
                option.forecasts[k] = ImprovementForecast(
                    kpi_name=f["kpi_name"],
                    point_estimate=f["point_estimate"],
                    confidence_interval=tuple(f["confidence_interval"]),
                    confidence_level=f.get("confidence_level", 0.80),
                    reasoning=f.get("reasoning", ""),
                    assumptions=f.get("assumptions", []),
                    base_rate=f.get("base_rate"),
                    base_rate_source=f.get("base_rate_source"),
                )
            decision.options.append(option)

        return decision


# Convenience functions
_decision_log = None


def get_decision_log() -> ImprovementDecisionLog:
    """Get the global decision log instance."""
    global _decision_log
    if _decision_log is None:
        _decision_log = ImprovementDecisionLog()
    return _decision_log


def create_improvement_decision(
    question: str,
    context: str,
    options: list[dict],
) -> ImprovementDecision:
    """Create an improvement decision from simple dicts.

    Example:
        decision = create_improvement_decision(
            question="How should we improve EITC encoding?",
            context="Current match rate is 85%",
            options=[
                {
                    "name": "Add phase-out guidance",
                    "description": "Add specific instructions for phase-out calculations",
                    "layer": "plugin",
                    "effort": "small",
                    "forecasts": {
                        "match_rate": {
                            "point": 5.0,  # +5 percentage points
                            "ci": (2.0, 8.0),
                            "reasoning": "Phase-out is current weak point",
                        }
                    }
                }
            ]
        )
    """
    converted_options = []
    for opt in options:
        option = ImprovementOption(
            name=opt["name"],
            description=opt["description"],
            layer=opt.get("layer", "plugin"),
            effort_level=opt.get("effort", "medium"),
        )

        for kpi_name, forecast_data in opt.get("forecasts", {}).items():
            option.forecasts[kpi_name] = ImprovementForecast(
                kpi_name=kpi_name,
                point_estimate=forecast_data["point"],
                confidence_interval=tuple(forecast_data.get("ci", (0, 0))),
                reasoning=forecast_data.get("reasoning", ""),
            )

        converted_options.append(option)

    return get_decision_log().create_decision(
        question=question,
        context=context,
        options=converted_options,
    )

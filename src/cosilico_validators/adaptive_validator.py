"""Adaptive Validator - Thompson sampling for plugin selection and sample sizing.

Implements:
1. Multi-armed bandit (Thompson sampling) for selecting plugin versions
2. Adaptive sample sizing - declining fraction as confidence grows
3. Regression detection across plugin changes
"""

import json
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import numpy as np


RESULTS_DIR = Path(__file__).parent.parent.parent.parent / "results"


@dataclass
class PluginArm:
    """A plugin version in the multi-armed bandit."""

    version: str  # Git commit or tag
    successes: int = 0  # Number of successful encodings
    failures: int = 0  # Number of failed encodings
    total_match_rate: float = 0.0  # Cumulative match rate
    n_validations: int = 0  # Number of validations run
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    variables_tested: list[str] = field(default_factory=list)
    regressions_from: dict[str, list[str]] = field(default_factory=dict)  # version -> vars that regressed


@dataclass
class SamplePlan:
    """Plan for which variables to validate."""

    variables: list[str]
    sample_fraction: float
    confidence_level: float
    reason: str


@dataclass
class ValidationBatch:
    """Results from a batch of validations."""

    plugin_version: str
    timestamp: str
    variables: list[str]
    match_rates: dict[str, float]
    overall_match_rate: float
    regressions: list[str]  # Variables that got worse vs previous version


class AdaptiveValidator:
    """Adaptive validation with Thompson sampling for plugin selection.

    Uses a multi-armed bandit approach where each plugin version is an "arm".
    Thompson sampling balances exploration (trying new versions) with
    exploitation (using versions that work well).
    """

    def __init__(
        self,
        results_dir: Optional[Path] = None,
        exploration_bonus: float = 0.1,
        regression_threshold: float = 0.05,
    ):
        """Initialize adaptive validator.

        Args:
            results_dir: Directory for storing results
            exploration_bonus: Bonus for less-tested versions (0-1)
            regression_threshold: Match rate drop that counts as regression
        """
        self.results_dir = results_dir or RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.arms_file = self.results_dir / "plugin_arms.json"
        self.batches_file = self.results_dir / "validation_batches.jsonl"

        self.exploration_bonus = exploration_bonus
        self.regression_threshold = regression_threshold

        self.arms: dict[str, PluginArm] = self._load_arms()

    def _load_arms(self) -> dict[str, PluginArm]:
        """Load plugin arms from disk."""
        if not self.arms_file.exists():
            return {}

        with open(self.arms_file) as f:
            data = json.load(f)
            return {k: PluginArm(**v) for k, v in data.items()}

    def _save_arms(self) -> None:
        """Save plugin arms to disk."""
        data = {k: asdict(v) for k, v in self.arms.items()}
        with open(self.arms_file, "w") as f:
            json.dump(data, f, indent=2)

    # -------------------------------------------------------------------------
    # Thompson Sampling for Plugin Selection
    # -------------------------------------------------------------------------

    def register_plugin(self, version: str) -> PluginArm:
        """Register a new plugin version as an arm.

        Args:
            version: Git commit hash or tag for this plugin version

        Returns:
            The created PluginArm
        """
        if version not in self.arms:
            self.arms[version] = PluginArm(version=version)
            self._save_arms()

        return self.arms[version]

    def select_plugin(self, strategy: str = "thompson") -> str:
        """Select a plugin version using Thompson sampling.

        Args:
            strategy: Selection strategy
                - "thompson": Thompson sampling (balanced explore/exploit)
                - "greedy": Always pick best performing
                - "random": Random selection (pure exploration)
                - "newest": Pick most recently registered

        Returns:
            Selected plugin version string
        """
        if not self.arms:
            raise ValueError("No plugin versions registered. Call register_plugin first.")

        if len(self.arms) == 1:
            return list(self.arms.keys())[0]

        if strategy == "random":
            return random.choice(list(self.arms.keys()))

        if strategy == "newest":
            return max(self.arms.items(), key=lambda x: x[1].created_at)[0]

        if strategy == "greedy":
            return max(
                self.arms.items(),
                key=lambda x: x[1].total_match_rate / max(x[1].n_validations, 1)
            )[0]

        # Thompson sampling (default)
        samples = {}
        for version, arm in self.arms.items():
            # Beta distribution: Beta(successes + 1, failures + 1)
            # Add exploration bonus for less-tested arms
            exploration_boost = self.exploration_bonus * (10 / max(arm.n_validations, 1))

            sample = np.random.beta(
                arm.successes + 1 + exploration_boost,
                arm.failures + 1
            )
            samples[version] = sample

        return max(samples, key=samples.get)

    def record_validation(
        self,
        version: str,
        variable: str,
        match_rate: float,
        success: bool,
    ) -> None:
        """Record a validation result for a plugin version.

        Args:
            version: Plugin version used
            variable: Variable that was validated
            match_rate: Match rate achieved (0-1)
            success: Whether validation passed (FULL_AGREEMENT)
        """
        if version not in self.arms:
            self.register_plugin(version)

        arm = self.arms[version]
        arm.n_validations += 1
        arm.total_match_rate += match_rate

        if success:
            arm.successes += 1
        else:
            arm.failures += 1

        if variable not in arm.variables_tested:
            arm.variables_tested.append(variable)

        self._save_arms()

    def detect_regressions(
        self,
        new_version: str,
        old_version: str,
        new_results: dict[str, float],
        old_results: dict[str, float],
    ) -> list[str]:
        """Detect variables that regressed between plugin versions.

        Args:
            new_version: The new plugin version
            old_version: The previous plugin version
            new_results: Match rates for new version {variable: rate}
            old_results: Match rates for old version {variable: rate}

        Returns:
            List of variables that regressed (match rate dropped by threshold)
        """
        regressions = []

        for var in new_results:
            if var in old_results:
                old_rate = old_results[var]
                new_rate = new_results[var]

                if old_rate - new_rate > self.regression_threshold:
                    regressions.append(var)

        # Record regressions in the arm
        if regressions and new_version in self.arms:
            self.arms[new_version].regressions_from[old_version] = regressions
            self._save_arms()

        return regressions

    # -------------------------------------------------------------------------
    # Adaptive Sample Sizing
    # -------------------------------------------------------------------------

    def compute_sample_plan(
        self,
        all_variables: list[str],
        confidence_threshold: float = 0.95,
        min_sample_fraction: float = 0.05,
        max_sample_fraction: float = 1.0,
    ) -> SamplePlan:
        """Compute which variables to validate based on confidence.

        As the system gains confidence (more successful validations),
        we can validate a smaller sample. This balances thoroughness
        with efficiency.

        Args:
            all_variables: Full list of variables to potentially validate
            confidence_threshold: Confidence level to target
            min_sample_fraction: Minimum fraction to sample (e.g., 5%)
            max_sample_fraction: Maximum fraction to sample (e.g., 100%)

        Returns:
            SamplePlan with selected variables and reasoning
        """
        # Get best performing arm's statistics
        if not self.arms:
            # No history - validate everything
            return SamplePlan(
                variables=all_variables,
                sample_fraction=1.0,
                confidence_level=0.0,
                reason="No validation history - full validation required",
            )

        best_arm = max(self.arms.values(), key=lambda a: a.successes / max(a.n_validations, 1))
        total_validations = sum(a.n_validations for a in self.arms.values())

        # Calculate success rate across all arms
        total_successes = sum(a.successes for a in self.arms.values())
        overall_success_rate = total_successes / max(total_validations, 1)

        # Compute confidence using Wilson score interval
        # Higher confidence = can sample less
        if total_validations < 10:
            confidence = 0.0
            sample_fraction = 1.0
            reason = f"Only {total_validations} validations - need more data"
        else:
            z = 1.96  # 95% confidence
            n = total_validations
            p = overall_success_rate

            # Wilson score lower bound
            wilson_lower = (p + z*z/(2*n) - z * np.sqrt((p*(1-p) + z*z/(4*n))/n)) / (1 + z*z/n)

            confidence = wilson_lower

            # Map confidence to sample fraction (inverse relationship)
            # High confidence → low sample fraction
            if confidence > 0.95:
                sample_fraction = min_sample_fraction
                reason = f"High confidence ({confidence:.1%}) - minimal sampling"
            elif confidence > 0.90:
                sample_fraction = min_sample_fraction + (0.9 - min_sample_fraction) * (0.95 - confidence) / 0.05
                reason = f"Good confidence ({confidence:.1%}) - reduced sampling"
            elif confidence > 0.80:
                sample_fraction = 0.3 + 0.4 * (0.90 - confidence) / 0.10
                reason = f"Moderate confidence ({confidence:.1%}) - standard sampling"
            else:
                sample_fraction = max_sample_fraction
                reason = f"Low confidence ({confidence:.1%}) - full validation"

        # Clamp sample fraction
        sample_fraction = max(min_sample_fraction, min(max_sample_fraction, sample_fraction))

        # Select variables to sample
        n_to_sample = max(1, int(len(all_variables) * sample_fraction))

        # Prioritize variables that haven't been tested recently
        tested_vars = set()
        for arm in self.arms.values():
            tested_vars.update(arm.variables_tested)

        untested = [v for v in all_variables if v not in tested_vars]
        tested = [v for v in all_variables if v in tested_vars]

        # Sample: all untested + random from tested
        sample = untested[:n_to_sample]
        if len(sample) < n_to_sample:
            remaining = n_to_sample - len(sample)
            sample.extend(random.sample(tested, min(remaining, len(tested))))

        return SamplePlan(
            variables=sample,
            sample_fraction=sample_fraction,
            confidence_level=confidence,
            reason=reason,
        )

    # -------------------------------------------------------------------------
    # Batch Validation
    # -------------------------------------------------------------------------

    def log_batch(
        self,
        plugin_version: str,
        variables: list[str],
        match_rates: dict[str, float],
        previous_version: Optional[str] = None,
    ) -> ValidationBatch:
        """Log a batch of validation results.

        Args:
            plugin_version: Plugin version used
            variables: Variables validated
            match_rates: Match rate for each variable
            previous_version: Previous version for regression detection

        Returns:
            ValidationBatch summary
        """
        overall_rate = sum(match_rates.values()) / len(match_rates) if match_rates else 0.0

        # Detect regressions if we have a previous version
        regressions = []
        if previous_version and previous_version in self.arms:
            # Load previous batch results
            previous_rates = self._get_previous_rates(previous_version, variables)
            regressions = self.detect_regressions(
                plugin_version, previous_version, match_rates, previous_rates
            )

        batch = ValidationBatch(
            plugin_version=plugin_version,
            timestamp=datetime.utcnow().isoformat() + "Z",
            variables=variables,
            match_rates=match_rates,
            overall_match_rate=overall_rate,
            regressions=regressions,
        )

        # Log to file
        with open(self.batches_file, "a") as f:
            f.write(json.dumps(asdict(batch)) + "\n")

        # Update arm statistics
        for var, rate in match_rates.items():
            self.record_validation(plugin_version, var, rate, success=(rate >= 0.99))

        return batch

    def _get_previous_rates(self, version: str, variables: list[str]) -> dict[str, float]:
        """Get previous match rates for a version."""
        if not self.batches_file.exists():
            return {}

        rates = {}
        with open(self.batches_file) as f:
            for line in f:
                batch = json.loads(line)
                if batch.get("plugin_version") == version:
                    for var in variables:
                        if var in batch.get("match_rates", {}):
                            rates[var] = batch["match_rates"][var]

        return rates

    def get_statistics(self) -> dict[str, Any]:
        """Get overall validation statistics."""
        if not self.arms:
            return {"status": "no_data", "total_validations": 0}

        total_validations = sum(a.n_validations for a in self.arms.values())
        total_successes = sum(a.successes for a in self.arms.values())
        unique_variables = set()
        for arm in self.arms.values():
            unique_variables.update(arm.variables_tested)

        best_arm = max(self.arms.values(), key=lambda a: a.successes / max(a.n_validations, 1))

        return {
            "status": "active",
            "total_validations": total_validations,
            "total_successes": total_successes,
            "overall_success_rate": total_successes / max(total_validations, 1),
            "unique_variables_tested": len(unique_variables),
            "plugin_versions": len(self.arms),
            "best_version": {
                "version": best_arm.version,
                "success_rate": best_arm.successes / max(best_arm.n_validations, 1),
                "n_validations": best_arm.n_validations,
            },
        }


# Global instance
_adaptive_validator = None


def get_adaptive_validator() -> AdaptiveValidator:
    """Get the global adaptive validator instance."""
    global _adaptive_validator
    if _adaptive_validator is None:
        _adaptive_validator = AdaptiveValidator()
    return _adaptive_validator

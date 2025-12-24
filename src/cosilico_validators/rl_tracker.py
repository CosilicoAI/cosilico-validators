"""RL Iteration Tracker - logs encoding attempts and validation results.

Tracks the progression from initial encoding to FULL_AGREEMENT for each variable.
Data is used for the pre-registered study on RL-guided tax code encoding.
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from .encoding_validator import EncodingValidationResult, ValidationStatus


RESULTS_DIR = Path(__file__).parent.parent.parent.parent / "results"


@dataclass
class EncodingAttempt:
    """Record of a single encoding attempt."""

    timestamp: str
    variable: str
    section: str  # e.g., "26 USC § 62"
    round: int
    prompt_hash: str  # Hash of the prompt used
    match_rate: float
    reward_signal: float
    status: str  # ValidationStatus value
    issues_count: int
    upstream_bugs_count: int
    test_cases_count: int
    duration_seconds: Optional[float] = None
    notes: Optional[str] = None


class RLTracker:
    """Tracks RL iterations for the encoding study."""

    def __init__(self, results_dir: Optional[Path] = None):
        self.results_dir = results_dir or RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.encoding_log = self.results_dir / "encoding_log.jsonl"
        self.validation_log = self.results_dir / "validation_results.jsonl"
        self.upstream_bugs_log = self.results_dir / "upstream_bugs.jsonl"
        self.summary_file = self.results_dir / "summary_stats.json"

    def log_attempt(
        self,
        variable: str,
        section: str,
        result: EncodingValidationResult,
        prompt: str,
        round_num: Optional[int] = None,
        duration_seconds: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> EncodingAttempt:
        """Log an encoding attempt."""

        # Auto-increment round if not specified
        if round_num is None:
            round_num = self._get_next_round(variable)

        attempt = EncodingAttempt(
            timestamp=datetime.utcnow().isoformat() + "Z",
            variable=variable,
            section=section,
            round=round_num,
            prompt_hash=hashlib.sha256(prompt.encode()).hexdigest()[:12],
            match_rate=result.match_rate,
            reward_signal=result.reward_signal,
            status=result.status.value,
            issues_count=len(result.issues),
            upstream_bugs_count=len(result.upstream_bugs),
            test_cases_count=len(result.consensus_results),
            duration_seconds=duration_seconds,
            notes=notes,
        )

        # Append to log
        with open(self.encoding_log, "a") as f:
            f.write(json.dumps(asdict(attempt)) + "\n")

        # Log any upstream bugs
        for bug in result.upstream_bugs:
            bug["logged_at"] = attempt.timestamp
            bug["encoding_round"] = round_num
            with open(self.upstream_bugs_log, "a") as f:
                f.write(json.dumps(bug) + "\n")

        # Update summary
        self._update_summary()

        return attempt

    def _get_next_round(self, variable: str) -> int:
        """Get the next round number for a variable."""
        if not self.encoding_log.exists():
            return 1

        max_round = 0
        with open(self.encoding_log) as f:
            for line in f:
                entry = json.loads(line)
                if entry["variable"] == variable:
                    max_round = max(max_round, entry["round"])

        return max_round + 1

    def get_variable_history(self, variable: str) -> List[EncodingAttempt]:
        """Get all attempts for a variable."""
        if not self.encoding_log.exists():
            return []

        history = []
        with open(self.encoding_log) as f:
            for line in f:
                entry = json.loads(line)
                if entry["variable"] == variable:
                    history.append(EncodingAttempt(**entry))

        return sorted(history, key=lambda x: x.round)

    def get_all_variables(self) -> Dict[str, Dict[str, Any]]:
        """Get summary for all variables."""
        if not self.encoding_log.exists():
            return {}

        variables = {}
        with open(self.encoding_log) as f:
            for line in f:
                entry = json.loads(line)
                var = entry["variable"]
                if var not in variables:
                    variables[var] = {
                        "section": entry["section"],
                        "total_rounds": 0,
                        "initial_match_rate": None,
                        "final_match_rate": None,
                        "final_status": None,
                        "achieved_parity": False,
                    }

                variables[var]["total_rounds"] = max(
                    variables[var]["total_rounds"], entry["round"]
                )

                if entry["round"] == 1:
                    variables[var]["initial_match_rate"] = entry["match_rate"]

                variables[var]["final_match_rate"] = entry["match_rate"]
                variables[var]["final_status"] = entry["status"]
                variables[var]["achieved_parity"] = entry["status"] == "passed"

        return variables

    def _update_summary(self) -> None:
        """Update summary statistics file."""
        variables = self.get_all_variables()

        if not variables:
            return

        total_vars = len(variables)
        achieved_parity = sum(1 for v in variables.values() if v["achieved_parity"])
        total_rounds = sum(v["total_rounds"] for v in variables.values())

        # Count upstream bugs
        upstream_bugs = 0
        if self.upstream_bugs_log.exists():
            with open(self.upstream_bugs_log) as f:
                upstream_bugs = sum(1 for _ in f)

        summary = {
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "total_variables": total_vars,
            "achieved_parity": achieved_parity,
            "parity_rate": achieved_parity / total_vars if total_vars > 0 else 0,
            "total_rounds": total_rounds,
            "average_rounds": total_rounds / total_vars if total_vars > 0 else 0,
            "upstream_bugs_found": upstream_bugs,
            "variables": variables,
        }

        with open(self.summary_file, "w") as f:
            json.dump(summary, f, indent=2)

    def print_progress(self) -> None:
        """Print current progress."""
        variables = self.get_all_variables()

        if not variables:
            print("No encoding attempts logged yet.")
            return

        print("=" * 70)
        print("RL ENCODING PROGRESS")
        print("=" * 70)
        print()

        # Group by status
        passed = []
        in_progress = []

        for var, info in sorted(variables.items()):
            if info["achieved_parity"]:
                passed.append((var, info))
            else:
                in_progress.append((var, info))

        if passed:
            print("✅ ACHIEVED PARITY:")
            for var, info in passed:
                print(f"   {var} ({info['section']}): {info['total_rounds']} rounds")

        if in_progress:
            print()
            print("🔄 IN PROGRESS:")
            for var, info in in_progress:
                print(f"   {var} ({info['section']}): {info['final_match_rate']:.1%} after {info['total_rounds']} rounds")

        print()
        print("-" * 70)
        total = len(variables)
        done = len(passed)
        print(f"Progress: {done}/{total} variables ({done/total:.0%})")

        if variables:
            avg_rounds = sum(v["total_rounds"] for v in variables.values()) / total
            print(f"Average rounds: {avg_rounds:.1f}")


# Global tracker instance
_tracker = None


def get_tracker() -> RLTracker:
    """Get the global tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = RLTracker()
    return _tracker


def log_encoding_attempt(
    variable: str,
    section: str,
    result: EncodingValidationResult,
    prompt: str,
    **kwargs,
) -> EncodingAttempt:
    """Convenience function to log an encoding attempt."""
    return get_tracker().log_attempt(variable, section, result, prompt, **kwargs)


def print_progress() -> None:
    """Print current encoding progress."""
    get_tracker().print_progress()


if __name__ == "__main__":
    print_progress()

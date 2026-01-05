"""
Validation Dashboard Schema

JSON schema for validation results consumed by:
1. cosilico.ai dashboard (real-time display)
2. LLM reviewers (diagnostic context)
3. CI checks (pass/fail thresholds)
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
import json


@dataclass
class YearResult:
    """Validation results for a single year."""
    year: int
    oracle: str  # "taxsim" or "policyengine"

    # Core metrics
    match_rate: float  # 0-1, fraction of cases within tolerance
    sample_size: int   # Number of CPS records tested

    # CPS-weighted totals (in dollars)
    rac_total: float
    oracle_total: float
    bias_pct: float  # (rac - oracle) / oracle * 100

    # Distribution metrics
    mean_diff: float
    median_diff: float
    max_abs_diff: float
    correlation: float

    # Detailed discrepancies (top N worst cases)
    discrepancies: list = field(default_factory=list)

    # Metadata
    oracle_version: Optional[str] = None
    duration_ms: int = 0


@dataclass
class VariableValidation:
    """Complete validation results for a single variable."""
    variable: str           # e.g., "income_tax_before_credits"
    citation: str          # e.g., "26 USC 1"
    rac_repo: str          # e.g., "rac-us"
    rac_version: str       # Git SHA or tag
    generated_at: str      # ISO timestamp

    # Per-year results
    years: list[YearResult] = field(default_factory=list)

    # Aggregate metrics
    avg_match_rate: float = 0.0
    total_bias_pct: float = 0.0
    total_sample_size: int = 0

    # Status
    status: str = "pending"  # pending, pass, fail, error
    error: Optional[str] = None

    def compute_aggregates(self):
        """Compute aggregate metrics from year results."""
        if not self.years:
            return

        self.avg_match_rate = sum(y.match_rate for y in self.years) / len(self.years)
        self.total_sample_size = sum(y.sample_size for y in self.years)

        # Weighted bias across years
        total_rac = sum(y.rac_total for y in self.years)
        total_oracle = sum(y.oracle_total for y in self.years)
        if total_oracle != 0:
            self.total_bias_pct = (total_rac - total_oracle) / total_oracle * 100

        # Determine status
        if self.avg_match_rate >= 0.95:
            self.status = "pass"
        elif self.avg_match_rate >= 0.80:
            self.status = "warn"
        else:
            self.status = "fail"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "variable": self.variable,
            "citation": self.citation,
            "rac_repo": self.rac_repo,
            "rac_version": self.rac_version,
            "generated_at": self.generated_at,
            "status": self.status,
            "error": self.error,
            "aggregate": {
                "avg_match_rate": round(self.avg_match_rate, 4),
                "total_bias_pct": round(self.total_bias_pct, 2),
                "total_sample_size": self.total_sample_size,
            },
            "years": [
                {
                    "year": y.year,
                    "oracle": y.oracle,
                    "match_rate": round(y.match_rate, 4),
                    "sample_size": y.sample_size,
                    "rac_total": round(y.rac_total, 2),
                    "oracle_total": round(y.oracle_total, 2),
                    "bias_pct": round(y.bias_pct, 2),
                    "mean_diff": round(y.mean_diff, 2),
                    "correlation": round(y.correlation, 4),
                    "discrepancies": y.discrepancies[:10],  # Top 10
                    "duration_ms": y.duration_ms,
                }
                for y in self.years
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_llm_context(self) -> str:
        """Format for LLM reviewer context (concise)."""
        lines = [
            f"## Validation: {self.variable} ({self.citation})",
            f"Status: {self.status.upper()}",
            f"Match Rate: {self.avg_match_rate:.1%}",
            f"Bias: {self.total_bias_pct:+.2f}%",
            "",
            "| Year | Oracle | Match | Bias |",
            "|------|--------|-------|------|",
        ]

        for y in self.years:
            lines.append(f"| {y.year} | {y.oracle} | {y.match_rate:.1%} | {y.bias_pct:+.1f}% |")

        if any(y.discrepancies for y in self.years):
            lines.extend(["", "### Top Discrepancies:"])
            for y in self.years:
                for d in y.discrepancies[:3]:
                    lines.append(f"- {y.year}: {d}")

        return "\n".join(lines)


@dataclass
class ValidationDashboard:
    """Complete validation dashboard across all variables."""
    rac_repo: str
    rac_version: str
    generated_at: str

    variables: list[VariableValidation] = field(default_factory=list)

    # Summary
    total_variables: int = 0
    passed: int = 0
    warned: int = 0
    failed: int = 0

    def compute_summary(self):
        """Compute summary statistics."""
        self.total_variables = len(self.variables)
        self.passed = sum(1 for v in self.variables if v.status == "pass")
        self.warned = sum(1 for v in self.variables if v.status == "warn")
        self.failed = sum(1 for v in self.variables if v.status == "fail")

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        self.compute_summary()
        return {
            "rac_repo": self.rac_repo,
            "rac_version": self.rac_version,
            "generated_at": self.generated_at,
            "summary": {
                "total_variables": self.total_variables,
                "passed": self.passed,
                "warned": self.warned,
                "failed": self.failed,
            },
            "variables": [v.to_dict() for v in self.variables],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

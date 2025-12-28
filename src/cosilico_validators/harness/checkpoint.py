"""Checkpoint system for saving and loading validation baselines."""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import Checkpoint, Delta, HarnessResult


def get_git_commit() -> str:
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def save_checkpoint(result: HarnessResult, path: Path) -> None:
    """Save harness result as checkpoint."""
    checkpoint = Checkpoint.from_result(result)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": checkpoint.timestamp,
        "git_commit": checkpoint.git_commit,
        "scores": checkpoint.scores,
        "details": checkpoint.details,
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_checkpoint(path: Path) -> Optional[Checkpoint]:
    """Load checkpoint from file."""
    if not path.exists():
        return None

    with open(path) as f:
        data = json.load(f)

    return Checkpoint(
        timestamp=data["timestamp"],
        git_commit=data["git_commit"],
        scores=data["scores"],
        details=data["details"],
    )


def compare_checkpoints(before: Checkpoint, after: Checkpoint) -> Delta:
    """Compare two checkpoints and return delta."""
    return Delta(before=before, after=after)


def get_baseline_path(name: str = "main") -> Path:
    """Get path to baseline file."""
    baselines_dir = Path(__file__).parent.parent.parent.parent / "baselines"
    return baselines_dir / f"{name}.json"


def save_baseline(result: HarnessResult, name: str = "latest") -> Path:
    """Save result as named baseline."""
    path = get_baseline_path(name)
    save_checkpoint(result, path)
    return path


def load_baseline(name: str = "main") -> Optional[Checkpoint]:
    """Load named baseline."""
    path = get_baseline_path(name)
    return load_checkpoint(path)


def create_empty_checkpoint() -> Checkpoint:
    """Create an empty checkpoint for when no baseline exists."""
    return Checkpoint(
        timestamp=datetime.now().isoformat(),
        git_commit="none",
        scores={
            "alignment": 0.0,
            "coverage": 0.0,
            "quality": 0.0,
            "review": 0.0,
        },
        details={},
    )

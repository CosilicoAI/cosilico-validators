"""Batch TAXSIM runner for CPS-scale validation.

Ported from policyengine-taxsim for self-contained operation.
"""

import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# TAXSIM output variable mappings
TAXSIM_OUTPUT_VARS = {
    "v22": "ctc",           # Child Tax Credit
    "v23": "actc",          # Additional CTC (refundable)
    "v25": "eitc",          # Earned Income Credit
    "fiitax": "fiitax",     # Federal income tax
    "siitax": "siitax",     # State income tax
    "fica": "fica",         # FICA taxes
}

# TAXSIM input columns
TAXSIM_REQUIRED_COLUMNS = [
    "taxsimid", "year", "state", "mstat", "page", "sage", "depx",
]

TAXSIM_DEPENDENT_AGE_COLUMNS = [
    "age1", "age2", "age3", "age4", "age5",
    "age6", "age7", "age8", "age9", "age10", "age11",
]

TAXSIM_INCOME_COLUMNS = [
    "pwages", "swages", "psemp", "ssemp", "dividends", "intrec",
    "stcg", "ltcg", "otherprop", "nonprop", "pensions", "gssi",
    "pui", "sui", "transfers", "rentpaid", "proptax", "otheritem",
    "childcare", "mortgage", "scorp", "pbusinc", "pprofinc",
    "sbusinc", "sprofinc", "idtl",
]

ALL_TAXSIM_COLUMNS = TAXSIM_REQUIRED_COLUMNS + TAXSIM_DEPENDENT_AGE_COLUMNS + TAXSIM_INCOME_COLUMNS


class TaxsimBatchRunner:
    """Run TAXSIM on batch data for CPS-scale validation."""

    def __init__(self, taxsim_path: Optional[Path] = None):
        """
        Initialize TAXSIM batch runner.

        Args:
            taxsim_path: Path to TAXSIM executable. Auto-detected if not provided.
        """
        self.taxsim_path = taxsim_path or self._detect_taxsim_executable()
        self._validate_executable()

    def _detect_taxsim_executable(self) -> Path:
        """Detect TAXSIM executable based on OS."""
        system = platform.system().lower()

        if system == "darwin":
            exe_name = "taxsim35-osx.exe"
        elif system == "windows":
            exe_name = "taxsim35-windows.exe"
        elif system == "linux":
            exe_name = "taxsim35-unix.exe"
        else:
            raise OSError(f"Unsupported operating system: {system}")

        # Search paths
        search_paths = [
            Path(__file__).parent.parent.parent.parent / "resources" / "taxsim" / exe_name,
            Path.cwd() / "resources" / "taxsim" / exe_name,
            Path.home() / ".cosilico" / "taxsim" / exe_name,
            # Also check policyengine-taxsim location
            Path.home() / "PolicyEngine/policyengine-taxsim/resources/taxsimtest" / exe_name.replace("taxsim35", "taxsimtest"),
        ]

        for path in search_paths:
            if path.exists():
                return path

        raise FileNotFoundError(
            f"TAXSIM executable '{exe_name}' not found. "
            f"Download from https://taxsim.nber.org/taxsim35/ and place in one of:\n"
            + "\n".join(f"  - {p}" for p in search_paths[:3])
        )

    def _validate_executable(self):
        """Ensure executable exists and is runnable."""
        if not self.taxsim_path.exists():
            raise FileNotFoundError(f"TAXSIM executable not found: {self.taxsim_path}")

        # Make executable on Unix
        if platform.system().lower() != "windows":
            os.chmod(self.taxsim_path, 0o755)

    def _format_input(self, df: pd.DataFrame) -> pd.DataFrame:
        """Format DataFrame for TAXSIM input."""
        formatted = df.copy()

        # Ensure all columns exist with defaults
        for col in ALL_TAXSIM_COLUMNS:
            if col not in formatted.columns:
                formatted[col] = 0

        # Set idtl=2 for full output
        formatted["idtl"] = 2

        return formatted[ALL_TAXSIM_COLUMNS]

    def _create_input_file(self, df: pd.DataFrame) -> str:
        """Create temporary TAXSIM input CSV file."""
        formatted = self._format_input(df)

        temp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        )

        # Write header
        temp_file.write(",".join(ALL_TAXSIM_COLUMNS) + "\n")

        # Write data rows
        for _, row in formatted.iterrows():
            values = [str(row.get(col, 0)) for col in ALL_TAXSIM_COLUMNS]
            temp_file.write(",".join(values) + "\n")

        temp_file.close()
        return temp_file.name

    def _execute(self, input_file: str, output_file: str):
        """Execute TAXSIM on input file."""
        system = platform.system().lower()

        if system != "windows":
            cmd = f'cat "{input_file}" | "{self.taxsim_path}" > "{output_file}"'
        else:
            cmd = f'type "{input_file}" | "{self.taxsim_path}" > "{output_file}"'

        # Environment setup for macOS
        env = os.environ.copy()
        if system == "darwin":
            homebrew_paths = ["/opt/homebrew/bin", "/usr/local/bin"]
            current_path = env.get("PATH", "")
            for hb_path in reversed(homebrew_paths):
                if hb_path not in current_path:
                    current_path = f"{hb_path}:{current_path}"
            env["PATH"] = current_path

        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            env=env,
        )

        if result.returncode != 0:
            raise RuntimeError(f"TAXSIM execution failed: {result.stderr}")

    def _parse_output(self, output_file: str) -> pd.DataFrame:
        """Parse TAXSIM output CSV."""
        df = pd.read_csv(output_file)

        # Convert numeric columns
        for col in df.columns:
            if col != "state_name":
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    def run(self, df: pd.DataFrame, show_progress: bool = True) -> pd.DataFrame:
        """
        Run TAXSIM on input DataFrame.

        Args:
            df: Input data with TAXSIM columns
            show_progress: Print progress messages

        Returns:
            DataFrame with TAXSIM results
        """
        if show_progress:
            print(f"Running TAXSIM on {len(df):,} records...")

        input_file = None
        output_file = None

        try:
            input_file = self._create_input_file(df)

            # Create output file
            output_fd, output_file = tempfile.mkstemp(suffix=".csv")
            os.close(output_fd)

            self._execute(input_file, output_file)

            results = self._parse_output(output_file)

            if show_progress:
                print(f"TAXSIM completed: {len(results):,} results")

            return results

        finally:
            # Cleanup
            for f in [input_file, output_file]:
                if f and os.path.exists(f):
                    try:
                        os.unlink(f)
                    except OSError:
                        pass

    def get_variable(self, results: pd.DataFrame, variable: str) -> Optional[np.ndarray]:
        """
        Extract a specific variable from TAXSIM results.

        Args:
            results: TAXSIM output DataFrame
            variable: Variable name (e.g., 'v22' for CTC, 'v25' for EITC)

        Returns:
            Array of values, or None if not found
        """
        if variable in results.columns:
            return results[variable].values
        return None


def load_cps_taxsim_format(path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load CPS data in TAXSIM format.

    Args:
        path: Path to CSV file. Uses policyengine-taxsim's cps_households.csv if not provided.

    Returns:
        DataFrame ready for TAXSIM
    """
    if path is None:
        path = Path.home() / "PolicyEngine/policyengine-taxsim/cps_households.csv"

    if not path.exists():
        raise FileNotFoundError(f"CPS file not found: {path}")

    return pd.read_csv(path)

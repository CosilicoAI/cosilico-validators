"""TAXSIM validator - uses local TAXSIM executable.

Uses the same approach as policyengine-taxsim, running the TAXSIM executable
locally via subprocess rather than the web service.
"""

import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from cosilico_validators.validators.base import (
    BaseValidator,
    TestCase,
    ValidatorResult,
    ValidatorType,
)

# TAXSIM output variable column names (for idtl=2 full output)
# See: https://taxsim.nber.org/taxsim35/
TAXSIM_OUTPUT_VARS = {
    "federal_income_tax": "fiitax",
    "fiitax": "fiitax",
    "state_income_tax": "siitax",
    "siitax": "siitax",
    "fica": "fica",
    "agi": "v10",
    "taxable_income": "v18",
    "ctc": "v22",
    "child_tax_credit": "v22",
    "actc": "v23",
    "cdctc": "v24",
    "eitc": "v25",
    "earned_income_credit": "v25",
    "amt": "v27",
    "state_agi": "v32",
    "state_eitc": "v39",
}

# State FIPS codes
STATE_CODES = {
    "AL": 1, "AK": 2, "AZ": 4, "AR": 5, "CA": 6, "CO": 8, "CT": 9, "DE": 10,
    "DC": 11, "FL": 12, "GA": 13, "HI": 15, "ID": 16, "IL": 17, "IN": 18,
    "IA": 19, "KS": 20, "KY": 21, "LA": 22, "ME": 23, "MD": 24, "MA": 25,
    "MI": 26, "MN": 27, "MS": 28, "MO": 29, "MT": 30, "NE": 31, "NV": 32,
    "NH": 33, "NJ": 34, "NM": 35, "NY": 36, "NC": 37, "ND": 38, "OH": 39,
    "OK": 40, "OR": 41, "PA": 42, "RI": 44, "SC": 45, "SD": 46, "TN": 47,
    "TX": 48, "UT": 49, "VT": 50, "VA": 51, "WA": 53, "WV": 54, "WI": 55,
    "WY": 56,
}

# Filing status mapping
MSTAT_CODES = {
    "SINGLE": 1,
    "JOINT": 2,
    "MARRIED_FILING_JOINTLY": 2,
    "MARRIED_FILING_SEPARATELY": 6,
    "SEPARATE": 6,
    "HEAD_OF_HOUSEHOLD": 1,  # TAXSIM uses depx to determine HoH
}

# TAXSIM input columns in order
TAXSIM_COLUMNS = [
    "taxsimid", "year", "state", "mstat", "page", "sage", "depx",
    "age1", "age2", "age3",
    "pwages", "swages", "psemp", "ssemp", "dividends", "intrec", "stcg", "ltcg",
    "otherprop", "nonprop", "pensions", "gssi", "pui", "sui", "transfers",
    "rentpaid", "proptax", "otheritem", "childcare", "mortgage",
    "scorp", "pbusinc", "pprofinc", "sbusinc", "sprofinc", "idtl"
]


class TaxsimValidator(BaseValidator):
    """Validator using local TAXSIM executable.

    Uses the TAXSIM executable from NBER, similar to policyengine-taxsim.
    The executable must be downloaded and placed in the resources directory,
    or the path can be provided explicitly.
    """

    name = "TAXSIM"
    validator_type = ValidatorType.REFERENCE
    supported_variables = set(TAXSIM_OUTPUT_VARS.keys())

    def __init__(self, taxsim_path: str | Path | None = None):
        """Initialize TAXSIM validator.

        Args:
            taxsim_path: Path to TAXSIM executable. If not provided,
                         looks in resources/taxsim/ directory.
        """
        self.taxsim_path = self._resolve_taxsim_path(taxsim_path)

    def _resolve_taxsim_path(self, provided_path: str | Path | None) -> Path:
        """Find the TAXSIM executable."""
        if provided_path:
            path = Path(provided_path)
            if path.exists():
                return path
            raise FileNotFoundError(f"TAXSIM executable not found at: {path}")

        # Detect OS-specific executable name
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
        ]

        for path in search_paths:
            if path.exists():
                return path

        raise FileNotFoundError(
            f"TAXSIM executable '{exe_name}' not found. "
            f"Download from https://taxsim.nber.org/taxsim35/ and place in one of:\n"
            + "\n".join(f"  - {p}" for p in search_paths)
        )

    def supports_variable(self, variable: str) -> bool:
        return variable.lower() in TAXSIM_OUTPUT_VARS

    def _build_taxsim_input(self, test_case: TestCase, year: int) -> dict[str, Any]:
        """Convert test case to TAXSIM input format."""
        inputs = test_case.inputs

        # Default TAXSIM record
        taxsim_input = {
            "taxsimid": 1,
            "year": year,
            "state": 6,  # California default
            "mstat": 1,  # Single
            "page": 30,  # Primary age
            "sage": 0,  # Spouse age
            "depx": 0,  # Number of dependents
            "pwages": 0,  # Primary wages
            "swages": 0,  # Spouse wages
            "idtl": 2,  # Full output
        }

        # Map common inputs to TAXSIM variables
        input_mapping = {
            "age": "page",
            "age_at_end_of_year": "page",
            "earned_income": "pwages",
            "employment_income": "pwages",
            "wages": "pwages",
            "agi": "pwages",  # Use wages as proxy for AGI
            "spouse_wages": "swages",
            "qualifying_children": "depx",
            "qualifying_children_under_17": "depx",
            "ctc_qualifying_children": "depx",
            "eitc_qualifying_children_count": "depx",
            "num_children": "depx",
            "children": "depx",
        }

        for key, value in inputs.items():
            key_lower = key.lower()

            # Handle state
            if key_lower in ["state", "state_name"]:
                if isinstance(value, str):
                    taxsim_input["state"] = STATE_CODES.get(value.upper(), 6)
                else:
                    taxsim_input["state"] = value
            # Handle filing status
            elif key_lower == "filing_status":
                taxsim_input["mstat"] = MSTAT_CODES.get(value.upper(), 1)
            # Handle mapped inputs
            elif key_lower in input_mapping:
                taxsim_input[input_mapping[key_lower]] = value

        # Handle filing status affecting household structure
        filing_status = inputs.get("filing_status", "SINGLE").upper()
        if filing_status in ["JOINT", "MARRIED_FILING_JOINTLY"]:
            taxsim_input["mstat"] = 2
            if taxsim_input["sage"] == 0:
                taxsim_input["sage"] = taxsim_input["page"]  # Default spouse age

        # Add child ages if dependents exist
        num_deps = taxsim_input.get("depx", 0)
        for i in range(min(num_deps, 3)):
            taxsim_input[f"age{i+1}"] = 10  # Default child age

        return taxsim_input

    def _create_input_csv(self, taxsim_input: dict) -> str:
        """Create TAXSIM input CSV file."""
        temp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        )

        # Write header
        temp_file.write(",".join(TAXSIM_COLUMNS) + "\n")

        # Write data row
        row = [str(taxsim_input.get(col, 0)) for col in TAXSIM_COLUMNS]
        temp_file.write(",".join(row) + "\n")

        temp_file.close()
        return temp_file.name

    def _execute_taxsim(self, input_file: str) -> str:
        """Execute TAXSIM and return output."""
        # Make executable on Unix
        if platform.system().lower() != "windows":
            os.chmod(self.taxsim_path, 0o755)

        # Create output file
        output_fd, output_file = tempfile.mkstemp(suffix=".csv")
        os.close(output_fd)

        try:
            system = platform.system().lower()

            if system != "windows":
                cmd = f'cat "{input_file}" | "{self.taxsim_path}" > "{output_file}"'
            else:
                cmd = f'type "{input_file}" | "{self.taxsim_path}" > "{output_file}"'

            # Set up environment
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
                raise RuntimeError(f"TAXSIM failed: {result.stderr}")

            with open(output_file, "r") as f:
                return f.read()

        finally:
            if os.path.exists(output_file):
                os.unlink(output_file)

    def _parse_output(self, output: str, variable: str) -> float | None:
        """Parse TAXSIM output CSV."""
        lines = output.strip().split("\n")
        if len(lines) < 2:
            raise ValueError(f"Invalid TAXSIM output: {output}")

        headers = [h.strip() for h in lines[0].split(",")]
        values = [v.strip() for v in lines[1].split(",")]

        result = dict(zip(headers, values))

        # Get the column name for this variable
        var_lower = variable.lower()
        col_name = TAXSIM_OUTPUT_VARS.get(var_lower)

        if col_name and col_name in result:
            return float(result[col_name])

        # Try direct lookup
        if var_lower in result:
            return float(result[var_lower])

        # Try partial match
        for key, value in result.items():
            if var_lower in key.lower():
                return float(value)

        return None

    def validate(
        self, test_case: TestCase, variable: str, year: int = 2023
    ) -> ValidatorResult:
        """Run validation using local TAXSIM executable.

        Note: TAXSIM-35 only supports tax years 1960-2023.
        """
        # Validate year is within TAXSIM's supported range
        if year < 1960 or year > 2023:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=f"TAXSIM-35 only supports tax years 1960-2023, got {year}",
            )

        var_lower = variable.lower()
        if var_lower not in TAXSIM_OUTPUT_VARS:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=f"Variable '{variable}' not supported by TAXSIM",
            )

        input_file = None
        try:
            taxsim_input = self._build_taxsim_input(test_case, year)
            input_file = self._create_input_csv(taxsim_input)

            output = self._execute_taxsim(input_file)
            calculated = self._parse_output(output, variable)

            if calculated is None:
                return ValidatorResult(
                    validator_name=self.name,
                    validator_type=self.validator_type,
                    calculated_value=None,
                    error=f"Could not find {variable} in TAXSIM output",
                    metadata={"raw_output": output},
                )

            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=calculated,
                metadata={"taxsim_input": taxsim_input, "year": year},
            )

        except FileNotFoundError as e:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=str(e),
            )
        except Exception as e:
            return ValidatorResult(
                validator_name=self.name,
                validator_type=self.validator_type,
                calculated_value=None,
                error=f"TAXSIM execution failed: {e}",
            )
        finally:
            if input_file and os.path.exists(input_file):
                os.unlink(input_file)

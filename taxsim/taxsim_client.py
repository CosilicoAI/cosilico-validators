"""TaxSim 35 client.

This module provides a client for submitting tax cases to the NBER TaxSim 35
service and parsing the results.

TaxSim 35 supports multiple access methods:
- SSH (recommended): ssh taxsim35@taxsimssh.nber.org
- HTTP: https://taxsim.nber.org/taxsim35/redirect.cgi
- FTP: taxsimftp.nber.org

This client uses SSH by default as it is the most reliable method.

API Documentation: https://taxsim.nber.org/taxsim35/
"""

import csv
import io
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import requests

from .variable_mapping import (
    FILING_STATUS_TO_MSTAT,
    STATE_FIPS,
    TAXSIM_TO_COSILICO,
    get_filing_status_code,
    get_state_code,
)


# TaxSim 35 SSH endpoint (recommended method)
TAXSIM_SSH_HOST = "taxsim35@taxsimssh.nber.org"

# TaxSim 35 HTTP endpoint (fallback)
TAXSIM_HTTP_URL = "https://taxsim.nber.org/taxsim35/redirect.cgi"

# Supported tax years for TaxSim 35
TAXSIM_MIN_YEAR = 1960
TAXSIM_MAX_YEAR = 2023

# Default timeout for API requests (seconds)
DEFAULT_TIMEOUT = 120

# Columns in standard TaxSim CSV input format
TAXSIM_INPUT_COLUMNS = [
    "taxsimid", "year", "state", "mstat", "page", "sage", "depx",
    "age1", "age2", "age3",
    "pwages", "swages", "psemp", "ssemp", "dividends", "intrec",
    "stcg", "ltcg", "otherprop", "nonprop", "pensions", "gssi",
    "pui", "sui", "transfers", "rentpaid", "proptax", "otheritem",
    "childcare", "mortgage", "scorp", "pbusinc", "pprofinc",
    "sbusinc", "sprofinc", "idtl",
]


@dataclass
class TaxSimCase:
    """A single tax case to submit to TaxSim.

    Attributes:
        taxsimid: Unique record identifier
        year: Tax year (1960-2023)
        state: State code or abbreviation (0 for no state tax)
        filing_status: Filing status (SINGLE, JOINT, HOH, SEPARATE)
        primary_age: Primary taxpayer's age
        spouse_age: Spouse's age (0 if single)
        num_dependents: Number of dependents
        child_ages: List of dependent ages (up to 3)
        primary_wages: Primary taxpayer wages
        spouse_wages: Spouse wages
        primary_self_employment: Primary self-employment income
        spouse_self_employment: Spouse self-employment income
        dividends: Dividend income
        interest: Interest income
        short_term_gains: Short-term capital gains
        long_term_gains: Long-term capital gains
        other_property_income: Rent, royalties, etc.
        other_income: Other non-property income
        pensions: Taxable pension income
        social_security: Gross Social Security income
        primary_unemployment: Primary taxpayer unemployment
        spouse_unemployment: Spouse unemployment
        transfers: Non-taxable transfer income
        rent_paid: Rent paid (for state credits)
        property_tax: Property taxes paid
        other_itemized: Other itemized deductions
        childcare: Child care expenses
        mortgage_interest: Mortgage interest paid
    """

    taxsimid: int = 1
    year: int = 2023
    state: Union[int, str] = 0
    filing_status: str = "SINGLE"
    primary_age: int = 40
    spouse_age: int = 0
    num_dependents: int = 0
    child_ages: List[int] = field(default_factory=list)

    # Income
    primary_wages: float = 0.0
    spouse_wages: float = 0.0
    primary_self_employment: float = 0.0
    spouse_self_employment: float = 0.0
    dividends: float = 0.0
    interest: float = 0.0
    short_term_gains: float = 0.0
    long_term_gains: float = 0.0
    other_property_income: float = 0.0
    other_income: float = 0.0
    pensions: float = 0.0
    social_security: float = 0.0
    primary_unemployment: float = 0.0
    spouse_unemployment: float = 0.0
    transfers: float = 0.0

    # Deductions
    rent_paid: float = 0.0
    property_tax: float = 0.0
    other_itemized: float = 0.0
    childcare: float = 0.0
    mortgage_interest: float = 0.0

    # Business income
    scorp_income: float = 0.0
    primary_business_income: float = 0.0
    primary_professional_income: float = 0.0
    spouse_business_income: float = 0.0
    spouse_professional_income: float = 0.0

    # Metadata
    name: Optional[str] = None
    notes: Optional[str] = None

    def to_taxsim_dict(self) -> Dict[str, Any]:
        """Convert to TaxSim input format dictionary."""
        # Handle state code
        state_code = get_state_code(self.state) if isinstance(self.state, str) else self.state

        # Handle filing status
        mstat = get_filing_status_code(self.filing_status)

        # Build the TaxSim record
        record = {
            "taxsimid": self.taxsimid,
            "year": min(max(self.year, TAXSIM_MIN_YEAR), TAXSIM_MAX_YEAR),
            "state": state_code,
            "mstat": mstat,
            "page": self.primary_age,
            "sage": self.spouse_age,
            "depx": self.num_dependents,
            "age1": self.child_ages[0] if len(self.child_ages) > 0 else 0,
            "age2": self.child_ages[1] if len(self.child_ages) > 1 else 0,
            "age3": self.child_ages[2] if len(self.child_ages) > 2 else 0,
            "pwages": self.primary_wages,
            "swages": self.spouse_wages,
            "psemp": self.primary_self_employment,
            "ssemp": self.spouse_self_employment,
            "dividends": self.dividends,
            "intrec": self.interest,
            "stcg": self.short_term_gains,
            "ltcg": self.long_term_gains,
            "otherprop": self.other_property_income,
            "nonprop": self.other_income,
            "pensions": self.pensions,
            "gssi": self.social_security,
            "pui": self.primary_unemployment,
            "sui": self.spouse_unemployment,
            "transfers": self.transfers,
            "rentpaid": self.rent_paid,
            "proptax": self.property_tax,
            "otheritem": self.other_itemized,
            "childcare": self.childcare,
            "mortgage": self.mortgage_interest,
            "scorp": self.scorp_income,
            "pbusinc": self.primary_business_income,
            "pprofinc": self.primary_professional_income,
            "sbusinc": self.spouse_business_income,
            "sprofinc": self.spouse_professional_income,
            "idtl": 2,  # Full output
        }

        return record

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaxSimCase":
        """Create a TaxSimCase from a dictionary.

        Supports both Cosilico-style variable names and TaxSim native names.
        """
        # Map common Cosilico input names to TaxSimCase attributes
        name_map = {
            "earned_income": "primary_wages",
            "wages": "primary_wages",
            "employment_income": "primary_wages",
            "agi": "primary_wages",  # Approximate AGI with wages
            "self_employment_income": "primary_self_employment",
            "dividend_income": "dividends",
            "interest_income": "interest",
            "capital_gains": "long_term_gains",
            "social_security_income": "social_security",
            "unemployment_income": "primary_unemployment",
            "num_children": "num_dependents",
            "qualifying_children": "num_dependents",
            "ctc_qualifying_children": "num_dependents",
            "eitc_qualifying_children_count": "num_dependents",
            "age": "primary_age",
            "age_at_end_of_year": "primary_age",
        }

        # Start with default values
        kwargs = {}

        for key, value in data.items():
            key_lower = key.lower()

            # Check for mapped name
            if key_lower in name_map:
                attr_name = name_map[key_lower]
                kwargs[attr_name] = value
            # Check for direct attribute
            elif hasattr(cls, key_lower):
                kwargs[key_lower] = value
            # Handle special cases
            elif key_lower == "filing_status":
                kwargs["filing_status"] = value.upper() if isinstance(value, str) else value

        return cls(**kwargs)


@dataclass
class TaxSimResult:
    """Result from a TaxSim calculation.

    Contains both the raw TaxSim output and mapped Cosilico variables.
    """

    taxsimid: int
    year: int
    raw_output: Dict[str, float]
    cosilico_output: Dict[str, float]
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None

    def get(self, variable: str) -> Optional[float]:
        """Get a variable value by name (TaxSim or Cosilico name)."""
        # Try Cosilico name first
        if variable in self.cosilico_output:
            return self.cosilico_output[variable]

        # Try raw TaxSim name
        if variable in self.raw_output:
            return self.raw_output[variable]

        return None


class TaxSimClient:
    """Client for the TaxSim 35 web API.

    Usage:
        client = TaxSimClient()

        # Single case
        case = TaxSimCase(
            year=2023,
            filing_status="SINGLE",
            primary_wages=50000,
        )
        result = client.calculate(case)
        print(result.cosilico_output["adjusted_gross_income"])

        # Multiple cases
        cases = [TaxSimCase(...), TaxSimCase(...)]
        results = client.calculate_batch(cases)
    """

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """Initialize the TaxSim client.

        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._session = requests.Session()

    def _cases_to_csv(self, cases: List[TaxSimCase]) -> str:
        """Convert cases to CSV format for TaxSim API."""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=TAXSIM_INPUT_COLUMNS)
        writer.writeheader()

        for case in cases:
            row = case.to_taxsim_dict()
            # Ensure all columns have values
            for col in TAXSIM_INPUT_COLUMNS:
                if col not in row:
                    row[col] = 0
            writer.writerow({col: row.get(col, 0) for col in TAXSIM_INPUT_COLUMNS})

        return output.getvalue()

    def _parse_response(self, response_text: str) -> List[Dict[str, float]]:
        """Parse TaxSim CSV response."""
        reader = csv.DictReader(io.StringIO(response_text))
        results = []

        for row in reader:
            parsed = {}
            for key, value in row.items():
                key = key.strip()
                try:
                    parsed[key] = float(value) if value.strip() else 0.0
                except ValueError:
                    parsed[key] = value
            results.append(parsed)

        return results

    def _map_to_cosilico(self, raw: Dict[str, float]) -> Dict[str, float]:
        """Map TaxSim output variables to Cosilico names."""
        cosilico = {}
        for taxsim_var, cosilico_var in TAXSIM_TO_COSILICO.items():
            if taxsim_var in raw:
                cosilico[cosilico_var] = raw[taxsim_var]
        return cosilico

    def _submit_via_ssh(self, csv_data: str) -> str:
        """Submit CSV data to TaxSim via SSH (recommended method)."""
        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-T",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "BatchMode=yes",
                    "-o", f"ConnectTimeout={self.timeout}",
                    TAXSIM_SSH_HOST,
                ],
                input=csv_data,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            if result.returncode != 0:
                raise RuntimeError(f"SSH command failed: {result.stderr}")

            return result.stdout

        except subprocess.TimeoutExpired:
            raise ConnectionError("TaxSim SSH connection timed out")
        except FileNotFoundError:
            raise RuntimeError("SSH client not available")

    def _submit_via_http(self, csv_data: str) -> str:
        """Submit CSV data to TaxSim via HTTP (fallback method)."""
        files = {
            "userfile": ("taxsim_input.csv", csv_data, "text/csv"),
        }
        data = {
            "mtr": "85",  # Taxpayer earnings
        }

        response = self._session.post(
            TAXSIM_HTTP_URL,
            files=files,
            data=data,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    def _submit_request(self, csv_data: str) -> str:
        """Submit CSV data to TaxSim with retries.

        Tries SSH first (most reliable), then falls back to HTTP if SSH fails.
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                # Try SSH first (recommended by NBER)
                return self._submit_via_ssh(csv_data)
            except (RuntimeError, ConnectionError) as e:
                # SSH failed, try HTTP
                try:
                    return self._submit_via_http(csv_data)
                except requests.RequestException as http_error:
                    last_error = http_error

            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay * (attempt + 1))

        raise ConnectionError(f"TaxSim request failed after {self.max_retries} attempts: {last_error}")

    def calculate(self, case: TaxSimCase) -> TaxSimResult:
        """Calculate taxes for a single case.

        Args:
            case: Tax case to calculate

        Returns:
            TaxSimResult with calculated values
        """
        results = self.calculate_batch([case])
        return results[0]

    def calculate_batch(self, cases: List[TaxSimCase]) -> List[TaxSimResult]:
        """Calculate taxes for multiple cases in a single API call.

        Args:
            cases: List of tax cases to calculate

        Returns:
            List of TaxSimResult objects
        """
        if not cases:
            return []

        try:
            # Prepare and submit request
            csv_data = self._cases_to_csv(cases)
            response_text = self._submit_request(csv_data)

            # Parse response
            raw_results = self._parse_response(response_text)

            # Create result objects
            results = []
            for i, case in enumerate(cases):
                if i < len(raw_results):
                    raw = raw_results[i]
                    cosilico = self._map_to_cosilico(raw)
                    results.append(TaxSimResult(
                        taxsimid=case.taxsimid,
                        year=case.year,
                        raw_output=raw,
                        cosilico_output=cosilico,
                    ))
                else:
                    results.append(TaxSimResult(
                        taxsimid=case.taxsimid,
                        year=case.year,
                        raw_output={},
                        cosilico_output={},
                        error="No result returned from TaxSim",
                    ))

            return results

        except Exception as e:
            # Return error results for all cases
            return [
                TaxSimResult(
                    taxsimid=case.taxsimid,
                    year=case.year,
                    raw_output={},
                    cosilico_output={},
                    error=str(e),
                )
                for case in cases
            ]

    def validate_year(self, year: int) -> bool:
        """Check if a tax year is supported by TaxSim 35."""
        return TAXSIM_MIN_YEAR <= year <= TAXSIM_MAX_YEAR

    def get_supported_years(self) -> tuple:
        """Return the range of supported tax years."""
        return (TAXSIM_MIN_YEAR, TAXSIM_MAX_YEAR)


def create_test_case(
    earned_income: float = 0,
    filing_status: str = "SINGLE",
    num_children: int = 0,
    year: int = 2023,
    age: int = 40,
    **kwargs,
) -> TaxSimCase:
    """Convenience function to create a test case with common defaults.

    Args:
        earned_income: Primary taxpayer earned income (wages)
        filing_status: Filing status (SINGLE, JOINT, HOH)
        num_children: Number of qualifying children
        year: Tax year
        age: Primary taxpayer age
        **kwargs: Additional TaxSimCase attributes

    Returns:
        Configured TaxSimCase
    """
    # Set spouse age for joint filers
    spouse_age = age if filing_status.upper() in ["JOINT", "MARRIED_FILING_JOINTLY"] else 0

    # Set child ages (default 10 years old)
    child_ages = [10] * min(num_children, 3)

    return TaxSimCase(
        year=year,
        filing_status=filing_status,
        primary_age=age,
        spouse_age=spouse_age,
        num_dependents=num_children,
        child_ages=child_ages,
        primary_wages=earned_income,
        **kwargs,
    )

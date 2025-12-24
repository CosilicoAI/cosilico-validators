"""Load input variables from microdata using the cosilico-us schema."""

import yaml
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_input_schema(
    cosilico_us_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Load the input variable schema from cosilico-us.

    Args:
        cosilico_us_path: Path to cosilico-us repo (default: ~/CosilicoAI/cosilico-us)

    Returns:
        Parsed schema dict with variables, entities, and groups
    """
    if cosilico_us_path is None:
        cosilico_us_path = Path.home() / "CosilicoAI/cosilico-us"

    schema_path = cosilico_us_path / "inputs" / "variables.yaml"

    if not schema_path.exists():
        raise FileNotFoundError(f"Input schema not found at {schema_path}")

    with open(schema_path) as f:
        return yaml.safe_load(f)


def get_pe_variable_mapping(schema: Dict[str, Any]) -> Dict[str, str]:
    """
    Get mapping from Cosilico variable names to PolicyEngine variable names.

    Args:
        schema: Loaded input schema

    Returns:
        Dict mapping cosilico_name -> pe_variable
    """
    mapping = {}
    for name, config in schema.get("variables", {}).items():
        pe_var = config.get("pe_variable")
        if pe_var:
            mapping[name] = pe_var
    return mapping


def get_variable_group(schema: Dict[str, Any], group_name: str) -> List[str]:
    """
    Get the list of variables in a group.

    Args:
        schema: Loaded input schema
        group_name: Name of the group (e.g., "eitc_inputs")

    Returns:
        List of variable names
    """
    groups = schema.get("groups", {})
    group = groups.get(group_name, {})
    return group.get("variables", [])


class InputLoader:
    """Load input variables from PolicyEngine simulation using schema."""

    def __init__(
        self,
        cosilico_us_path: Optional[Path] = None,
    ):
        """
        Initialize the input loader.

        Args:
            cosilico_us_path: Path to cosilico-us repo
        """
        self.cosilico_us_path = cosilico_us_path or Path.home() / "CosilicoAI/cosilico-us"
        self.schema = load_input_schema(self.cosilico_us_path)
        self.pe_mapping = get_pe_variable_mapping(self.schema)

    def load_from_pe(
        self,
        simulation,
        year: int,
        variables: Optional[List[str]] = None,
        group: Optional[str] = None,
    ) -> Dict[str, np.ndarray]:
        """
        Load input variables from a PolicyEngine simulation.

        Args:
            simulation: PolicyEngine Microsimulation or Simulation object
            year: Tax year
            variables: List of variable names to load (if None, load all mapped)
            group: Name of variable group to load (e.g., "eitc_inputs")

        Returns:
            Dict mapping variable names to numpy arrays
        """
        # Determine which variables to load
        if group:
            var_list = get_variable_group(self.schema, group)
        elif variables:
            var_list = variables
        else:
            var_list = list(self.pe_mapping.keys())

        inputs = {}

        for var_name in var_list:
            pe_var = self.pe_mapping.get(var_name)
            if pe_var is None:
                continue

            try:
                values = simulation.calculate(pe_var, year)
                inputs[var_name] = np.asarray(values)
            except Exception as e:
                print(f"  Warning: Could not load {var_name} ({pe_var}): {e}")
                continue

        # Add entity mappings
        try:
            inputs["_tax_unit_id"] = np.asarray(
                simulation.calculate("tax_unit_id", year)
            )
            inputs["_person_tax_unit_id"] = np.asarray(
                simulation.calculate("person_tax_unit_id", year)
            )
            inputs["_household_id"] = np.asarray(
                simulation.calculate("household_id", year)
            )
        except Exception:
            pass  # Entity mappings are optional

        return inputs

    def get_variable_info(self, var_name: str) -> Optional[Dict[str, Any]]:
        """Get schema info for a variable."""
        return self.schema.get("variables", {}).get(var_name)

    def get_cosilico_path(self, var_name: str) -> Optional[str]:
        """Get the cosilico statute path for a variable."""
        info = self.get_variable_info(var_name)
        return info.get("cosilico_path") if info else None

    def get_entity(self, var_name: str) -> Optional[str]:
        """Get the entity type for a variable."""
        info = self.get_variable_info(var_name)
        return info.get("entity") if info else None

    def list_variables(self) -> List[str]:
        """List all defined variables."""
        return list(self.schema.get("variables", {}).keys())

    def list_groups(self) -> List[str]:
        """List all defined variable groups."""
        return list(self.schema.get("groups", {}).keys())

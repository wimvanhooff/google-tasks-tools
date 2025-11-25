"""
Simple configuration file parser for plain .conf files.

Format:
- Lines starting with # are comments
- Empty lines are ignored
- Key-value pairs: key = value
- List values: key = value1, value2, value3
- Boolean values: key = true/false/yes/no/1/0
- Nested sections not supported (flat structure)
"""

import os
from typing import Any, Dict, List, Optional


def parse_value(value: str) -> Any:
    """Parse a string value into appropriate Python type.

    Args:
        value: Raw string value from config file

    Returns:
        Parsed value (bool, int, float, list, or string)
    """
    value = value.strip()

    # Empty value
    if not value:
        return ''

    # Boolean values
    if value.lower() in ('true', 'yes', '1'):
        return True
    if value.lower() in ('false', 'no', '0'):
        return False

    # Try integer
    try:
        return int(value)
    except ValueError:
        pass

    # Try float
    try:
        return float(value)
    except ValueError:
        pass

    # Check for list (comma-separated values)
    if ',' in value:
        items = [item.strip() for item in value.split(',')]
        # Filter out empty strings
        items = [item for item in items if item]
        return items

    return value


def load_config(filepath: str, defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Load configuration from a plain .conf file.

    Args:
        filepath: Path to the configuration file
        defaults: Optional dictionary of default values

    Returns:
        Dictionary with configuration values
    """
    config = dict(defaults) if defaults else {}

    if not os.path.exists(filepath):
        return config

    with open(filepath, 'r') as f:
        for line_num, line in enumerate(f, 1):
            # Strip whitespace
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            # Parse key=value
            if '=' not in line:
                continue

            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip()

            # Skip empty keys
            if not key:
                continue

            config[key] = parse_value(value)

    return config


def save_config(filepath: str, config: Dict[str, Any], comments: Optional[Dict[str, str]] = None):
    """Save configuration to a plain .conf file.

    Args:
        filepath: Path to the configuration file
        config: Dictionary with configuration values
        comments: Optional dictionary mapping keys to comment strings
    """
    comments = comments or {}

    with open(filepath, 'w') as f:
        for key, value in config.items():
            # Write comment if provided
            if key in comments:
                f.write(f"# {comments[key]}\n")

            # Format value
            if isinstance(value, bool):
                str_value = 'true' if value else 'false'
            elif isinstance(value, list):
                str_value = ', '.join(str(item) for item in value)
            else:
                str_value = str(value)

            f.write(f"{key} = {str_value}\n")

            # Add blank line after commented entries
            if key in comments:
                f.write("\n")


def create_default_config(filepath: str, template: str):
    """Create a default configuration file from a template string.

    Args:
        filepath: Path where config file should be created
        template: Template string content for the config file
    """
    with open(filepath, 'w') as f:
        f.write(template)

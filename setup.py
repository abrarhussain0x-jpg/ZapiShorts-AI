"""Compatibility wrapper for setup checks.

The actual implementation lives in :mod:`src.zapi.environment` so the project
has a proper package namespace without breaking existing imports.
"""

from __future__ import annotations

import sys

from src.zapi.environment import (check_dependencies, check_directories,
                                  check_env_file, check_env_variables,
                                  check_python_version, check_system_tools,
                                  main)

__all__ = [
    "check_python_version",
    "check_env_file",
    "check_dependencies",
    "check_system_tools",
    "check_env_variables",
    "check_directories",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())

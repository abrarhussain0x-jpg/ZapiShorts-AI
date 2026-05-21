"""Package entrypoint for the ZAPI command-line interface."""

from __future__ import annotations

from cli import cli as cli


def main() -> None:
    """Execute the root CLI command group."""
    cli()


if __name__ == "__main__":
    main()

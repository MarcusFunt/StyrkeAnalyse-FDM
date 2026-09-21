"""Command-line entry point for the research pipeline."""

from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="FDM strength-analysis research tools.", no_args_is_help=True)
console = Console()


@app.command()
def info() -> None:
    """Show the initial project boundary and available next steps."""
    console.print("[bold]StyrkeAnalyse-FDM[/bold] 0.1.0")
    console.print("Initial scaffold: toolpath parsing → material mapping → solver comparison.")


@app.command()
def inspect(path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    """Confirm that a future input file is reachable from the analysis environment."""
    console.print(f"Input: {path.resolve()}")
    console.print(f"Size: {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    app()

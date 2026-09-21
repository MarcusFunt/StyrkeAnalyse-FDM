from typer.testing import CliRunner

from fdm_strength import __version__
from fdm_strength.cli import app


def test_version_is_defined() -> None:
    assert __version__ == "0.1.0"


def test_info_command_runs() -> None:
    result = CliRunner().invoke(app, ["info"])
    assert result.exit_code == 0
    assert "StyrkeAnalyse-FDM" in result.stdout

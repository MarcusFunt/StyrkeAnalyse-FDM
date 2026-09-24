import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_analysis_image_installs_the_locked_project_before_jupyter():
    dockerfile = (ROOT / "docker/analysis.Dockerfile").read_text()
    frozen_sync = dockerfile.index("uv sync --frozen --all-groups")
    jupyter_install = dockerfile.index(
        "uv pip install --python /opt/venv/bin/python --requirement /tmp/jupyter-requirements.txt"
    )
    assert frozen_sync < jupyter_install


def test_notebook_requirements_do_not_repin_locked_scientific_packages():
    requirements = (ROOT / "docker/jupyter-requirements.txt").read_text().splitlines()
    assert requirements == ["jupyterlab==4.4.10", "ipykernel==6.30.1"]


def test_fenicsx_sync_restores_jupyter_and_devcontainer_runs_only_fenicsx():
    devcontainer = json.loads((ROOT / ".devcontainer/devcontainer.json").read_text())
    post_create = devcontainer["postCreateCommand"]
    assert post_create.index("uv sync --frozen --all-groups") < post_create.index(
        "uv pip install --python /opt/venv/bin/python --requirement docker/jupyter-requirements.txt"
    )
    assert devcontainer["runServices"] == ["fenicsx"]


def test_fenicsx_notebooks_import_the_mounted_project_source():
    compose = (ROOT / "compose.yaml").read_text()
    fenicsx = compose.split("  fenicsx:", 1)[1].split("  rve:", 1)[0]
    dockerfile = (ROOT / "docker/Dockerfile").read_text()
    assert "ENV PYTHONPATH=/workspaces/styrkeanalyse-fdm/src:${PYTHONPATH}" in dockerfile
    assert "PYTHONPATH:" not in fenicsx


def test_fenicsx_image_reuses_the_base_account_when_uid_already_exists():
    dockerfile = (ROOT / "docker/Dockerfile").read_text()
    assert 'getent passwd "${USER_UID}"' in dockerfile
    assert 'usermod --login "${USERNAME}"' in dockerfile


def test_fenicsx_venv_uses_the_base_dolfinx_interpreter():
    dockerfile = (ROOT / "docker/Dockerfile").read_text()
    assert "uv venv --system-site-packages --python /dolfinx-env/bin/python /opt/venv" in dockerfile
    assert 'base_site_packages="$(/dolfinx-env/bin/python -c' in dockerfile
    assert "dolfinx-env.pth" in dockerfile


def test_linux_environment_script_keeps_lf_line_endings_on_windows_checkouts():
    script = ROOT / "scripts/verify-environment.sh"
    assert b"\r\n" not in script.read_bytes()


def test_gui_service_stores_studies_and_is_loopback_only():
    compose = (ROOT / "compose.yaml").read_text()
    gui = compose.split("  gui:", 1)[1].split("\nvolumes:", 1)[0]
    assert "127.0.0.1:8010:8000" in gui
    assert "gui_data:/data" in gui
    assert "restart: unless-stopped" in gui

    dockerfile = (ROOT / "docker/gui.Dockerfile").read_text()
    assert "npm ci" in dockerfile
    assert "USER gui" in dockerfile
    assert 'CMD ["python", "-m", "fdm_strength.web"]' in dockerfile


def test_remote_desktop_instructions_use_tailnet_serve_without_exposing_other_ports():
    readme = (ROOT / "README.md").read_text()
    assert "tailscale serve --bg 8010" in readme
    assert "Tailscale Funnel" in readme
    assert "GPU" in readme

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
    assert "PYTHONPATH: /workspaces/styrkeanalyse-fdm/src" in fenicsx

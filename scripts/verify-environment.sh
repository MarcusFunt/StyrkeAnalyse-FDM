#!/usr/bin/env bash
set -euo pipefail

command -v ccx >/dev/null
command -v gmsh >/dev/null
command -v mpirun >/dev/null

python - <<'PY'
import dolfinx
import gmsh
import meshio
import numpy
import petsc4py
import pyvista
import scipy

print(f"dolfinx={dolfinx.__version__}")
print(f"numpy={numpy.__version__}")
print(f"scipy={scipy.__version__}")
print(f"petsc4py={petsc4py.__version__}")
print(f"gmsh={gmsh.__version__}")
print(f"meshio={meshio.__version__}")
print(f"pyvista={pyvista.__version__}")
PY

fdm-strength --help >/dev/null
pytest -q

echo "Environment verification passed."

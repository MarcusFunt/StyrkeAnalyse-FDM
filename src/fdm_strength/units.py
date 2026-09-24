"""Project unit convention: millimetres, newtons, and MPa for mechanics."""

MM_PER_M = 1_000.0
N_PER_KN = 1_000.0
MM_PER_CM = 10.0
MM2_PER_M2 = MM_PER_M**2
MPA_PER_PA = 1e-6
TONNE_PER_KG = 1e-3
TONNE_PER_MM3_PER_KG_PER_M3 = 1e-12


def density_kg_m3_to_tonne_mm3(value: float) -> float:
    """Convert kg/m³ to tonne/mm³ for CalculiX-compatible material data."""
    return value * TONNE_PER_MM3_PER_KG_PER_M3

def nominal_tensile_stress_mpa(force_newton: float, area_mm2: float) -> float:
    if area_mm2 <= 0:
        raise ValueError("area_mm2 must be positive")
    return force_newton / area_mm2

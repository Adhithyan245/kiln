"""Convergence tests for relaxations. A variable-cell relaxation must pass force AND stress."""
from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike

__all__ = ["max_force", "max_stress", "converged"]


def max_force(forces: ArrayLike) -> float:
    """Largest per-atom force norm, eV/Å."""
    f = np.asarray(forces, dtype=float).reshape(-1, 3)
    return float(np.sqrt((f * f).sum(axis=1)).max()) if len(f) else 0.0


def max_stress(stress: ArrayLike) -> float:
    """Largest absolute stress component (Voigt or 3x3), eV/Å³."""
    return float(np.abs(np.asarray(stress, dtype=float)).max())


def converged(forces: ArrayLike, stress: ArrayLike, fmax_ev_per_a: float, stress_tol_ev_per_a3: float) -> bool:
    return max_force(forces) <= fmax_ev_per_a and max_stress(stress) <= stress_tol_ev_per_a3

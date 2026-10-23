from __future__ import annotations

import math
import re
from functools import reduce
from operator import mul


def american_to_decimal(value: str | int | float) -> float:
    """Convierte una cuota americana a decimal sin redondear internamente."""
    text = str(value).strip().replace("−", "-").replace(" ", "")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        raise ValueError(f"Cuota americana inválida: {value!r}")
    american = float(text)
    if american == 0:
        raise ValueError("La cuota americana no puede ser cero")
    return 1.0 + (american / 100.0 if american > 0 else 100.0 / abs(american))


def visible_to_decimal(value: str | int | float) -> float:
    """Interpreta la cuota tal como aparece en Triunfobet.

    Las cuotas con signo son americanas. Las cuotas sin signo y mayores que
    uno ya están en formato decimal. Así la aplicación funciona aunque el
    usuario cambie el formato visible de la casa.
    """
    text = str(value).strip().replace("−", "-").replace(",", ".").replace(" ", "")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        raise ValueError(f"Cuota visible inválida: {value!r}")
    if text.startswith(("+", "-")):
        return american_to_decimal(text)
    decimal = float(text)
    if decimal <= 1.0 or not math.isfinite(decimal):
        raise ValueError("La cuota decimal debe ser mayor que 1")
    return decimal


def implied_probability(decimal_odds: float) -> float:
    if decimal_odds <= 1.0 or not math.isfinite(decimal_odds):
        raise ValueError("La cuota decimal debe ser mayor que 1")
    return 1.0 / decimal_odds


def multiply_odds(values: list[float]) -> float:
    if not values:
        return 1.0
    if any(v <= 1.0 or not math.isfinite(v) for v in values):
        raise ValueError("Todas las cuotas deben ser mayores que 1")
    return reduce(mul, values, 1.0)


def remove_vig(probabilities: list[float]) -> list[float]:
    total = sum(probabilities)
    if total <= 0:
        return probabilities
    return [p / total for p in probabilities]


def fmt_decimal(value: float) -> str:
    return f"{value:.2f}"


def fmt_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


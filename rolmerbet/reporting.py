from __future__ import annotations

from collections import Counter

from .domain import Evaluation


REJECTION_LABELS = {
    "fuente_no_disponible": "sin fuente estadística",
    "sin_modelo": "mercado sin datos interpretables",
    "muestra_insuficiente": "muestra insuficiente",
    "evidencia_insuficiente": "calidad de evidencia insuficiente",
    "probabilidad_insuficiente": "probabilidad prudente insuficiente",
    "cuota_demasiado_baja": "cuota demasiado baja",
    "cuota_demasiado_alta": "cuota fuera del perfil conservador",
    "precio_desfavorable": "precio desfavorable",
    "alineacion_no_confirmada": "alineación sin confirmar",
    "bajas_no_verificadas": "bajas o sanciones sin verificar",
    "fuentes_en_conflicto": "fuentes en conflicto",
    "rotacion_alta": "riesgo alto de rotación",
}


def diagnostic_report(evaluations: list[Evaluation]) -> dict[str, object]:
    """Resume el cuello de botella sin modificar ninguna decisión del motor."""
    active_sources = sorted({source for item in evaluations for source in item.sources})
    warnings = sorted({warning.strip() for item in evaluations
                       for warning in item.source_warnings if warning.strip()})
    counts = Counter(code for item in evaluations
                     for code in set(item.rejection_codes))
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    reasons = [(REJECTION_LABELS.get(code, code), count) for code, count in ranked]
    viable = sum(item.presentation_tier in {"COMBINADA", "VIABLE"} for item in evaluations)
    alternatives = sum(item.presentation_tier == "ALTERNATIVA" for item in evaluations)
    discarded = sum(item.presentation_tier == "DESCARTADA" for item in evaluations)
    return {
        "active_sources": active_sources,
        "warnings": warnings,
        "reasons": reasons,
        "viable": viable,
        "alternatives": alternatives,
        "discarded": discarded,
    }


def diagnostic_text(evaluations: list[Evaluation], max_reasons: int = 5) -> tuple[str, str]:
    report = diagnostic_report(evaluations)
    active = ", ".join(report["active_sources"]) or "ninguna"
    reasons = report["reasons"][:max_reasons]
    reason_text = " · ".join(f"{label}: {count}" for label, count in reasons)
    warnings = report["warnings"]
    warning_text = " | ".join(warnings[:3]) if warnings else "Sin errores reportados por las fuentes."
    title = (f"Diagnóstico: {report['viable']} viables · {report['alternatives']} alternativas · "
             f"{report['discarded']} descartadas")
    detail = (f"Fuentes activas: {active}. Principales bloqueos: {reason_text or 'ninguno'}. "
              f"Fuentes/avisos: {warning_text} "
              "Un mercado puede aparecer en más de un bloqueo.")
    return title, detail


from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


TASK_NAME = "RolmerBet_Analisis_Diario"


def install_daily(hour: str = "08:00") -> str:
    if os.name != "nt":
        raise RuntimeError("La programación automática solo está disponible en Windows.")
    root = Path(__file__).resolve().parent.parent
    launcher = root / "RolmerBet.pyw"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else Path(sys.executable)
    action = f'"{executable}" "{launcher}" --auto'
    result = subprocess.run(
        ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", action,
         "/SC", "DAILY", "/ST", hour, "/F"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "No se pudo crear la tarea.")
    return f"Tarea diaria creada para las {hour}, según la hora local de Windows."


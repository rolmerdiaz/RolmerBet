# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


PROTECTED_ROOTS = {"data", "diagnostics", ".venv", ".git"}


def log(root: Path, message: str) -> None:
    folder = root / "diagnostics"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "update.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


def wait_for_process(pid: int, seconds: int = 30) -> None:
    if os.name != "nt":
        time.sleep(1.5)
        return
    for _ in range(seconds * 4):
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, creationflags=0x08000000,
        )
        if str(pid) not in result.stdout:
            return
        time.sleep(0.25)


def safe_path(root: Path, relative: str) -> Path:
    destination = (root / relative).resolve()
    if root.resolve() not in destination.parents:
        raise RuntimeError(f"Ruta insegura: {relative}")
    if Path(relative).parts[0] in PROTECTED_ROOTS:
        raise RuntimeError(f"Carpeta protegida: {relative}")
    return destination


def install(plan_path: Path) -> None:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    root = Path(plan["root"]).resolve()
    staging = Path(plan["staging"]).resolve()
    files = [str(item) for item in plan["files"]]
    version = str(plan["version"])
    wait_for_process(int(plan["pid"]))

    backup = root / ".update_backup"
    shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    try:
        for relative in files:
            source = safe_path(staging, relative)
            destination = safe_path(root, relative)
            if not source.is_file():
                raise RuntimeError(f"Falta el archivo descargado: {relative}")
            if destination.exists():
                previous = backup / relative
                previous.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, previous)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".updating")
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
            installed.append(relative)
        log(root, f"Actualización {version} instalada: {len(installed)} archivos.")
    except Exception as exc:
        for relative in reversed(installed):
            destination = safe_path(root, relative)
            previous = backup / relative
            if previous.exists():
                shutil.copy2(previous, destination)
        log(root, f"Actualización cancelada y restaurada: {exc}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)

    launcher = root / "RolmerBet.pyw"
    subprocess.Popen([sys.executable, str(launcher)], cwd=str(root), close_fds=True)


if __name__ == "__main__" and len(sys.argv) == 2:
    try:
        install(Path(sys.argv[1]))
    except Exception:
        pass


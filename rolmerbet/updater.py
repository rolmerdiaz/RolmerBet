from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable


ROOT = Path(__file__).resolve().parent.parent
VERSION_PATH = ROOT / "VERSION.txt"
MANIFEST_URL = "https://raw.githubusercontent.com/rolmerdiaz/RolmerBet/main/version.json"
RAW_PREFIX = "https://raw.githubusercontent.com/rolmerdiaz/RolmerBet/main/"
PROTECTED_ROOTS = {"data", "diagnostics", ".venv", ".git"}


class UpdateError(RuntimeError):
    pass


@dataclass(slots=True)
class UpdateInfo:
    version: str
    notes: str
    files: dict[str, str]


def current_version() -> str:
    try:
        return VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.fullmatch(r"v?(\d+(?:\.\d+){1,3})", value.strip())
    if not match:
        raise UpdateError(f"Versión inválida: {value!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate: str, installed: str | None = None) -> bool:
    installed = installed or current_version()
    left, right = version_tuple(candidate), version_tuple(installed)
    size = max(len(left), len(right))
    return left + (0,) * (size - len(left)) > right + (0,) * (size - len(right))


def _safe_relative(path_text: str) -> str:
    path = PurePosixPath(path_text)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise UpdateError(f"Ruta de actualización insegura: {path_text}")
    if path.parts[0] in PROTECTED_ROOTS:
        raise UpdateError(f"La actualización intentó modificar una carpeta protegida: {path_text}")
    return path.as_posix()


def parse_manifest(payload: dict) -> UpdateInfo:
    if payload.get("repository") != "rolmerdiaz/RolmerBet":
        raise UpdateError("El manifiesto no pertenece al repositorio oficial de RolmerBet.")
    version = str(payload.get("version", ""))
    version_tuple(version)
    raw_files = payload.get("files")
    if not isinstance(raw_files, dict) or not raw_files:
        raise UpdateError("El manifiesto de actualización no contiene archivos.")
    files: dict[str, str] = {}
    for raw_path, raw_hash in raw_files.items():
        path = _safe_relative(str(raw_path))
        digest = str(raw_hash).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise UpdateError(f"Firma SHA-256 inválida para {path}")
        files[path] = digest
    return UpdateInfo(version=version, notes=str(payload.get("notes", "")), files=files)


def _read_url(url: str, timeout: int = 15) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "RolmerBet-Updater"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"No se pudo conectar con GitHub: {exc}") from exc


def check_for_update() -> UpdateInfo | None:
    try:
        payload = json.loads(_read_url(MANIFEST_URL).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("GitHub devolvió un manifiesto inválido.") from exc
    info = parse_manifest(payload)
    return info if is_newer(info.version) else None


def download_update(info: UpdateInfo, progress: Callable[[str], None] | None = None) -> Path:
    progress = progress or (lambda _message: None)
    staging = Path(tempfile.mkdtemp(prefix=f"rolmerbet-{info.version}-"))
    try:
        for index, (relative, expected) in enumerate(info.files.items(), 1):
            progress(f"Descargando {index}/{len(info.files)}: {relative}")
            data = _read_url(RAW_PREFIX + relative)
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                raise UpdateError(f"La firma de {relative} no coincide. No se instaló nada.")
            destination = staging / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        plan = {
            "version": info.version,
            "root": str(ROOT),
            "staging": str(staging),
            "files": list(info.files),
            "pid": os.getpid(),
        }
        plan_path = staging / "update-plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return plan_path
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def launch_installer(plan_path: Path) -> None:
    updater = ROOT / "RolmerBetUpdater.pyw"
    if not updater.exists():
        raise UpdateError("No se encontró RolmerBetUpdater.pyw")
    pythonw = Path(sys.executable)
    subprocess.Popen([str(pythonw), str(updater), str(plan_path)], cwd=str(ROOT),
                     close_fds=True)


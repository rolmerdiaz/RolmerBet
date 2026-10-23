from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_PARTS = {".git", ".venv", "data", "diagnostics", "__pycache__", "tests"}
EXCLUDED_FILES = {"version.json", ".gitignore"}
ALLOWED_SUFFIXES = {".py", ".pyw", ".bat", ".ps1", ".png", ".md", ".txt"}


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return (
        path.is_file()
        and not any(part in EXCLUDED_PARTS for part in relative.parts)
        and path.name not in EXCLUDED_FILES
        and (path.suffix.lower() in ALLOWED_SUFFIXES or path.name == "requirements.txt")
    )


files = {
    path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(ROOT.rglob("*")) if included(path)
}
payload = {
    "repository": "rolmerdiaz/RolmerBet",
    "version": (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip(),
    "notes": ("Nuevo motor conservador por familia de mercado, cruce ESPN/Sofascore, verificación "
              "obligatoria de bajas para resultados y análisis visual jerárquico sin apuestas débiles."),
    "files": files,
}
(ROOT / "version.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)


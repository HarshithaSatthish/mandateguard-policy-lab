from __future__ import annotations

from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".hypothesis",
    ".venv",
    "venv",
    "build",
    "dist",
    "node_modules",
}
EXCLUDED_PREFIXES = ("outputs/generated/", "outputs/demo/")


def shipped_files():
    for path in sorted(ROOT.rglob("*"), key=lambda p: p.relative_to(ROOT).as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative == "SHA256SUMS.txt":
            continue
        parts = path.relative_to(ROOT).parts
        if any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in parts):
            continue
        if relative.startswith(EXCLUDED_PREFIXES) or relative.endswith(".pyc"):
            continue
        yield path, relative


def manifest_text() -> str:
    lines = []
    for path, relative in shipped_files():
        digest = sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}")
    return "\n".join(lines) + "\n"


def main() -> int:
    print(manifest_text(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

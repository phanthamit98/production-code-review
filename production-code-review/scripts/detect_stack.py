#!/usr/bin/env python3
"""Detect the stack of a project and list entry points that receive external input.

Usage:
    python detect_stack.py <project-root>

Prints JSON to stdout:
{
  "root": "...",
  "stacks": ["nextjs", "dotnet"],
  "config_files": [...],
  "protection": {...},          # middleware / pipeline files worth reading first
  "entry_points": [{"kind": "...", "file": "...", "line": N, "detail": "..."}],
  "warnings": [...]
}

Standard library only, so it runs anywhere Python 3.8+ is available.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Iterator

IGNORED_DIRS = {
    "node_modules", ".next", ".git", "bin", "obj", "dist", "build",
    "out", ".vercel", "coverage", ".turbo",
}
MAX_FILE_BYTES = 512 * 1024

HTTP_METHOD_EXPORT = re.compile(
    r"export\s+(?:async\s+)?(?:function|const)\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b"
)
USE_SERVER = re.compile(r"""^\s*['"]use server['"]""", re.MULTILINE)
# Supports primary constructors: `class FooController(AppDbContext db) : ControllerBase`
CONTROLLER_CLASS = re.compile(r"class\s+(\w+)\s*(?:\([^)]*\))?\s*:\s*(?:Controller|ControllerBase)\b")
HTTP_ATTRIBUTE = re.compile(r"\[(Http(?:Get|Post|Put|Patch|Delete))(?:\(\"?([^\")]*)\"?\))?\]")
MINIMAL_API = re.compile(r"\.Map(Get|Post|Put|Patch|Delete|Methods)\s*\(\s*\"([^\"]*)\"")


def iter_files(root: Path, suffixes: tuple[str, ...]) -> Iterator[Path]:
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file() and path.suffix in suffixes and path.stat().st_size <= MAX_FILE_BYTES:
            yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # unreadable file: report, don't crash
        return f"__UNREADABLE__ {exc}"


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def detect_nextjs(root: Path, result: dict) -> None:
    package_json = root / "package.json"
    if not package_json.exists():
        return
    try:
        pkg = json.loads(read_text(package_json))
    except json.JSONDecodeError as exc:
        result["warnings"].append(f"package.json is not valid JSON: {exc}")
        return

    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    if "next" not in deps:
        return

    result["stacks"].append("nextjs")
    result["libraries"].update({k: v for k, v in deps.items() if k in {
        "next", "react", "prisma", "@prisma/client", "zod", "next-auth",
        "drizzle-orm", "stripe", "@clerk/nextjs",
    }})

    for name in ("tsconfig.json", "next.config.js", "next.config.mjs", "next.config.ts", ".env.example"):
        if (root / name).exists():
            result["config_files"].append(name)

    tsconfig = root / "tsconfig.json"
    if tsconfig.exists() and re.search(r'"strict"\s*:\s*false', read_text(tsconfig)):
        result["warnings"].append("tsconfig.json has strict: false")

    for candidate in ("middleware.ts", "middleware.js", "src/middleware.ts", "src/middleware.js"):
        mw = root / candidate
        if mw.exists():
            text = read_text(mw)
            matcher = re.search(r"matcher\s*:\s*(\[[^\]]*\]|['\"][^'\"]*['\"])", text)
            result["protection"]["nextjs_middleware"] = {
                "file": candidate,
                "matcher": matcher.group(1) if matcher else None,
            }

    for path in iter_files(root, (".ts", ".tsx", ".js", ".jsx")):
        rel = path.relative_to(root).as_posix()
        text = read_text(path)

        if re.search(r"(^|/)app/.*route\.(t|j)sx?$", rel):
            for m in HTTP_METHOD_EXPORT.finditer(text):
                result["entry_points"].append({
                    "kind": "route_handler", "file": rel,
                    "line": line_of(text, m.start()), "detail": m.group(1),
                })
        elif re.search(r"(^|/)pages/api/", rel):
            result["entry_points"].append({"kind": "pages_api_route", "file": rel, "line": 1, "detail": ""})

        if USE_SERVER.search(text):
            for m in re.finditer(r"export\s+(?:async\s+)?function\s+(\w+)", text):
                result["entry_points"].append({
                    "kind": "server_action", "file": rel,
                    "line": line_of(text, m.start()), "detail": m.group(1),
                })

        if "dangerouslySetInnerHTML" in text:
            result["hotspots"].append({"file": rel, "pattern": "dangerouslySetInnerHTML"})
        if re.search(r"\$(query|execute)RawUnsafe", text):
            result["hotspots"].append({"file": rel, "pattern": "Prisma raw unsafe query"})


def detect_dotnet(root: Path, result: dict) -> None:
    csprojs = [p for p in iter_files(root, (".csproj",))]
    if not csprojs:
        return

    result["stacks"].append("dotnet")
    for proj in csprojs:
        rel = proj.relative_to(root).as_posix()
        result["config_files"].append(rel)
        text = read_text(proj)
        target = re.search(r"<TargetFramework>([^<]+)</TargetFramework>", text)
        if target:
            result["libraries"][f"{rel}:TargetFramework"] = target.group(1)
        if re.search(r"<Nullable>\s*disable\s*</Nullable>", text) or "<Nullable>" not in text:
            result["warnings"].append(f"{rel}: nullable reference types are not enabled")
        for pkg in re.finditer(r'<PackageReference\s+Include="([^"]+)"\s+Version="([^"]+)"', text):
            result["libraries"][pkg.group(1)] = pkg.group(2)

    for path in iter_files(root, (".cs",)):
        rel = path.relative_to(root).as_posix()
        text = read_text(path)

        if path.name == "Program.cs" or path.name == "Startup.cs":
            pipeline = [m.group(0) for m in re.finditer(r"app\.Use\w+\(", text)]
            result["protection"].setdefault("dotnet_pipeline", []).append({"file": rel, "order": pipeline})
            names = [p[len("app."):-1] for p in pipeline]
            if "UseAuthentication" in names and "UseAuthorization" in names \
                    and names.index("UseAuthorization") < names.index("UseAuthentication"):
                result["warnings"].append(f"{rel}: UseAuthorization() is registered before UseAuthentication()")
            for m in MINIMAL_API.finditer(text):
                result["entry_points"].append({
                    "kind": "minimal_api", "file": rel,
                    "line": line_of(text, m.start()), "detail": f"{m.group(1)} {m.group(2)}",
                })

        controller = CONTROLLER_CLASS.search(text)
        if controller:
            class_authorize = bool(re.search(r"\[Authorize[^\]]*\]\s*(?:\[[^\]]*\]\s*)*public\s+(?:sealed\s+)?class", text))
            result["protection"].setdefault("dotnet_controllers", []).append({
                "file": rel, "class": controller.group(1), "class_level_authorize": class_authorize,
            })
            for m in HTTP_ATTRIBUTE.finditer(text):
                result["entry_points"].append({
                    "kind": "controller_action", "file": rel,
                    "line": line_of(text, m.start()), "detail": f"{m.group(1)} {m.group(2) or ''}".strip(),
                })

        if re.search(r"(FromSqlRaw|ExecuteSqlRaw)\s*\(\s*\$?\"", text):
            result["hotspots"].append({"file": rel, "pattern": "EF raw SQL"})
        if "new HttpClient(" in text:
            result["hotspots"].append({"file": rel, "pattern": "new HttpClient()"})


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: detect_stack.py <project-root>", file=sys.stderr)
        return 2

    root = Path(argv[1]).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    result: dict = {
        "root": str(root), "stacks": [], "libraries": {}, "config_files": [],
        "protection": {}, "entry_points": [], "hotspots": [], "warnings": [],
    }
    for name in ("CLAUDE.md", "README.md", ".editorconfig"):
        if (root / name).exists():
            result["config_files"].append(name)

    detect_nextjs(root, result)
    detect_dotnet(root, result)

    if not result["stacks"]:
        result["warnings"].append(
            "No Next.js or .NET project detected; review with references/core-checklist.md only."
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

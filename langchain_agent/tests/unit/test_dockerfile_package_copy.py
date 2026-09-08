"""
Pre-flight guard: every top-level package actually imported at runtime must
have its own explicit `COPY langchain_agent/<pkg>/ ./<pkg>/` line in the
Dockerfile.

`COPY langchain_agent/*.py ./` only matches top-level .py files, never
directories -- a new top-level package silently doesn't exist in the built
image unless it gets its own COPY line, crashing the app at import time on
boot. This has broken prod twice: `integrations/` (issue #18) and `tools/`
(PR #73's ENABLE_ENRICHMENT_TOOL rollout -- caught live via
"No module named 'tools'" in the enrichment demo, 2026-09-08).
"""

import ast
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = AGENT_ROOT / "Dockerfile"


def _top_level_packages() -> set[str]:
    return {p.name for p in AGENT_ROOT.iterdir() if p.is_dir() and (p / "__init__.py").exists()}


def _runtime_imported_packages(packages: set[str]) -> set[str]:
    imported: set[str] = set()
    candidate_files = (
        list(AGENT_ROOT.glob("*.py"))
        + list(AGENT_ROOT.glob("api/**/*.py"))
        + [f for pkg in packages for f in (AGENT_ROOT / pkg).glob("**/*.py")]
    )
    for f in candidate_files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in packages:
                    imported.add(top)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in packages:
                        imported.add(top)
    return imported


def test_every_runtime_imported_package_has_dockerfile_copy_line():
    packages = _top_level_packages()
    imported = _runtime_imported_packages(packages)

    dockerfile_text = DOCKERFILE.read_text(encoding="utf-8")
    missing = [
        pkg for pkg in imported if f"COPY langchain_agent/{pkg}/ ./{pkg}/" not in dockerfile_text
    ]

    assert not missing, (
        f"Package(s) {missing} are imported at runtime but have no explicit "
        f"COPY line in {DOCKERFILE} -- COPY langchain_agent/*.py only copies "
        "top-level files, not directories, so these would silently be "
        "missing from the built image and crash the app at import time."
    )

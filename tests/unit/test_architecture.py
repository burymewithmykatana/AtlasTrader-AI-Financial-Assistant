import ast
from pathlib import Path

DOMAIN_ROOT = Path(__file__).parents[2] / "src" / "atlas_trader" / "domain"
FORBIDDEN_DEPENDENCIES = (
    "atlas_trader.api",
    "atlas_trader.application",
    "atlas_trader.config",
    "atlas_trader.infrastructure",
)


def test_domain_does_not_import_outer_layers() -> None:
    violations: list[str] = []
    for path in DOMAIN_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.startswith(FORBIDDEN_DEPENDENCIES):
                    violations.append(f"{path.name}: {module}")

    assert violations == []


def test_domain_has_no_vendor_specific_nobitex_reference() -> None:
    references = [
        str(path.relative_to(DOMAIN_ROOT))
        for path in DOMAIN_ROOT.rglob("*.py")
        if "nobitex" in path.read_text(encoding="utf-8").lower()
    ]

    assert references == []

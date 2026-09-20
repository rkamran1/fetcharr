"""The backend structure rules from CLAUDE.md ("Backend structure"), checked by parsing the source.

Nothing under ``app/`` is imported here: every check reads the AST. Every package under
``app/`` is a domain unless it is listed in LIBRARY_PACKAGES or INFRA_PACKAGES; adding a
library package means changing that set and CLAUDE.md together.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"

LIBRARY_PACKAGES = {"ytdlp", "library"}
INFRA_PACKAGES = {"db"}
DOMAIN_MODULES = {
    "__init__.py",
    "router.py",
    "schemas.py",
    "service.py",
    "models.py",
    "dependencies.py",
    "exceptions.py",
    "constants.py",
    "utils.py",
}
#: The documented exceptions in CLAUDE.md -> Backend structure ("Extra modules").
EXTRA_MODULES = {"jobs": {"pipeline.py", "manager.py"}}
FASTAPI = ("fastapi", "starlette")


def _packages() -> list[str]:
    return sorted(p.name for p in APP.iterdir() if (p / "__init__.py").is_file())


def _domains() -> list[str]:
    return [p for p in _packages() if p not in LIBRARY_PACKAGES | INFRA_PACKAGES]


def _modules(package: str) -> list[Path]:
    return sorted((APP / package).rglob("*.py"))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _imports(path: Path) -> Iterator[str]:
    """Every imported module name; ``from a.b import c`` yields ``a.b`` and ``a.b.c``."""
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def _matches(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(f"{prefix}.")


def _bad_imports(path: Path, forbidden: list[str]) -> list[str]:
    return sorted({n for n in _imports(path) if any(_matches(n, f) for f in forbidden)})


def _rel(path: Path) -> str:
    return str(path.relative_to(APP.parent))


def _base_names(node: ast.ClassDef) -> set[str]:
    names = set()
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def _classes() -> list[tuple[Path, ast.ClassDef]]:
    return [
        (path, node)
        for path in sorted(APP.rglob("*.py"))
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ClassDef)
    ]


def _subclasses_of(roots: set[str]) -> list[tuple[Path, ast.ClassDef]]:
    """Classes deriving (directly or through each other, by name) from one of ``roots``."""
    classes = _classes()
    names = set(roots)
    while True:
        found = {node.name for _, node in classes if _base_names(node) & names}
        if found <= names:
            break
        names |= found
    return [(path, node) for path, node in classes if _base_names(node) & names]


def test_domain_packages_have_expected_files() -> None:
    expected = {
        "events": {"router.py", "schemas.py", "service.py", "dependencies.py"},
        "jobs": {
            "router.py",
            "schemas.py",
            "service.py",
            "models.py",
            "dependencies.py",
            "exceptions.py",
            "constants.py",
            "utils.py",
            "pipeline.py",
            "manager.py",
        },
        "requests": {
            "router.py",
            "schemas.py",
            "service.py",
            "models.py",
            "dependencies.py",
            "exceptions.py",
        },
        "system": {"router.py", "schemas.py", "service.py", "dependencies.py", "utils.py"},
        "auth": {
            "router.py",
            "schemas.py",
            "service.py",
            "models.py",
            "dependencies.py",
            "exceptions.py",
            "utils.py",
        },
        "inspections": {
            "router.py",
            "schemas.py",
            "service.py",
            "models.py",
            "dependencies.py",
            "exceptions.py",
            "utils.py",
        },
    }
    for domain, files in expected.items():
        assert {p.name for p in (APP / domain).glob("*.py")} == files | {"__init__.py"}, domain

    removed = [
        "api",
        "db/models.py",
        "auth/deps.py",
        "auth/passwords.py",
        "auth/sessions.py",
        "auth/ratelimit.py",
        "ytdlp/options.py",
    ]
    assert [r for r in removed if (APP / r).exists()] == []


def test_only_allowed_module_names() -> None:
    offenders = [
        _rel(path)
        for domain in _domains()
        for path in _modules(domain)
        if path.parent != APP / domain
        or path.name not in DOMAIN_MODULES | EXTRA_MODULES.get(domain, set())
    ]

    assert offenders == []


def test_router_layering() -> None:
    domains = _domains()
    offenders = {}
    for domain in domains:
        router = APP / domain / "router.py"
        if not router.is_file():
            continue
        other_services = [f"app.{d}.service" for d in domains if d != domain]
        forbidden = ["sqlalchemy", "app.db", "asyncio.subprocess", *other_services]
        if bad := _bad_imports(router, forbidden):
            offenders[_rel(router)] = bad

    assert offenders == {}


def test_service_layering() -> None:
    offenders = {
        _rel(service): bad
        for domain in _domains()
        if (service := APP / domain / "service.py").is_file()
        if (bad := _bad_imports(service, list(FASTAPI)))
    }

    assert offenders == {}


def test_library_layering() -> None:
    forbidden = [*FASTAPI, *(f"app.{d}" for d in _domains())]
    offenders = {
        _rel(path): bad
        for package in sorted(LIBRARY_PACKAGES)
        for path in _modules(package)
        if (bad := _bad_imports(path, forbidden))
    }

    assert offenders == {}


def test_schemas_only_in_schemas_modules() -> None:
    offenders = [
        f"{_rel(path)}::{node.name}"
        for path, node in _subclasses_of({"BaseModel", "RootModel"})
        if path.name != "schemas.py"
    ]

    assert offenders == []


def test_models_registered() -> None:
    models = _subclasses_of({"Base"})
    misplaced = [
        f"{_rel(path)}::{node.name}"
        for path, node in models
        if path.name != "models.py" or path.parent.name not in _domains()
    ]
    registered = set(_imports(APP / "db" / "registry.py"))
    unregistered = sorted(
        module
        for path, _ in models
        if (module := f"app.{path.parent.name}.models") not in registered
    )

    assert models, "no SQLAlchemy models found"
    assert misplaced == []
    assert unregistered == []

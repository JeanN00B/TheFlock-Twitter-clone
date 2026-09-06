import ast
from pathlib import Path


AUTH_ROOT = Path(__file__).parents[3] / "app" / "auth"
FORBIDDEN_IMPORTS = {
    "app.users.infrastructure",
    "sqlalchemy",
    "fastapi",
    "pydantic",
    "psycopg",
    "pwdlib",
}
FORBIDDEN_TEXT = {"UserModel", "SQLAlchemyUserRepository"}


def test_auth_domain_and_application_have_only_inward_capability_imports() -> None:
    checked = [
        *((AUTH_ROOT / "domain").glob("*.py")),
        *((AUTH_ROOT / "application").glob("*.py")),
    ]

    assert {path.name for path in checked} >= {"session.py", "login.py"}
    for path in checked:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        assert not any(
            name == forbidden or name.startswith(f"{forbidden}.")
            for name in imported
            for forbidden in FORBIDDEN_IMPORTS
        ), path
        assert not any(text in source for text in FORBIDDEN_TEXT), path

import ast
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, StrictStr

from app.main import registration_request_validation_handler


AUTH_ROOT = Path(__file__).parents[3] / "app" / "auth"
COMPOSITION_PATH = AUTH_ROOT.parent / "composition.py"
MAIN_PATH = AUTH_ROOT.parent / "main.py"
FORBIDDEN_IMPORTS = {
    "app.users.infrastructure",
    "sqlalchemy",
    "fastapi",
    "pydantic",
    "psycopg",
    "pwdlib",
}
FORBIDDEN_TEXT = {"UserModel", "SQLAlchemyUserRepository"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
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
    return imported


def test_auth_domain_application_and_infrastructure_never_import_users_infrastructure() -> None:
    checked = [*AUTH_ROOT.rglob("*.py")]

    assert {path.name for path in checked} >= {
        "session.py",
        "login.py",
        "login_router.py",
    }
    for path in checked:
        imported = _imports(path)
        assert not any(
            name == "app.users.infrastructure"
            or name.startswith("app.users.infrastructure.")
            for name in imported
        ), path
        if path.parent.name in {"domain", "application"}:
            assert not any(
                name == forbidden or name.startswith(f"{forbidden}.")
                for name in imported
                for forbidden in FORBIDDEN_IMPORTS
            ), path
            assert not any(text in path.read_text() for text in FORBIDDEN_TEXT), path


def test_composition_is_the_explicit_cross_capability_wiring_root() -> None:
    imported = _imports(COMPOSITION_PATH)

    assert "app.users.infrastructure.credential_lookup" in imported
    assert "app.users.infrastructure.registration_support" in imported
    assert "app.users.infrastructure.public_user_lookup" in imported
    assert "app.auth.application.session_access" in imported
    assert "app.auth.infrastructure.login_router" in imported
    assert "app.auth.infrastructure.session_router" in imported
    assert "app.auth.infrastructure.session_store" in imported
    assert "app.auth.infrastructure.session_tokens" in imported
    assert "app.infrastructure.database" in imported
    assert "app.core.settings" in imported


def test_main_composes_login_and_keeps_origin_middleware_at_the_edge() -> None:
    imported = _imports(MAIN_PATH)
    source = MAIN_PATH.read_text()

    assert "app.auth.application.session_access" in imported
    assert "app.composition" in imported
    assert "app.auth.infrastructure.origin_middleware" in imported
    assert "app.users.infrastructure.registration_router" in imported
    assert "app.include_router(login_router)" in source
    assert "app.include_router(session_router)" in source
    assert "Unauthenticated" in source
    assert "LoginOriginMiddleware" in source
    assert "CORSMiddleware" in source


class ValidationProbe(BaseModel):
    value: StrictStr


def test_probe_validation_keeps_fastapi_stock_shape_elsewhere() -> None:
    probe_app = FastAPI()
    probe_app.add_exception_handler(
        RequestValidationError, registration_request_validation_handler
    )

    @probe_app.post("/probe")
    def probe(payload: ValidationProbe):
        return payload

    with TestClient(probe_app) as client:
        response = client.post("/probe", json={"value": 42})

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "string_type",
                "loc": ["body", "value"],
                "msg": "Input should be a valid string",
                "input": 42,
            }
        ]
    }

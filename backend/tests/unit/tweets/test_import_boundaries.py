import ast
import importlib
from pathlib import Path


FORBIDDEN = {
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "alembic",
    "psycopg",
    "app.auth",
    "app.users.infrastructure",
}


def test_domain_and_application_sources_have_inward_only_imports() -> None:
    files = [Path("app/tweets/domain/tweet.py"), *Path("app/tweets/application").glob("*.py")]
    violations: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for name in imported:
                if any(name == blocked or name.startswith(f"{blocked}.") for blocked in FORBIDDEN):
                    violations.append(f"{path}:{node.lineno}: {name}")
    assert violations == []


def test_domain_and_application_modules_import_without_frameworks() -> None:
    modules = [
        "app.tweets.domain.tweet",
        "app.tweets.application.errors",
        "app.tweets.application.ports",
        "app.tweets.application.create_tweet",
        "app.tweets.application.list_tweet_feed",
        "app.tweets.application.delete_tweet",
    ]
    for module in modules:
        importlib.import_module(module)

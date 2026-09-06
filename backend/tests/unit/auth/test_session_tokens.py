import ast
import inspect

import pytest

from app.auth.application.login import RawSessionToken
from app.auth.domain.session import SessionTokenDigest
from app.auth.infrastructure.session_tokens import (
    SecretsSessionTokenGenerator,
    Sha256SessionTokenHasher,
)


RAW_TOKEN = b"r" * 32


def test_generator_requests_one_redacted_32_byte_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[int] = []

    def token_bytes(size: int) -> bytes:
        requested.append(size)
        return RAW_TOKEN

    monkeypatch.setattr(
        "app.auth.infrastructure.session_tokens.secrets.token_bytes", token_bytes
    )

    token = SecretsSessionTokenGenerator().generate()

    assert requested == [32]
    assert isinstance(token, RawSessionToken)
    assert token.as_bytes() == RAW_TOKEN
    assert RAW_TOKEN.hex() not in repr(token)


@pytest.mark.parametrize(
    ("raw_bytes", "expected_hex"),
    [
        (
            b"\x00" * 32,
            "66687aadf862bd776c8fc18b8e9f8e20089714856ee233b3902a591d0d5f2925",
        ),
        (
            b"a" * 32,
            "3ba3f5f43b92602683c19aee62a20342b084dd5971ddd33808d81a328879a547",
        ),
    ],
)
def test_sha256_hasher_returns_the_exact_32_byte_digest_for_known_vectors(
    raw_bytes: bytes, expected_hex: str
) -> None:
    digest = Sha256SessionTokenHasher().digest(RawSessionToken(raw_bytes))

    assert isinstance(digest, SessionTokenDigest)
    assert len(digest.value) == 32
    assert digest.value.hex() == expected_hex


def test_cryptographic_adapters_do_not_log_inputs_or_results() -> None:
    from app.auth.infrastructure import session_tokens

    tree = ast.parse(inspect.getsource(session_tokens))

    assert not any(
        isinstance(node, ast.Import)
        and any(alias.name == "logging" for alias in node.names)
        for node in tree.body
    )
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "logging"
        for node in tree.body
    )
    assert "getLogger" not in inspect.getsource(session_tokens)


def test_generator_returns_independent_tokens_and_requests_32_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[int] = []
    generated = iter((b"a" * 32, b"b" * 32))

    def token_bytes(size: int) -> bytes:
        requested.append(size)
        return next(generated)

    monkeypatch.setattr(
        "app.auth.infrastructure.session_tokens.secrets.token_bytes", token_bytes
    )

    generator = SecretsSessionTokenGenerator()
    first = generator.generate()
    second = generator.generate()

    assert requested == [32, 32]
    assert first.as_bytes() == b"a" * 32
    assert second.as_bytes() == b"b" * 32
    assert first.as_bytes() != second.as_bytes()
    assert (b"a" * 32).hex() not in repr(first)
    assert (b"b" * 32).hex() not in repr(second)

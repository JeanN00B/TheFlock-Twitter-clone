"""FastAPI adapter for the protected current-user session contract."""

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, field_serializer
from starlette.responses import JSONResponse

from app.auth.application.session_access import SessionAccess
from app.auth.infrastructure.session_cookie import clear_session_cookie
from app.auth.infrastructure.session_dependency import (
    build_current_user_dependency,
    revoke_current_session,
)
from app.users.domain.user import PublicUser


class CurrentUserResponse(BaseModel):
    """The credential-free public representation returned by ``/auth/me``."""

    id: UUID
    email: str
    username: str
    display_name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")

    @field_serializer("created_at", "updated_at")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @classmethod
    def from_public_user(cls, user: PublicUser) -> "CurrentUserResponse":
        """Map only the public-user fields into the transport model."""

        return cls(
            id=user.id,
            email=user.email,
            username=user.username,
            display_name=user.display_name,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


PublicUserResponse = CurrentUserResponse


def _internal_error_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": {"code": "internal_error"}},
    )


def build_session_router(
    session_access_provider: Callable[..., SessionAccess],
    cookie_security_provider: Callable[..., bool],
) -> APIRouter:
    """Build protected routes from explicit request-scoped application providers."""

    session_router = APIRouter(prefix="/auth")
    current_user_dependency = build_current_user_dependency(session_access_provider)

    @session_router.get("/me", response_model=CurrentUserResponse)
    def me(
        user: PublicUser = Depends(current_user_dependency),
    ) -> CurrentUserResponse:
        """Return the current credential-free public user."""

        return CurrentUserResponse.from_public_user(user)

    @session_router.post(
        "/logout",
        response_model=None,
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def logout(
        request: Request,
        session_access: SessionAccess = Depends(session_access_provider),
        secure_cookie: bool = Depends(cookie_security_provider),
    ) -> Response:
        """Revoke the current session when present and always clear its cookie."""

        try:
            revoke_current_session(request, session_access)
        except Exception:
            response = _internal_error_response()
            clear_session_cookie(response, secure=secure_cookie)
            return response

        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        clear_session_cookie(response, secure=secure_cookie)
        return response

    return session_router

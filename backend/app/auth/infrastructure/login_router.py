"""FastAPI adapter for the credential-free login contract."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, StrictStr
from starlette.responses import JSONResponse

from app.auth.application.login import (
    CommittedSessionCookie,
    InvalidCredentials,
    Login,
    LoginCommand,
    LoginValidationError,
)

from .session_cookie import write_session_cookie


class LoginRequest(BaseModel):
    """Exactly the two strict string values accepted by login."""

    email: StrictStr
    password: StrictStr

    model_config = ConfigDict(extra="forbid")


def _error_response(status_code: int, content: dict[str, object]) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=content)


def build_login_router(
    login_provider: Callable[..., Login],
    cookie_security_provider: Callable[..., bool],
) -> APIRouter:
    """Build the login router from explicit application and cookie providers."""

    login_router = APIRouter(prefix="/auth")

    @login_router.post(
        "/login",
        response_model=None,
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def login(
        request: LoginRequest,
        login_use_case: Login = Depends(login_provider),
        secure_cookie: bool = Depends(cookie_security_provider),
    ) -> Response:
        """Verify credentials and write a cookie only after durable commit."""

        try:
            committed_cookie = login_use_case.execute(
                LoginCommand(email=request.email, password=request.password)
            )
        except LoginValidationError as error:
            return _error_response(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {
                    "error": {
                        "code": "validation_error",
                        "fields": error.fields,
                    }
                },
            )
        except InvalidCredentials:
            return _error_response(
                status.HTTP_401_UNAUTHORIZED,
                {"error": {"code": "invalid_credentials"}},
            )
        except Exception:
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                {"error": {"code": "internal_error"}},
            )

        try:
            response = Response(status_code=status.HTTP_204_NO_CONTENT)
            write_session_cookie(
                response, committed_cookie, secure=secure_cookie
            )
        except Exception:
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                {"error": {"code": "internal_error"}},
            )

        return response

    return login_router

"""FastAPI adapter for Users registration."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictStr, field_serializer
from sqlalchemy.orm import Session

from app.infrastructure.database import get_db
from app.users.application.register_user import (
    RegisterUser,
    RegisterUserCommand,
    RegistrationConflict,
    RegistrationValidationError,
)
from app.users.infrastructure.registration_support import (
    SystemClock,
    Uuid4Generator,
    get_password_hasher,
)
from app.users.infrastructure.user_repository import SQLAlchemyUserRepository


class RegistrationRequest(BaseModel):
    """Exactly the four strict string values accepted by registration."""

    email: StrictStr
    username: StrictStr
    display_name: StrictStr
    password: StrictStr

    model_config = ConfigDict(extra="forbid")


class RegistrationResponse(BaseModel):
    """The credential-free public registration representation."""

    id: UUID
    username: str
    display_name: str
    email: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")

    @field_serializer("created_at", "updated_at")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


router = APIRouter(prefix="/auth")


def build_register_user(session: Session) -> RegisterUser:
    """Compose registration from a request-scoped session and Users adapters."""

    return RegisterUser(
        repository=SQLAlchemyUserRepository(session),
        password_hasher=get_password_hasher(),
        public_id_generator=Uuid4Generator(),
        clock=SystemClock(),
    )


def get_register_user(session: Session = Depends(get_db)) -> RegisterUser:
    """Provide one composed registration use case per request."""

    return build_register_user(session)


def _error_response(status_code: int, code: str, fields: dict[str, str]) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "fields": fields}},
    )


@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    request: RegistrationRequest,
    register_user: RegisterUser = Depends(get_register_user),
) -> RegistrationResponse:
    """Register a user without creating authentication state."""

    try:
        user = register_user.execute(
            RegisterUserCommand(
                email=request.email,
                username=request.username,
                display_name=request.display_name,
                password=request.password,
            )
        )
    except RegistrationValidationError as error:
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            error.fields,
        )
    except RegistrationConflict as error:
        return _error_response(
            status.HTTP_409_CONFLICT,
            "conflict",
            {field: "already_exists" for field in sorted(error.fields)},
        )

    return RegistrationResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )

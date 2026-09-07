"""theFlock-twitter API composition root."""

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth.infrastructure.origin_middleware import LoginOriginMiddleware
from app.composition import login_router
from app.core.settings import get_frontend_origin
from app.users.infrastructure.registration_router import router as registration_router

# Browser origin for host `pnpm dev` / Compose frontend (credentials: include).
_FRONTEND_ORIGIN = get_frontend_origin()


app = FastAPI(title="theFlock-twitter API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# This is outermost, so login origin denial happens before CORS or dependencies.
app.add_middleware(
    LoginOriginMiddleware,
    allowed_origins=(_FRONTEND_ORIGIN,),
)
app.include_router(registration_router)
app.include_router(login_router)


def _registration_validation_fields(error: RequestValidationError) -> dict[str, str]:
    fields: dict[str, str] = {}
    for detail in error.errors():
        location = detail.get("loc", ())
        if location and location[0] == "body":
            location = location[1:]
        field = (
            "body"
            if not location or not isinstance(location[0], str)
            else location[0]
        )
        fields[field] = "invalid"
    return fields


@app.exception_handler(RequestValidationError)
async def registration_request_validation_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    if request.url.path not in {"/auth/register", "/auth/login"}:
        return await request_validation_exception_handler(request, error)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": {
                "code": "validation_error",
                "fields": _registration_validation_fields(error),
            }
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

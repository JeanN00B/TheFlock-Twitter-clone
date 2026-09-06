"""theFlock-twitter API composition root."""

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.users.infrastructure.registration_router import router as registration_router

app = FastAPI(title="theFlock-twitter API")
app.include_router(registration_router)


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
    if request.url.path != "/auth/register":
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

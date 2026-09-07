"""FastAPI transport adapter for authenticated tweet creation."""

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictStr, field_serializer

from app.tweets.application.create_tweet import CreateTweet, CreateTweetCommand
from app.tweets.application.errors import TweetValidationError
from app.tweets.domain.tweet import PublicTweet
from app.users.domain.user import PublicUser


class CreateTweetRequest(BaseModel):
    text: StrictStr

    model_config = ConfigDict(extra="forbid")


class AuthorResponse(BaseModel):
    id: UUID
    username: str
    display_name: str

    model_config = ConfigDict(extra="forbid")


class TweetResponse(BaseModel):
    id: UUID
    text: str
    created_at: datetime
    author: AuthorResponse

    model_config = ConfigDict(extra="forbid")

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )


def _validation_response(fields: dict[str, str]) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"error": {"code": "validation_error", "fields": fields}},
    )


def _to_response(tweet: PublicTweet) -> TweetResponse:
    return TweetResponse(
        id=tweet.id,
        text=tweet.text,
        created_at=tweet.created_at,
        author=AuthorResponse(
            id=tweet.author.id,
            username=tweet.author.username,
            display_name=tweet.author.display_name,
        ),
    )


def build_tweet_router(
    create_provider: Callable[..., CreateTweet],
    current_user_dependency: Callable[..., PublicUser],
) -> APIRouter:
    """Build only the create endpoint; feed and deletion are later work units."""

    router = APIRouter(prefix="/tweets")

    @router.post("", response_model=TweetResponse, status_code=status.HTTP_201_CREATED)
    def create_tweet(
        request: CreateTweetRequest,
        actor: PublicUser = Depends(current_user_dependency),
        use_case: CreateTweet = Depends(create_provider),
    ) -> TweetResponse | JSONResponse:
        try:
            tweet = use_case.execute(
                CreateTweetCommand(
                    text=request.text,
                    author_id=actor.id,
                    author_username=actor.username,
                    author_display_name=actor.display_name,
                )
            )
        except TweetValidationError as error:
            return _validation_response({field: "invalid" for field in error.fields})
        return _to_response(tweet)

    return router

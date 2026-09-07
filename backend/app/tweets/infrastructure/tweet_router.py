"""FastAPI transport adapter for authenticated tweet creation and feed."""

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictStr, field_serializer

from app.tweets.application.create_tweet import CreateTweet, CreateTweetCommand
from app.tweets.application.errors import InvalidFeedCursor, TweetValidationError
from app.tweets.application.list_tweet_feed import ListTweetFeed, ListTweetFeedQuery
from app.tweets.domain.tweet import PublicTweet
from app.tweets.infrastructure.cursor import decode_cursor, encode_cursor
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
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class TweetFeedResponse(BaseModel):
    items: list[TweetResponse]
    next_cursor: str | None
    model_config = ConfigDict(extra="forbid")


def _validation_response(fields: dict[str, str]) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "fields": fields}})


def _to_response(tweet: PublicTweet) -> TweetResponse:
    return TweetResponse(
        id=tweet.id, text=tweet.text, created_at=tweet.created_at,
        author=AuthorResponse(id=tweet.author.id, username=tweet.author.username, display_name=tweet.author.display_name),
    )


def build_tweet_router(
    create_provider: Callable[..., CreateTweet],
    list_provider: Callable[..., ListTweetFeed],
    current_user_dependency: Callable[..., PublicUser],
) -> APIRouter:
    router = APIRouter(prefix="/tweets")

    @router.post("", response_model=TweetResponse, status_code=status.HTTP_201_CREATED)
    def create_tweet(
        request: CreateTweetRequest,
        actor: PublicUser = Depends(current_user_dependency),
        use_case: CreateTweet = Depends(create_provider),
    ) -> TweetResponse | JSONResponse:
        try:
            tweet = use_case.execute(CreateTweetCommand(
                text=request.text, author_id=actor.id,
                author_username=actor.username, author_display_name=actor.display_name,
            ))
        except TweetValidationError as error:
            return _validation_response({field: "invalid" for field in error.fields})
        return _to_response(tweet)

    @router.get("", response_model=TweetFeedResponse)
    def list_tweets(
        request: Request,
        _actor: PublicUser = Depends(current_user_dependency),
        use_case: ListTweetFeed = Depends(list_provider),
    ) -> TweetFeedResponse | JSONResponse:
        values = request.query_params.getlist("page_size")
        if not values:
            page_size = 20
        elif len(values) != 1 or not values[0].isascii() or not values[0].isdigit() or str(int(values[0])) != values[0]:
            return _validation_response({"page_size": "invalid"})
        else:
            page_size = int(values[0])
            if not 1 <= page_size <= 50:
                return _validation_response({"page_size": "invalid"})

        cursors = request.query_params.getlist("cursor")
        if len(cursors) > 1 or (cursors and not cursors[0]):
            return _validation_response({"cursor": "invalid"})
        try:
            before = decode_cursor(cursors[0]) if cursors else None
        except InvalidFeedCursor:
            return _validation_response({"cursor": "invalid"})
        page = use_case.execute(ListTweetFeedQuery(page_size, before))
        return TweetFeedResponse(
            items=[_to_response(item) for item in page.items],
            next_cursor=encode_cursor(page.next_cursor) if page.next_cursor else None,
        )

    return router

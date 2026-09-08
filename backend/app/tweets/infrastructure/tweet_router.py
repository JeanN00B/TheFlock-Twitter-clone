"""FastAPI transport adapter for authenticated tweet creation and feed."""

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, StrictStr, field_serializer

from app.tweets.application.create_tweet import CreateTweet, CreateTweetCommand
from app.tweets.application.delete_tweet import DeleteTweet, DeleteTweetCommand
from app.tweets.application.errors import InvalidFeedCursor, TweetForbidden, TweetNotFound, TweetValidationError
from app.tweets.application.list_tweet_feed import ListTweetFeed, ListTweetFeedQuery
from app.tweets.application.ports import FeedKind, FeedScope
from app.tweets.application.set_like_state import SetLikeState, SetLikeStateCommand
from app.tweets.domain.tweet import PublicTweet
from app.tweets.infrastructure.cursor import decode_cursor, encode_cursor
from app.users.domain.user import PublicUser, canonicalize_username


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
    like_count: int
    liked_by_actor: bool
    model_config = ConfigDict(extra="forbid")

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class TweetFeedResponse(BaseModel):
    items: list[TweetResponse]
    next_cursor: str | None
    model_config = ConfigDict(extra="forbid")


class LikeStateResponse(BaseModel):
    tweet_id: UUID
    like_count: int
    liked_by_actor: bool
    model_config = ConfigDict(extra="forbid")


def _validation_response(fields: dict[str, str]) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "fields": fields}})


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
        like_count=tweet.like_count,
        liked_by_actor=tweet.liked_by_actor,
    )


def _parse_canonical_tweet_id(raw_id: str) -> UUID | None:
    try:
        parsed_id = UUID(raw_id)
    except (ValueError, AttributeError):
        return None
    return parsed_id if parsed_id.version == 4 and str(parsed_id) == raw_id else None


def _like_state_response(
    raw_id: str, actor: PublicUser, use_case: SetLikeState, liked: bool
) -> LikeStateResponse | JSONResponse:
    parsed_id = _parse_canonical_tweet_id(raw_id)
    if parsed_id is None:
        return _validation_response({"tweet_id": "invalid"})
    try:
        state = use_case.execute(SetLikeStateCommand(parsed_id, actor.id, liked))
    except TweetNotFound:
        return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
    return LikeStateResponse(
        tweet_id=state.tweet_id,
        like_count=state.like_count,
        liked_by_actor=state.liked_by_actor,
    )


def build_tweet_router(
    create_provider: Callable[..., CreateTweet],
    list_provider: Callable[..., ListTweetFeed],
    delete_provider: Callable[..., DeleteTweet],
    current_user_dependency: Callable[..., PublicUser],
    like_state_provider: Callable[..., SetLikeState],
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
        actor: PublicUser = Depends(current_user_dependency),
        use_case: ListTweetFeed = Depends(list_provider),
    ) -> TweetFeedResponse | JSONResponse:
        feeds = request.query_params.getlist("feed")
        usernames = request.query_params.getlist("username")
        if len(feeds) > 1 or (feeds and feeds[0] not in {kind.value for kind in FeedKind}):
            return _validation_response({"feed": "invalid"})
        feed = feeds[0] if feeds else FeedKind.ALL.value
        if len(usernames) > 1:
            return _validation_response({"username": "invalid"})
        username = usernames[0] if usernames else None
        if feed == FeedKind.PROFILE.value:
            try:
                scope = FeedScope(FeedKind.PROFILE, canonicalize_username(username))
            except (TypeError, ValueError):
                return _validation_response({"username": "invalid"})
        else:
            if username is not None:
                return _validation_response({"username": "invalid"})
            scope = FeedScope(FeedKind(feed))

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
            before = decode_cursor(cursors[0], scope) if cursors else None
        except InvalidFeedCursor:
            return _validation_response({"cursor": "invalid"})
        try:
            page = use_case.execute(ListTweetFeedQuery(page_size, before, scope, actor.id))
        except TweetValidationError as error:
            return _validation_response(error.fields)
        except TweetNotFound:
            return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
        return TweetFeedResponse(
            items=[_to_response(item) for item in page.items],
            next_cursor=encode_cursor(page.next_cursor) if page.next_cursor else None,
        )

    @router.post("/{tweet_id}/like", response_model=LikeStateResponse)
    def like_tweet(
        tweet_id: str,
        actor: PublicUser = Depends(current_user_dependency),
        use_case: SetLikeState = Depends(like_state_provider),
    ) -> LikeStateResponse | JSONResponse:
        return _like_state_response(tweet_id, actor, use_case, True)

    @router.delete("/{tweet_id}/like", response_model=LikeStateResponse)
    def unlike_tweet(
        tweet_id: str,
        actor: PublicUser = Depends(current_user_dependency),
        use_case: SetLikeState = Depends(like_state_provider),
    ) -> LikeStateResponse | JSONResponse:
        return _like_state_response(tweet_id, actor, use_case, False)

    @router.delete("/{tweet_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_tweet(
        tweet_id: str,
        actor: PublicUser = Depends(current_user_dependency),
        use_case: DeleteTweet = Depends(delete_provider),
    ) -> Response:
        parsed_id = _parse_canonical_tweet_id(tweet_id)
        if parsed_id is None:
            return _validation_response({"tweet_id": "invalid"})
        try:
            use_case.execute(DeleteTweetCommand(tweet_id=parsed_id, requester_id=actor.id))
        except TweetForbidden:
            return JSONResponse(status_code=403, content={"error": {"code": "forbidden"}})
        except TweetNotFound:
            return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router

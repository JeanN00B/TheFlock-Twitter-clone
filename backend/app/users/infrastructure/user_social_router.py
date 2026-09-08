"""FastAPI adapter for user social operations."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.users.application.follow_relationships import (
    FollowValidationError, SetFollowState, SetFollowStateCommand, UserNotFound,
)
from app.users.application.public_social_reads import (
    GetPublicProfile, ProfileNotFound, ProfileValidationError, SearchUsers,
    SearchValidationError,
)
from app.users.domain.user import PublicUser


class PublicIdentityResponse(BaseModel):
    id: str
    username: str
    display_name: str
    model_config = ConfigDict(extra="forbid")


class SearchResponse(BaseModel):
    items: list[PublicIdentityResponse]
    model_config = ConfigDict(extra="forbid")


class PublicProfileResponse(BaseModel):
    id: str
    username: str
    display_name: str
    followers_count: int
    following_count: int
    followed_by_actor: bool
    model_config = ConfigDict(extra="forbid")


class FollowStateResponse(BaseModel):
    username: str
    following: bool
    model_config = ConfigDict(extra="forbid")


def build_user_social_router(
    follow_state_provider: Callable[..., SetFollowState],
    current_user_dependency: Callable[..., PublicUser],
    search_provider: Callable[..., SearchUsers],
    profile_provider: Callable[..., GetPublicProfile],
) -> APIRouter:
    router = APIRouter(prefix="/users")

    @router.get("/search", response_model=SearchResponse)
    def search(
        request: Request,
        _actor: PublicUser = Depends(current_user_dependency),
        use_case: SearchUsers = Depends(search_provider),
    ):
        values = request.query_params.getlist("q")
        if len(values) != 1:
            return JSONResponse(status_code=422, content={
                "error": {"code": "validation_error", "fields": {"q": "invalid"}}
            })
        try:
            identities = use_case.execute(values[0])
        except SearchValidationError as error:
            return JSONResponse(status_code=422, content={
                "error": {"code": "validation_error", "fields": error.fields}
            })
        return SearchResponse(items=[PublicIdentityResponse(
            id=str(identity.id), username=identity.username,
            display_name=identity.display_name,
        ) for identity in identities])

    @router.get("/{username}", response_model=PublicProfileResponse)
    def profile(
        username: str,
        actor: PublicUser = Depends(current_user_dependency),
        use_case: GetPublicProfile = Depends(profile_provider),
    ):
        try:
            result = use_case.execute(username, actor.id)
        except ProfileNotFound:
            return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
        except ProfileValidationError as error:
            return JSONResponse(status_code=422, content={
                "error": {"code": "validation_error", "fields": error.fields}
            })
        return PublicProfileResponse(
            id=str(result.id), username=result.username, display_name=result.display_name,
            followers_count=result.followers_count, following_count=result.following_count,
            followed_by_actor=result.followed_by_actor,
        )

    def transition(username: str, following: bool, actor: PublicUser, use_case: SetFollowState):
        try:
            state = use_case.execute(SetFollowStateCommand(
                actor_id=actor.id, actor_username=actor.username,
                target_username=username, following=following,
            ))
        except UserNotFound:
            return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
        except FollowValidationError as error:
            return JSONResponse(status_code=422, content={
                "error": {"code": "validation_error", "fields": error.fields}
            })
        return FollowStateResponse(username=state.username, following=state.following)

    @router.post("/{username}/follow", response_model=FollowStateResponse, status_code=status.HTTP_200_OK)
    def follow(
        username: str, actor: PublicUser = Depends(current_user_dependency),
        use_case: SetFollowState = Depends(follow_state_provider),
    ):
        return transition(username, True, actor, use_case)

    @router.delete("/{username}/follow", response_model=FollowStateResponse, status_code=status.HTTP_200_OK)
    def unfollow(
        username: str, actor: PublicUser = Depends(current_user_dependency),
        use_case: SetFollowState = Depends(follow_state_provider),
    ):
        return transition(username, False, actor, use_case)

    return router

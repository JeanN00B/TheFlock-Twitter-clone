"""FastAPI adapter for follow and unfollow operations."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.users.application.follow_relationships import (
    FollowValidationError,
    SetFollowState,
    SetFollowStateCommand,
    UserNotFound,
)
from app.users.domain.user import PublicUser


class FollowStateResponse(BaseModel):
    username: str
    following: bool
    model_config = ConfigDict(extra="forbid")


def build_user_social_router(
    follow_state_provider: Callable[..., SetFollowState],
    current_user_dependency: Callable[..., PublicUser],
) -> APIRouter:
    router = APIRouter(prefix="/users")

    def transition(
        username: str,
        following: bool,
        actor: PublicUser,
        use_case: SetFollowState,
    ):
        try:
            state = use_case.execute(SetFollowStateCommand(
                actor_id=actor.id,
                actor_username=actor.username,
                target_username=username,
                following=following,
            ))
        except UserNotFound:
            return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
        except FollowValidationError as error:
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "validation_error", "fields": error.fields}},
            )
        return FollowStateResponse(username=state.username, following=state.following)

    @router.post("/{username}/follow", response_model=FollowStateResponse, status_code=status.HTTP_200_OK)
    def follow(
        username: str,
        actor: PublicUser = Depends(current_user_dependency),
        use_case: SetFollowState = Depends(follow_state_provider),
    ):
        return transition(username, True, actor, use_case)

    @router.delete("/{username}/follow", response_model=FollowStateResponse, status_code=status.HTTP_200_OK)
    def unfollow(
        username: str,
        actor: PublicUser = Depends(current_user_dependency),
        use_case: SetFollowState = Depends(follow_state_provider),
    ):
        return transition(username, False, actor, use_case)

    return router

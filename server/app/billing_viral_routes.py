"""Legacy refresh URL now reads the weekly database snapshot without a supplier call."""

from typing import Annotated

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.customer_fence import BusinessDbDep
from app.viral_routes import ViralStatisticsResponse, _item
from app.viral_statistics import _load_wechat_videos

router = APIRouter(tags=["viral-billing"])


class RefreshRequest(BaseModel):
    videoIds: list[str] = Field(min_length=1, max_length=12)


@router.post("/api/viral/videos/statistics/refresh", response_model=ViralStatisticsResponse)
def refresh_statistics(
    payload: RefreshRequest,
    db: BusinessDbDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> ViralStatisticsResponse:
    with db.write() as (conn, _actor):
        return ViralStatisticsResponse(
            items=[
                _item(video) for video in _load_wechat_videos(conn, sorted(set(payload.videoIds)))
            ]
        )

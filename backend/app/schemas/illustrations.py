from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class GenerateIllustrationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    size: str = Field(default="1024x1024", max_length=32)
    reference_asset_ids: list[int] = Field(default_factory=list, max_length=20)
    character_id: Optional[int] = None
    role: Literal["character_anchor", "illustration"] = "illustration"
    pipeline_run_id: Optional[str] = Field(default=None, max_length=64)
    shot_seq: Optional[int] = None


class GenerateShotlistRequest(BaseModel):
    essay: str = Field(min_length=1, max_length=8000)
    character_id: int
    instruction: str = Field(default="", max_length=800)
    pipeline_run_id: Optional[str] = Field(default=None, max_length=64)


class IllustrationAssetResponse(BaseModel):
    id: int
    user_id: int
    character_id: Optional[int]
    role: str
    pipeline_run_id: Optional[str]
    shot_seq: Optional[int]
    prompt: str
    model: str
    size: str
    reference_asset_ids: list[int]
    file_path: str
    created_at: datetime

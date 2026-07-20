from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CharacterCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str = Field(min_length=1, max_length=128)
    ip_definition: str = Field(default="", max_length=8000)
    reference_image_asset_ids: list[int] = Field(default_factory=list, max_length=20)
    created_via: str = Field(default="text_only", max_length=32)


class CharacterUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    ip_definition: str | None = Field(default=None, max_length=8000)
    reference_image_asset_ids: list[int] | None = Field(default=None, max_length=20)


class CharacterResponse(BaseModel):
    id: int
    name: str
    slug: str
    ip_definition: str
    reference_image_asset_ids: list[int]
    created_via: str
    created_at: datetime
    updated_at: datetime

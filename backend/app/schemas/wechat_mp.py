from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


WechatMpArticleStatus = Literal[
    "draft_local", "writing", "layout_ready", "prompts_ready", "images_partial",
    "images_ready", "synced_to_wechat", "publish_pending", "published", "failed",
]
WechatMpImageStatus = Literal["prompt_ready", "generating", "generated", "failed", "skipped"]
WechatMpDraftSyncStatus = Literal["synced", "failed"]
WechatMpPublishStatus = Literal["scheduled", "publishing", "published", "failed"]


class WechatMpArticleCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    topic: str = Field(min_length=1)
    source_material: str = ""
    target_reader: str = ""
    tone: str = ""
    illustration_skill: str = "xiaomao-illustrations"


class WechatMpAccountCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    app_id: str = Field(min_length=1, max_length=128)
    app_secret: str = Field(min_length=1)


class WechatMpAccountResponse(BaseModel):
    id: int
    user_id: int
    name: str
    app_id: str
    connection_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WechatMpArticleResponse(BaseModel):
    id: int
    user_id: int
    account_id: int | None
    title: str
    markdown_body: str
    html_body: str
    digest: str
    cover_brief: str
    status: WechatMpArticleStatus
    illustration_skill: str
    cost_estimate: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WechatMpImagePromptResponse(BaseModel):
    id: int
    user_id: int
    article_id: int
    section_id: int
    skill_name: str
    skill_version: str
    prompt: str
    editable_prompt: str
    version: int
    status: WechatMpImageStatus
    cost_estimate: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WechatMpAssetResponse(BaseModel):
    id: int
    user_id: int
    article_id: int
    prompt_id: int | None
    role: str
    file_path: str
    public_url: str
    prompt: str
    skill_name: str
    model_name: str
    status: WechatMpImageStatus
    provider_response: dict
    created_at: datetime

    model_config = {"from_attributes": True}

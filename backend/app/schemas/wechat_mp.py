from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


WechatMpArticleStatus = Literal[
    "draft_local", "writing", "layout_ready", "prompts_ready", "images_partial",
    "images_ready", "synced_to_wechat", "publish_pending", "published", "failed",
]
WechatMpImageStatus = Literal["prompt_ready", "generating", "generated", "failed", "skipped"]
WechatMpDraftSyncStatus = Literal["pending", "synced", "stale", "failed"]
WechatMpPublishStatus = Literal["pending", "scheduled", "submitted", "publishing", "published", "failed", "cancelled"]
WechatMpMaterialType = Literal["text", "link", "outline", "quote", "file", "other"]


class WechatMpArticleCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    topic: str = Field(min_length=1)
    source_material: str = ""
    material_ids: list[int] = Field(default_factory=list)
    target_reader: str = ""
    tone: str = ""
    illustration_skill: str = "xiaomao-illustrations"


class WechatMpIllustrationCharacterCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1)


class WechatMpIllustrationCharacterResponse(BaseModel):
    id: int | None
    user_id: int | None = None
    name: str
    skill_name: str
    prompt: str
    status: str
    is_builtin: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


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
    revision: int
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


class WechatMpMaterialCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    material_type: WechatMpMaterialType = "text"
    content: str = ""
    source_url: str = ""
    file_name: str = ""
    original_file_name: str = ""
    file_path: str = ""
    download_url: str = ""
    file_size: int = 0
    mime_type: str = ""
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class WechatMpMaterialUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    material_type: WechatMpMaterialType | None = None
    content: str | None = None
    source_url: str | None = None
    file_name: str | None = None
    original_file_name: str | None = None
    file_path: str | None = None
    download_url: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    status: str | None = Field(default=None, max_length=32)


class WechatMpMaterialResponse(BaseModel):
    id: int
    user_id: int
    title: str
    material_type: str
    content: str
    source_url: str
    file_name: str
    original_file_name: str
    file_path: str
    download_url: str
    file_size: int
    mime_type: str
    tags: list[str]
    notes: str
    status: str
    used_article_count: int = 0
    usage_status: str = "unused"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

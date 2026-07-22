from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class WechatMpAccount(Base):
    __tablename__ = "wechat_mp_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    app_id: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_app_secret: Mapped[str] = mapped_column(Text, nullable=False)
    token_cache: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    connection_status: Mapped[str] = mapped_column(String(32), default="unchecked", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class WechatMpArticle(Base):
    __tablename__ = "wechat_mp_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("wechat_mp_accounts.id"), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    markdown_body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    html_body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    digest: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    cover_brief: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft_local", index=True, nullable=False)
    illustration_skill: Mapped[str] = mapped_column(String(80), default="xiaomao-illustrations", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cost_estimate: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    sections: Mapped[list["WechatMpArticleSection"]] = relationship(cascade="all, delete-orphan")
    prompts: Mapped[list["WechatMpImagePrompt"]] = relationship(cascade="all, delete-orphan")
    assets: Mapped[list["WechatMpAsset"]] = relationship(cascade="all, delete-orphan")


class WechatMpArticleSection(Base):
    __tablename__ = "wechat_mp_article_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("wechat_mp_articles.id"), index=True, nullable=False)
    section_index: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    needs_image: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class WechatMpImagePrompt(Base):
    __tablename__ = "wechat_mp_image_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("wechat_mp_articles.id"), index=True, nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("wechat_mp_article_sections.id"), index=True, nullable=False)
    skill_name: Mapped[str] = mapped_column(String(80), default="xiaomao-illustrations", nullable=False)
    skill_version: Mapped[str] = mapped_column(String(32), default="v1.0.0", nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    editable_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="prompt_ready", index=True, nullable=False)
    cost_estimate: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class WechatMpAsset(Base):
    __tablename__ = "wechat_mp_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("wechat_mp_articles.id"), index=True, nullable=False)
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("wechat_mp_image_prompts.id"), index=True, nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    public_url: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    skill_name: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="generated", index=True, nullable=False)
    provider_response: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class WechatMpMaterial(Base):
    __tablename__ = "wechat_mp_materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    material_type: Mapped[str] = mapped_column(String(32), default="text", index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    original_file_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    file_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    download_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class WechatMpDraftSync(Base):
    __tablename__ = "wechat_mp_draft_syncs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("wechat_mp_accounts.id"), index=True, nullable=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("wechat_mp_articles.id"), index=True, nullable=False)
    wechat_media_id: Mapped[str] = mapped_column(String(128), nullable=False)
    article_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(200), unique=True, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="synced", index=True, nullable=False)
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class WechatMpPublishJob(Base):
    __tablename__ = "wechat_mp_publish_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("wechat_mp_accounts.id"), index=True, nullable=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("wechat_mp_articles.id"), index=True, nullable=False)
    draft_sync_id: Mapped[int] = mapped_column(ForeignKey("wechat_mp_draft_syncs.id"), index=True, nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(200), unique=True, index=True, nullable=True)
    publish_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="scheduled", index=True, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(128), index=True)
    ip_definition: Mapped[str] = mapped_column(Text, default="")
    reference_image_asset_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_via: Mapped[str] = mapped_column(String(32), default="text_only")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)


class IllustrationAsset(Base):
    __tablename__ = "illustration_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    character_id: Mapped[Optional[int]] = mapped_column(ForeignKey("characters.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32), default="illustration", index=True)  # 'character_anchor' | 'illustration'
    pipeline_run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    shot_seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    size: Mapped[str] = mapped_column(String(32), default="1024x1024")
    reference_asset_ids: Mapped[list] = mapped_column(JSON, default=list)
    file_path: Mapped[str] = mapped_column(Text, default="")
    provider_raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, index=True)


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    pipeline_run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    step: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    image_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unit_price_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    cost_yuan: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.0000"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, index=True)


class IllustrationRun(Base):
    __tablename__ = "illustration_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), index=True)
    essay: Mapped[str] = mapped_column(Text)
    instruction: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="shotlist_ready", index=True)
    core_thesis: Mapped[str] = mapped_column(Text, default="")
    cognitive_anchors: Mapped[list] = mapped_column(JSON, default=list)
    shots: Mapped[list] = mapped_column(JSON, default=list)
    selected_shot_seqs: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)

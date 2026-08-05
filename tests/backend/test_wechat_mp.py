import importlib.util
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.user import User


def test_wechat_mp_adapter_accepts_successful_errcode_zero():
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiAdapter

    response = Mock(status_code=200)
    response.json.return_value = {"errcode": 0, "publish_id": "publish_001"}

    assert WechatMpApiAdapter()._checked_json(response, "wechat publish submit failed") == {
        "errcode": 0,
        "publish_id": "publish_001",
    }


def test_wechat_mp_add_draft_sends_utf8_json_without_escaping_chinese(monkeypatch):
    from backend.app.adapters.wechat_mp import api_adapter

    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"errcode": 0, "media_id": "draft-media"}

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(api_adapter.requests, "post", fake_post)

    api_adapter.WechatMpApiAdapter().add_draft(
        access_token="token",
        article={
            "title": "软考高级必备 | 信息系统工程核心考点速查手册（附口诀）",
            "digest": "摘要",
            "content": "<p>正文</p>",
            "thumb_media_id": "thumb",
        },
    )

    assert "json" not in captured
    assert captured["data"].decode("utf-8").find("软考高级必备") != -1
    assert "\\u8f6f" not in captured["data"].decode("utf-8")
    assert captured["headers"]["Content-Type"] == "application/json; charset=utf-8"


@pytest.fixture
def db_session():
    # Register all mapped tables before constructing the isolated test database.
    import backend.app.models  # noqa: F401

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def test_user(db_session):
    user = User(username="wechat-mp-user", password_hash="unused")
    db_session.add(user)
    db_session.commit()
    return user


def test_wechat_mp_models_are_independent_from_xhs_assets(db_session, test_user):
    from backend.app.models.wechat_mp import WechatMpArticle, WechatMpAsset
    from backend.app.models.pipeline import IllustrationAsset

    article = WechatMpArticle(
        user_id=test_user.id,
        title="公众号标题",
        markdown_body="正文",
        html_body="<p>正文</p>",
        status="draft_local",
        illustration_skill="xiaomao-illustrations",
    )
    db_session.add(article)
    db_session.flush()

    asset = WechatMpAsset(
        user_id=test_user.id,
        article_id=article.id,
        role="inline_illustration",
        file_path="/api/files/media/wechat-mp-u1-a1.png",
        public_url="/api/files/media/wechat-mp-u1-a1.png",
        prompt="小猫压住一个标题盒子",
        skill_name="xiaomao-illustrations",
        model_name="doubao-seedream-4-0-250828",
        status="generated",
    )
    db_session.add(asset)
    db_session.commit()

    assert db_session.query(WechatMpAsset).count() == 1
    assert db_session.query(IllustrationAsset).count() == 0


def test_prompt_fingerprints_and_analysis_response_defaults(db_session, test_user):
    from backend.app.models.wechat_mp import (
        WechatMpArticle,
        WechatMpArticleSection,
        WechatMpImagePrompt,
    )
    from backend.app.schemas.wechat_mp import (
        WechatMpPromptAnalysisResponse,
        WechatMpPromptGenerationResponse,
    )

    article = WechatMpArticle(user_id=test_user.id, title="公众号标题")
    db_session.add(article)
    db_session.flush()
    section = WechatMpArticleSection(
        user_id=test_user.id,
        article_id=article.id,
        section_index=0,
    )
    db_session.add(section)
    db_session.flush()
    prompt = WechatMpImagePrompt(
        user_id=test_user.id,
        article_id=article.id,
        section_id=section.id,
        prompt="小猫压住一个标题盒子",
        editable_prompt="小猫压住一个标题盒子",
    )
    db_session.add(prompt)
    db_session.flush()

    assert section.source_fingerprint == ""
    assert section.analysis_version == ""
    assert prompt.generation_fingerprint == ""

    analysis = WechatMpPromptAnalysisResponse()
    assert analysis.model_dump() == {
        "source_blocks": 0,
        "filtered_blocks": 0,
        "deterministic_prompts": 0,
        "semantic_candidates": 0,
        "reused_prompts": 0,
        "model_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    assert WechatMpPromptGenerationResponse(items=[], analysis=analysis).model_dump() == {
        "items": [],
        "analysis": analysis.model_dump(),
    }


def test_content_analysis_filters_nonvisual_html_and_metadata_before_flow_detection():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    analysis = analyze_content(
        "<details><summary>点击查看答案</summary>\n"
        "需求获取 -> 需求分析 -> 需求确认\n"
        "</details>\n\n"
        "封面尺寸：900 x 383，禁止水印。\n\n"
        "提示词：一只猫坐在桌前。"
    )

    assert len(analysis.blocks) == 3
    assert analysis.filtered_blocks == 3
    assert analysis.candidates == ()


def test_content_analysis_filters_indented_code_comments_and_nonvisual_html_before_flows():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    analysis = analyze_content(
        "    需求获取 -> 需求分析 -> 需求确认\n\n"
        "<!-- 需求获取 -> 需求分析 -> 需求确认 -->\n\n"
        "<pre>需求获取 -> 需求分析 -> 需求确认</pre>\n\n"
        "<code>需求获取 -> 需求分析 -> 需求确认</code>"
    )

    assert analysis.filtered_blocks == 4
    assert analysis.candidates == ()


def test_content_analysis_filters_non_rendered_html_authoring_containers_before_flows():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    analysis = analyze_content(
        "<template>需求获取 -> 需求分析 -> 需求确认</template>\n\n"
        "<noscript>需求获取 -> 需求分析 -> 需求确认</noscript>"
    )

    assert analysis.filtered_blocks == 2
    assert analysis.candidates == ()


def test_content_analysis_extracts_exact_flow_with_heading_context():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    analysis = analyze_content(
        "# 系统设计\n\n"
        "## 需求流程\n\n"
        "需求获取 -> 需求分析 -> 需求确认"
    )

    candidate = analysis.candidates[0]
    assert candidate.kind == "flow"
    assert candidate.heading_path == ("系统设计", "需求流程")
    assert candidate.structure == (("需求获取", "需求分析", "需求确认"),)


def test_content_analysis_preserves_link_labels_and_link_stable_fingerprints():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    plain = analyze_content("需求获取 -> 需求分析 -> 需求确认")
    linked = analyze_content(
        "[需求获取](https://example.test/acquire) -> "
        "[需求分析](https://example.test/analyze) -> "
        "[需求确认](https://example.test/confirm)"
    )
    with_image = analyze_content(
        "需求获取 -> 需求分析 -> 需求确认 "
        "![流程示意](https://example.test/flow.png)"
    )

    assert linked.candidates[0].kind == "flow"
    assert linked.candidates[0].structure == (("需求获取", "需求分析", "需求确认"),)
    assert linked.blocks[0].fingerprint == plain.blocks[0].fingerprint
    assert with_image.candidates[0].structure == (("需求获取", "需求分析", "需求确认"),)
    assert with_image.blocks[0].fingerprint == plain.blocks[0].fingerprint


def test_content_analysis_accepts_only_valid_markdown_tables():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    valid = analyze_content(
        "| 风格 | 包含类型 |\n"
        "| --- | --- |\n"
        "| 数据流风格 | 批处理序列、管道/过滤器 |\n"
        "| 仓库风格 | 数据库系统、黑板系统 |"
    )
    invalid = analyze_content("| 风格 | 包含类型 |\n| 数据流风格 | 批处理序列 |")
    no_outer_pipes = analyze_content(
        "[风格](https://example.test/style) | 包含类型\n"
        "--- | ---\n"
        "数据流风格 | [批处理序列](https://example.test/dataflow)"
    )
    escaped_pipe = analyze_content(
        "| 类型 | 说明 |\n"
        "| --- | --- |\n"
        "| A | a \\| b |"
    )

    assert valid.candidates[0].kind == "table"
    assert valid.candidates[0].structure == (
        ("风格", "包含类型"),
        ("数据流风格", "批处理序列、管道/过滤器"),
        ("仓库风格", "数据库系统、黑板系统"),
    )
    assert invalid.candidates == ()
    assert no_outer_pipes.candidates[0].kind == "table"
    assert no_outer_pipes.candidates[0].structure == (
        ("风格", "包含类型"),
        ("数据流风格", "批处理序列"),
    )
    assert escaped_pipe.candidates[0].structure == (
        ("类型", "说明"),
        ("A", "a | b"),
    )


def test_content_analysis_extracts_explicit_classification_mappings():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    analysis = analyze_content(
        "## 架构风格分类\n\n"
        "- 数据流风格：批处理序列、管道/过滤器\n"
        "- 调用/返回风格：主程序/子程序、层次结构"
    )

    candidate = analysis.candidates[0]
    assert candidate.kind == "classification"
    assert candidate.structure == (
        ("数据流风格", "批处理序列、管道/过滤器"),
        ("调用/返回风格", "主程序/子程序、层次结构"),
    )


def test_content_analysis_extracts_adjacent_non_bullet_classification_mappings():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    analysis = analyze_content(
        "数据流风格：批处理序列、管道/过滤器\n"
        "调用/返回风格：主程序/子程序、层次结构"
    )

    assert analysis.candidates[0].kind == "classification"
    assert analysis.candidates[0].structure == (
        ("数据流风格", "批处理序列、管道/过滤器"),
        ("调用/返回风格", "主程序/子程序、层次结构"),
    )


def test_content_analysis_keeps_all_nodes_in_long_exact_flow():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    nodes = [f"步骤{index}" for index in range(1, 14)]
    analysis = analyze_content(" -> ".join(nodes))

    assert analysis.candidates[0].kind == "flow"
    assert analysis.candidates[0].structure == (tuple(nodes),)


def test_content_analysis_returns_no_candidate_for_low_information_copy():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    analysis = analyze_content("# 开场\n\n欢迎关注公众号，下一篇再见。")

    assert analysis.candidates == ()
    assert analysis.filtered_blocks == 0


def test_content_analysis_deduplicates_at_jaccard_point_eight_two_boundary():
    from backend.app.services.wechat_mp_content_analysis_service import (
        ContentBlock,
        VisualCandidate,
        _char_bigrams,
        _deduplicate,
        _jaccard,
    )

    # The first text has 41 unique bigrams; the second appends nine, so 41 / 50 == 0.82.
    base = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEF"
    extended = base + "GHIJKLMNO"
    first_block = ContentBlock(0, (), base, base, "first")
    second_block = ContentBlock(1, (), extended, extended, "second")
    candidates = (
        VisualCandidate(first_block, "semantic", (), 0.70),
        VisualCandidate(second_block, "semantic", (), 0.80),
    )

    deduplicated = _deduplicate(candidates)

    assert _jaccard(_char_bigrams(base), _char_bigrams(extended)) == pytest.approx(0.82)
    assert deduplicated == (candidates[1],)


def test_content_analysis_keeps_distinct_deterministic_flows_despite_near_duplicate_text():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    analysis = analyze_content(
        "项目需求收集 -> 项目需求分析 -> 项目需求确认 -> 确认项目需求并提交审核\n\n"
        "项目需求收集 -> 项目需求分析 -> 项目需求确认 -> 确认项目需求并提交复审"
    )

    assert [candidate.structure for candidate in analysis.deterministic_candidates] == [
        (("项目需求收集", "项目需求分析", "项目需求确认", "确认项目需求并提交审核"),),
        (("项目需求收集", "项目需求分析", "项目需求确认", "确认项目需求并提交复审"),),
    ]


def test_image_prompt_section_index_matches_migration(monkeypatch):
    from backend.app.models.wechat_mp import WechatMpImagePrompt

    migration_path = (
        Path(__file__).parents[2]
        / "backend"
        / "alembic"
        / "versions"
        / "20260721_wmp001_add_wechat_mp_tables.py"
    )
    spec = importlib.util.spec_from_file_location("wechat_mp_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    created_indexes: list[tuple[str, str]] = []
    dropped_indexes: list[tuple[str, str]] = []
    monkeypatch.setattr(migration.op, "create_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "create_index", lambda name, table, columns: created_indexes.append((name, table)))
    monkeypatch.setattr(migration.op, "drop_index", lambda name, table_name: dropped_indexes.append((name, table_name)))
    monkeypatch.setattr(migration.op, "drop_table", lambda *args, **kwargs: None)

    migration.upgrade()
    migration.downgrade()

    model_index_names = {index.name for index in WechatMpImagePrompt.__table__.indexes}
    section_index_name = "ix_wechat_mp_image_prompts_section_id"
    assert section_index_name in model_index_names
    assert (section_index_name, "wechat_mp_image_prompts") in created_indexes
    assert (section_index_name, "wechat_mp_image_prompts") in dropped_indexes


@pytest.fixture
def api_client(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.main import app

    import backend.app.models  # noqa: F401

    engine = create_engine(
        f"sqlite:///{tmp_path / 'wechat-mp-api.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), testing_session
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def auth_headers(api_client):
    client, _ = api_client
    response = client.post("/api/auth/register", json={"username": "wechat-owner", "password": "secret123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def created_wechat_article(api_client, auth_headers):
    client, session_factory = api_client
    from backend.app.models import User, WechatMpArticle

    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="稳定输出",
            markdown_body=(
                "## 问题\n计划开始时消耗精力的核心问题，是任务入口太多而无法选择。\n\n"
                "## 方法\n解决方法是先做最小动作，再根据结果决定下一步。"
            ),
            html_body=(
                "<h2>问题</h2><p>计划开始时消耗精力的核心问题，是任务入口太多而无法选择。</p>"
                "<h2>方法</h2><p>解决方法是先做最小动作，再根据结果决定下一步。</p>"
            ),
            digest="稳定输出的方法",
            cover_brief="小猫压住计划表",
            status="layout_ready",
            illustration_skill="xiaomao-illustrations",
        )
        session.add(article)
        session.commit()
        session.refresh(article)
        return article
    finally:
        session.close()


def _successful_prompt_batch(candidates, *, prompt="一只小猫整理便签", input_tokens=12, output_tokens=24):
    from backend.app.services.wechat_mp_prompt_batch_service import BatchPromptItem, BatchPromptResult

    return BatchPromptResult(
        items=tuple(
            BatchPromptItem(candidate_id=str(candidate.source_index), prompt=prompt)
            for candidate in candidates
        ),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_name="qwen3.7-max",
        model_calls=1,
        outcome="success",
    )


@pytest.fixture
def created_wechat_account(api_client, auth_headers):
    client, session_factory = api_client
    response = client.post(
        "/api/platforms/wechat-mp/accounts",
        json={"name": "测试公众号", "app_id": "wx-test", "app_secret": "secret-value"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    from backend.app.models import WechatMpAccount
    from backend.app.services.wechat_mp_token_service import normalize_token_cache

    session = session_factory()
    try:
        account = session.get(WechatMpAccount, response.json()["id"])
        account.token_cache = normalize_token_cache({"access_token": "cached-token", "expires_in": 3600})
        session.commit()
    finally:
        session.close()
    return type("WechatMpAccountFixture", (), {"id": response.json()["id"]})()


@pytest.fixture
def created_wechat_article_with_image(api_client, auth_headers, created_wechat_article, tmp_path, monkeypatch):
    _, session_factory = api_client
    from backend.app.models import User, WechatMpAsset
    from backend.app.services import wechat_mp_image_service as image_service

    image_path = tmp_path / "wechat-inline.png"
    image_path.write_bytes(b"fake-image")
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        asset = WechatMpAsset(
            user_id=owner.id,
            article_id=created_wechat_article.id,
            role="inline_illustration",
            file_path=str(image_path),
            public_url="/api/files/media/wechat-inline.png",
            prompt="测试插图",
            skill_name="xiaomao-illustrations",
            model_name="test-model",
            status="generated",
        )
        article = session.get(type(created_wechat_article), created_wechat_article.id)
        article.html_body = '<p><img src="/api/files/media/wechat-inline.png" /></p>'
        session.add(asset)
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr(
        image_service,
        "_call_image_model",
        lambda **kwargs: {
            "file_path": str(image_path),
            "public_url": "/api/files/media/wechat-cover.png",
            "provider_response": {"ok": True},
        },
    )
    client, _ = api_client
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/cover",
        json={"image_model": "test-model", "size": "16:9"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["role"] == "cover"
    return created_wechat_article


def test_sync_wechat_mp_article_creates_draft_sync(api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch):
    from backend.app.services import wechat_mp_draft_service as draft_service
    from backend.app.models import WechatMpArticle, WechatMpDraftSync

    client, _ = api_client
    calls = []

    class FakeAdapter:
        def upload_permanent_image(self, **kwargs):
            calls.append(("cover", kwargs))
            return {"media_id": "thumb_media_id"}

        def upload_content_image(self, **kwargs):
            calls.append(("inline", kwargs))
            return {"url": "https://mmbiz.qpic.cn/fake.png"}

        def add_draft(self, **kwargs):
            calls.append(("draft", kwargs))
            return {"media_id": "wechat_draft_media_id"}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": created_wechat_account.id},
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["wechat_media_id"] == "wechat_draft_media_id"
    assert data["status"] == "synced"
    assert [name for name, _ in calls] == ["cover", "inline", "draft"]
    assert calls[-1][1]["article"]["content"] == '<p><img src="https://mmbiz.qpic.cn/fake.png" /></p>'

    _, session_factory = api_client
    session = session_factory()
    try:
        assert session.query(WechatMpDraftSync).filter_by(article_id=created_wechat_article_with_image.id).count() == 1
        assert session.get(WechatMpArticle, created_wechat_article_with_image.id).status == "synced_to_wechat"
    finally:
        session.close()


def test_get_latest_wechat_mp_draft_sync_restores_synced_state(api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch):
    from backend.app.models import WechatMpDraftSync
    from backend.app.services import wechat_mp_draft_service as draft_service

    class FakeAdapter:
        def upload_permanent_image(self, **kwargs): return {"media_id": "thumb_media_id"}
        def upload_content_image(self, **kwargs): return {"url": "https://mmbiz.qpic.cn/fake.png"}
        def add_draft(self, **kwargs): return {"media_id": "wechat_draft_media_id"}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    client, session_factory = api_client
    synced = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": created_wechat_account.id},
        headers=auth_headers,
    )
    assert synced.status_code == 201

    latest = client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/draft-syncs/latest",
        headers=auth_headers,
    )

    assert latest.status_code == 200
    assert latest.json()["id"] == synced.json()["id"]
    assert latest.json()["status"] == "synced"
    assert latest.json()["wechat_media_id"] == "wechat_draft_media_id"

    other = client.post("/api/auth/register", json={"username": "draft-sync-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/draft-syncs/latest",
        headers=other_headers,
    ).status_code == 404

    empty = client.get("/api/platforms/wechat-mp/articles/999999/draft-syncs/latest", headers=auth_headers)
    assert empty.status_code == 404

    session = session_factory()
    try:
        assert session.query(WechatMpDraftSync).filter_by(article_id=created_wechat_article_with_image.id).count() == 1
    finally:
        session.close()


def test_sync_wechat_mp_article_applies_selected_layout_style(
    api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch
):
    from backend.app.services import wechat_mp_draft_service as draft_service
    from backend.app.models import WechatMpArticle

    client, session_factory = api_client
    draft_payloads = []
    upload_calls = []

    session = session_factory()
    try:
        article = session.get(WechatMpArticle, created_wechat_article_with_image.id)
        article.html_body = '<h2>01 信息系统管理</h2><p><img src="/api/files/media/wechat-inline.png" /></p>'
        session.commit()
    finally:
        session.close()

    class FakeAdapter:
        def upload_permanent_image(self, **kwargs):
            upload_calls.append(("cover_thumb", kwargs))
            return {"media_id": "thumb_media_id"}

        def upload_content_image(self, **kwargs):
            upload_calls.append(("content", kwargs))
            return {"url": f"https://mmbiz.qpic.cn/{len(upload_calls)}.png"}

        def add_draft(self, **kwargs):
            draft_payloads.append(kwargs["article"])
            return {"media_id": "styled_draft_media_id"}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": created_wechat_account.id, "layout_style": "study_green"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["wechat_media_id"] == "styled_draft_media_id"
    content = draft_payloads[0]["content"]
    assert "章节复习" in content
    assert "max-width:677px" in content
    assert "border-radius:18px" in content
    assert "https://mmbiz.qpic.cn/2.png" in content
    assert "https://mmbiz.qpic.cn/3.png" in content
    assert [name for name, _ in upload_calls] == ["cover_thumb", "content", "content"]


def test_sync_wechat_mp_draft_repairs_saved_markdown_table_before_upload(
    api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch
):
    from backend.app.models import WechatMpArticle
    from backend.app.services import wechat_mp_draft_service as draft_service

    client, session_factory = api_client
    draft_payloads = []

    class FakeAdapter:
        def upload_permanent_image(self, **kwargs):
            return {"media_id": "thumb_media_id"}

        def upload_content_image(self, **kwargs):
            return {"url": "https://mmbiz.qpic.cn/fake.png"}

        def add_draft(self, **kwargs):
            draft_payloads.append(kwargs["article"])
            return {"media_id": "repaired-draft"}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    session = session_factory()
    try:
        article = session.get(WechatMpArticle, created_wechat_article_with_image.id)
        article.html_body = (
            '<p>| 风格 | 包含类型 |<br />'
            '|------|----------|<br />'
            '| **数据流风格** | 批处理序列、管道/过滤器 |</p>'
            '<p><img src="/api/files/media/wechat-inline.png" alt="| **旧图** | 未清洗 |" /></p>'
        )
        session.commit()
    finally:
        session.close()

    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": created_wechat_account.id},
        headers=auth_headers,
    )

    assert response.status_code == 201
    content = draft_payloads[0]["content"]
    assert "<table" in content
    assert "<strong>数据流风格</strong>" in content
    assert 'alt="旧图 未清洗"' in content
    assert "|------|----------|" not in content
    assert "| **旧图** |" not in content


def test_sync_wechat_mp_draft_reports_unresolved_prompt_placeholders(
    api_client, auth_headers, created_wechat_prompt, created_wechat_account, tmp_path
):
    client, session_factory = api_client
    from backend.app.models import User, WechatMpArticle, WechatMpAsset

    cover_path = tmp_path / "cover.png"
    cover_path.write_bytes(b"cover")
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = session.get(WechatMpArticle, created_wechat_prompt.article_id)
        article.html_body = f"<p>正文</p>{{{{image:prompt-{created_wechat_prompt.id}}}}}"
        session.add(WechatMpAsset(
            user_id=owner.id,
            article_id=article.id,
            role="cover",
            file_path=str(cover_path),
            public_url="/api/files/media/cover.png",
            prompt="封面",
            skill_name="xiaomao-illustrations",
            model_name="test-model",
            status="generated",
        ))
        session.commit()
    finally:
        session.close()

    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}/sync-draft",
        json={"account_id": created_wechat_account.id},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert f"prompt-{created_wechat_prompt.id}" in response.json()["detail"]
    assert "写作页生成对应正文图片" in response.json()["detail"]


def test_sync_wechat_mp_draft_refreshes_raw_token_cache(api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch):
    from backend.app.models import WechatMpAccount
    from backend.app.services import wechat_mp_draft_service as draft_service

    client, session_factory = api_client
    session = session_factory()
    try:
        account = session.get(WechatMpAccount, created_wechat_account.id)
        account.token_cache = {"access_token": "raw-token", "expires_in": 7200}
        session.commit()
    finally:
        session.close()

    calls = []

    class FakeAdapter:
        def get_access_token(self, **kwargs):
            calls.append(("refresh", kwargs))
            return {"access_token": "refreshed-token", "expires_in": 7200}

        def upload_permanent_image(self, **kwargs):
            calls.append(("cover", kwargs))
            return {"media_id": "thumb_media_id"}

        def upload_content_image(self, **kwargs):
            return {"url": "https://mmbiz.qpic.cn/fake.png"}

        def add_draft(self, **kwargs):
            return {"media_id": "wechat_draft_media_id"}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": created_wechat_account.id},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert [name for name, _ in calls] == ["refresh", "cover"]
    assert calls[-1][1]["access_token"] == "refreshed-token"


def test_sync_wechat_mp_draft_refreshes_expired_token_cache(api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch):
    from backend.app.models import WechatMpAccount
    from backend.app.services import wechat_mp_draft_service as draft_service

    client, session_factory = api_client
    session = session_factory()
    try:
        account = session.get(WechatMpAccount, created_wechat_account.id)
        account.token_cache = {"access_token": "expired-token", "expires_at": time.time() - 1}
        session.commit()
    finally:
        session.close()

    calls = []

    class FakeAdapter:
        def get_access_token(self, **kwargs):
            calls.append(("refresh", kwargs))
            return {"access_token": "refreshed-token", "expires_in": 7200}

        def upload_permanent_image(self, **kwargs):
            calls.append(("cover", kwargs))
            return {"media_id": "thumb_media_id"}

        def upload_content_image(self, **kwargs):
            return {"url": "https://mmbiz.qpic.cn/fake.png"}

        def add_draft(self, **kwargs):
            return {"media_id": "wechat_draft_media_id"}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": created_wechat_account.id},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert [name for name, _ in calls] == ["refresh", "cover"]
    assert calls[-1][1]["access_token"] == "refreshed-token"


@pytest.mark.parametrize("expires_at", [float("inf"), float("-inf"), float("nan")])
def test_wechat_mp_token_cache_rejects_non_finite_expiry(expires_at):
    from backend.app.services.wechat_mp_token_service import get_cached_access_token

    assert get_cached_access_token({"access_token": "cached-token", "expires_at": expires_at}) is None


def test_sync_wechat_mp_draft_hides_foreign_article_and_account(api_client, auth_headers, created_wechat_article_with_image, created_wechat_account):
    client, _ = api_client
    other = client.post("/api/auth/register", json={"username": "wechat-other", "password": "secret123"})
    assert other.status_code == 200
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": created_wechat_account.id},
        headers=other_headers,
    )

    assert response.status_code == 404

    foreign_account = client.post(
        "/api/platforms/wechat-mp/accounts",
        json={"name": "其他公众号", "app_id": "wx-other", "app_secret": "secret-value"},
        headers=other_headers,
    )
    assert foreign_account.status_code == 201
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": foreign_account.json()["id"]},
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_sync_wechat_mp_draft_maps_api_errors_to_502(api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
    from backend.app.services import wechat_mp_draft_service as draft_service

    client, _ = api_client

    class FailingAdapter:
        def upload_permanent_image(self, **kwargs):
            raise WechatMpApiError("wechat permanent image upload failed", errcode=40001, payload={"errcode": 40001, "errmsg": "invalid credential"})

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: FailingAdapter())
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": created_wechat_account.id},
        headers=auth_headers,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "message": "WeChat draft sync failed",
        "errcode": 40001,
        "payload": {"errcode": 40001, "errmsg": "invalid credential"},
    }


@pytest.fixture
def synced_wechat_article(api_client, auth_headers, created_wechat_article, created_wechat_account):
    _, session_factory = api_client
    from backend.app.models import User, WechatMpDraftSync

    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        draft_sync = WechatMpDraftSync(
            user_id=owner.id,
            account_id=created_wechat_account.id,
            article_id=created_wechat_article.id,
            wechat_media_id="wechat_draft_media_id",
            status="synced",
            raw_response={"media_id": "wechat_draft_media_id"},
        )
        session.add(draft_sync)
        session.commit()
        return created_wechat_article
    finally:
        session.close()


def test_submit_publish_job_requires_synced_draft_and_records_publish_id(api_client, auth_headers, synced_wechat_article, monkeypatch):
    from backend.app.services import wechat_mp_publish_service as publish_service

    class FakeAdapter:
        def submit_publish(self, **kwargs):
            return {"publish_id": "publish_001"}

    monkeypatch.setattr(publish_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    client, _ = api_client
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True},
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["publish_id"] == "publish_001"
    assert data["status"] == "submitted"

    _, session_factory = api_client
    session = session_factory()
    try:
        from backend.app.models import WechatMpArticle

        assert session.get(WechatMpArticle, synced_wechat_article.id).status == "publish_pending"
    finally:
        session.close()


def test_submit_publish_job_schedules_without_calling_wechat(api_client, auth_headers, synced_wechat_article, monkeypatch):
    from backend.app.services import wechat_mp_publish_service as publish_service

    class FakeAdapter:
        def submit_publish(self, **kwargs):
            raise AssertionError("scheduled jobs must not be submitted immediately")

    monkeypatch.setattr(publish_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    client, _ = api_client
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True, "scheduled_at": "2030-01-02T03:04:05"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["status"] == "scheduled"
    assert response.json()["publish_id"] == ""


def test_submit_publish_job_requires_confirmation(api_client, auth_headers, synced_wechat_article):
    client, _ = api_client
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": False},
        headers=auth_headers,
    )

    assert response.status_code == 400


def test_poll_publish_job_maps_wechat_status_and_stores_response(api_client, auth_headers, synced_wechat_article, monkeypatch):
    from backend.app.services import wechat_mp_publish_service as publish_service

    class FakeAdapter:
        def submit_publish(self, **kwargs):
            return {"publish_id": "publish_001"}

        def get_publish_status(self, **kwargs):
            return {"publish_id": "publish_001", "publish_status": 0, "article_id": "article_001"}

    monkeypatch.setattr(publish_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    client, _ = api_client
    submitted = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True},
        headers=auth_headers,
    )
    response = client.post(
        f"/api/platforms/wechat-mp/publish-jobs/{submitted.json()['id']}/poll",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "published"
    assert response.json()["raw_response"]["article_id"] == "article_001"

    _, session_factory = api_client
    session = session_factory()
    try:
        from backend.app.models import WechatMpArticle

        assert session.get(WechatMpArticle, synced_wechat_article.id).status == "published"
    finally:
        session.close()


@pytest.mark.parametrize("publish_status", [2, 3, 4, 5, 6])
def test_poll_publish_job_maps_terminal_failures_and_keeps_article_editable(
    api_client, auth_headers, synced_wechat_article, monkeypatch, publish_status
):
    from backend.app.services import wechat_mp_publish_service as publish_service

    class FakeAdapter:
        def submit_publish(self, **kwargs):
            return {"publish_id": "publish_001"}

        def get_publish_status(self, **kwargs):
            return {"publish_id": "publish_001", "publish_status": publish_status, "errmsg": "content rejected"}

    monkeypatch.setattr(publish_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    client, session_factory = api_client
    submitted = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True},
        headers=auth_headers,
    )
    response = client.post(
        f"/api/platforms/wechat-mp/publish-jobs/{submitted.json()['id']}/poll",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_message"] == "content rejected"

    session = session_factory()
    try:
        from backend.app.models import WechatMpArticle

        assert session.get(WechatMpArticle, synced_wechat_article.id).status == "synced_to_wechat"
    finally:
        session.close()


def test_publish_routes_hide_foreign_article_and_map_api_failure_to_502(api_client, auth_headers, synced_wechat_article, monkeypatch):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
    from backend.app.services import wechat_mp_publish_service as publish_service

    class FailingAdapter:
        def submit_publish(self, **kwargs):
            raise WechatMpApiError(
                "wechat publish submit failed",
                errcode=48001,
                payload={"errcode": 48001, "errmsg": "api unauthorized"},
            )

    monkeypatch.setattr(publish_service, "WechatMpApiAdapter", lambda: FailingAdapter())
    client, _ = api_client
    other = client.post("/api/auth/register", json={"username": "publish-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    foreign = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True},
        headers=other_headers,
    )
    failed = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True},
        headers=auth_headers,
    )

    assert foreign.status_code == 404
    assert failed.status_code == 502
    assert "48001" in failed.json()["detail"]
    assert "api unauthorized" in failed.json()["detail"]


@pytest.fixture
def created_wechat_prompt(api_client, auth_headers, created_wechat_article):
    client, session_factory = api_client
    from backend.app.models import User, WechatMpArticle, WechatMpArticleSection, WechatMpImagePrompt

    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = session.get(WechatMpArticle, created_wechat_article.id)
        section = WechatMpArticleSection(
            user_id=owner.id,
            article_id=article.id,
            section_index=0,
            summary="先完成最小动作",
            source_excerpt="先做最小动作。",
        )
        session.add(section)
        session.flush()
        prompt = WechatMpImagePrompt(
            user_id=owner.id,
            article_id=article.id,
            section_id=section.id,
            skill_name="xiaomao-illustrations",
            prompt="一只小猫开始最小动作",
            editable_prompt="一只小猫开始最小动作",
            status="prompt_ready",
        )
        session.add(prompt)
        session.flush()
        article.status = "prompts_ready"
        session.commit()
        session.refresh(prompt)
        return prompt
    finally:
        session.close()


def test_generate_wechat_mp_image_saves_only_wechat_asset_and_backfills_article(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.models import IllustrationAsset, UsageRecord, WechatMpArticle, WechatMpAsset, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_service as image_service
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: _successful_prompt_batch(kwargs["candidates"], prompt="一只小猫开始最小动作"),
    )

    def fake_generate(*, prompt, model_name, size, **kwargs):
        assert prompt == "一只小猫开始最小动作"
        assert model_name == "doubao-seedream-4-0-250828"
        assert size == "2732x1536"
        return {
            "file_path": "/api/files/media/wechat-mp-u1-p1.png",
            "public_url": "/api/files/media/wechat-mp-u1-p1.png",
            "provider_response": {"ok": True},
        }

    monkeypatch.setattr(image_service, "_call_image_model", fake_generate)
    client, session_factory = api_client
    prompts_response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts",
        headers=auth_headers,
    )
    assert prompts_response.status_code == 201
    prompts = prompts_response.json()["items"]
    prompt_id = prompts[0]["id"]
    html_body = client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}", headers=auth_headers
    ).json()["html_body"]
    assert all(html_body.count(f"{{{{image:prompt-{prompt['id']}}}}}") == 1 for prompt in prompts)

    response = client.post(
        f"/api/platforms/wechat-mp/prompts/{prompt_id}/image",
        json={"image_model": "doubao-seedream-4-0-250828", "size": "16:9"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["prompt_id"] == prompt_id
    session = session_factory()
    try:
        assert session.query(WechatMpAsset).count() == 1
        assert session.query(IllustrationAsset).count() == 0
        assert session.get(WechatMpImagePrompt, prompt_id).status == "generated"
        article = session.get(WechatMpArticle, created_wechat_article.id)
        assert 'src="/api/files/media/wechat-mp-u1-p1.png"' in article.html_body
        assert f"{{{{image:prompt-{prompt_id}}}}}" not in article.html_body
        assert article.status == ("images_ready" if len(prompts) == 1 else "images_partial")
        usage = session.query(UsageRecord).filter_by(step="image_gen", resource_id=article.id).one()
        assert usage.platform == "wechat_mp"
        assert usage.resource_type == "wechat_mp_article"
        assert usage.image_count == 1
        assert article.cost_estimate["total_yuan"] == str(usage.cost_yuan)
        assert article.cost_estimate["calls"] == len(prompts) + 1
    finally:
        session.close()


def test_generate_wechat_mp_image_backfills_plain_alt_text_for_markdown_sections(
    api_client, auth_headers, created_wechat_prompt, monkeypatch
):
    from backend.app.models import WechatMpArticle, WechatMpArticleSection, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_service as image_service

    monkeypatch.setattr(
        image_service,
        "_call_image_model",
        lambda **kwargs: {
            "file_path": "/api/files/media/wechat-clean-alt.png",
            "public_url": "/api/files/media/wechat-clean-alt.png",
            "provider_response": {"ok": True},
        },
    )
    client, session_factory = api_client
    session = session_factory()
    try:
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        section = session.get(WechatMpArticleSection, prompt.section_id)
        section.summary = "| 风格 | 包含类型 |\n|------|----------|\n| **数据流风格** | 批处理序列、管道/过滤器 |"
        section.source_excerpt = "### 数据流风格\n| **数据流风格** | 批处理序列、管道/过滤器 |"
        article = session.get(WechatMpArticle, prompt.article_id)
        article.html_body = f"<p>正文</p>{{{{image:prompt-{prompt.id}}}}}"
        session.commit()
    finally:
        session.close()

    response = client.post(
        f"/api/platforms/wechat-mp/prompts/{created_wechat_prompt.id}/image",
        json={"image_model": "doubao-seedream-4-0-250828", "size": "16:9"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    session = session_factory()
    try:
        html = session.get(WechatMpArticle, created_wechat_prompt.article_id).html_body
        assert 'alt="数据流风格；数据流风格 批处理序列、管道/过滤器"' in html
        assert "|------" not in html
        assert "**" not in html
        assert "###" not in html
    finally:
        session.close()


def test_generate_wechat_mp_image_reuses_similar_existing_asset_without_model_call(
    api_client, auth_headers, created_wechat_prompt, monkeypatch
):
    from backend.app.models import UsageRecord, WechatMpArticle, WechatMpAsset, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_service as image_service

    def fail_generate(**kwargs):
        raise AssertionError("image model should not be called when a similar asset exists")

    monkeypatch.setattr(image_service, "_call_image_model", fail_generate)
    client, session_factory = api_client
    session = session_factory()
    try:
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        prompt.editable_prompt = "一只小猫开始做最小动作，白色背景，16:9 横版构图"
        article = session.get(WechatMpArticle, prompt.article_id)
        article.html_body += f'{{{{image:prompt-{prompt.id}}}}}'
        existing = WechatMpAsset(
            user_id=prompt.user_id,
            article_id=article.id,
            prompt_id=None,
            role="inline_illustration",
            file_path="/tmp/reused-wechat-cat.png",
            public_url="/api/files/media/reused-wechat-cat.png",
            prompt="一只小猫开始做最小动作 白色背景 16:9横版构图",
            skill_name=prompt.skill_name,
            model_name="previous-model",
            status="generated",
            provider_response={"ok": True},
        )
        session.add(existing)
        session.commit()
        existing_id = existing.id
        original_cost = dict(article.cost_estimate or {})
    finally:
        session.close()

    response = client.post(
        f"/api/platforms/wechat-mp/prompts/{created_wechat_prompt.id}/image",
        json={"image_model": "doubao-seedream-4-0-250828", "size": "16:9"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["public_url"] == "/api/files/media/reused-wechat-cat.png"
    assert data["provider_response"]["reused_from_asset_id"] == existing_id
    session = session_factory()
    try:
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        article = session.get(WechatMpArticle, prompt.article_id)
        assert prompt.status == "generated"
        assert 'src="/api/files/media/reused-wechat-cat.png"' in article.html_body
        assert article.cost_estimate == original_cost
        assert session.query(UsageRecord).filter_by(step="image_gen", resource_id=article.id).count() == 0
        assert session.query(WechatMpAsset).filter_by(prompt_id=prompt.id).count() == 1
    finally:
        session.close()


def test_wechat_mp_assets_are_owner_scoped_and_delete_local_media(api_client, auth_headers, created_wechat_prompt, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from backend.app.models import User, WechatMpAsset
    from backend.app.api.platforms.wechat_mp import assets as assets_api

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    local_file = media_dir / "wechat-mp-u1-delete.png"
    local_file.write_bytes(b"image")
    monkeypatch.setattr(assets_api, "get_settings", lambda: SimpleNamespace(storage_dir=tmp_path))

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        asset = WechatMpAsset(
            user_id=owner.id,
            article_id=created_wechat_prompt.article_id,
            prompt_id=created_wechat_prompt.id,
            role="inline_illustration",
            file_path=str(local_file),
            public_url="/api/files/media/wechat-mp-u1-delete.png",
            prompt="一只小猫",
            skill_name="xiaomao-illustrations",
            model_name="doubao-seedream-4-0-250828",
        )
        session.add(asset)
        session.commit()
        asset_id = asset.id
    finally:
        session.close()

    assert client.get("/api/platforms/wechat-mp/assets", headers=auth_headers).json()["items"][0]["id"] == asset_id
    other = client.post("/api/auth/register", json={"username": "wechat-asset-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.get("/api/platforms/wechat-mp/assets", headers=other_headers).json()["items"] == []
    assert client.delete(f"/api/platforms/wechat-mp/assets/{asset_id}", headers=other_headers).status_code == 404

    deleted = client.delete(f"/api/platforms/wechat-mp/assets/{asset_id}", headers=auth_headers)
    assert deleted.status_code == 200
    assert not local_file.exists()
def _create_wechat_account(client, headers):
    response = client.post(
        "/api/platforms/wechat-mp/accounts",
        json={"name": "主号", "app_id": "wx123", "app_secret": "secret-value"},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def test_wechat_mp_account_create_never_returns_secret(api_client, auth_headers):
    client, session_factory = api_client

    data = _create_wechat_account(client, auth_headers)

    assert data["name"] == "主号"
    assert data["app_id"] == "wx123"
    assert "app_secret" not in data
    assert "encrypted_app_secret" not in data
    assert "token_cache" not in data

    from backend.app.models import WechatMpAccount

    session = session_factory()
    try:
        account = session.get(WechatMpAccount, data["id"])
        assert account.encrypted_app_secret != "secret-value"
    finally:
        session.close()


def test_wechat_mp_account_delete_is_owner_scoped(api_client, auth_headers):
    client, session_factory = api_client
    data = _create_wechat_account(client, auth_headers)
    other = client.post("/api/auth/register", json={"username": "wechat-account-delete-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    assert client.delete(f"/api/platforms/wechat-mp/accounts/{data['id']}", headers=other_headers).status_code == 404

    deleted = client.delete(f"/api/platforms/wechat-mp/accounts/{data['id']}", headers=auth_headers)
    assert deleted.status_code == 200
    assert deleted.json() == {"id": data["id"], "status": "deleted"}
    assert client.get("/api/platforms/wechat-mp/accounts", headers=auth_headers).json() == []

    from backend.app.models import WechatMpAccount

    session = session_factory()
    try:
        assert session.get(WechatMpAccount, data["id"]) is None
    finally:
        session.close()


def test_wechat_mp_accounts_page_exposes_delete_action():
    source = Path("frontend/src/pages/platforms/wechat-mp/accounts-page.tsx").read_text(encoding="utf-8")
    api_source = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")

    assert "deleteWechatMpAccount" in api_source
    assert "deleteWechatMpAccount" in source
    assert "删除账号" in source
    assert "Popconfirm" in source


def test_wechat_mp_assets_image_grid_prevents_card_overflow():
    source = Path("frontend/src/pages/platforms/wechat-mp/assets-page.tsx").read_text(encoding="utf-8")

    assert "minmax(min(100%, 280px), 1fr)" in source
    assert 'maxWidth: "100%"' in source
    assert 'overflowWrap: "anywhere"' in source
    assert 'styles={{ body: { overflow: "hidden" } }}' in source


def test_wechat_mp_material_feishu_config_is_exposed_to_container():
    from pathlib import Path

    compose_source = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "FEISHU_APP_ID=${FEISHU_APP_ID:-}" in compose_source
    assert "FEISHU_APP_SECRET=${FEISHU_APP_SECRET:-}" in compose_source
    assert "LARK_APP_ID=${LARK_APP_ID:-}" in compose_source
    assert "LARK_APP_SECRET=${LARK_APP_SECRET:-}" in compose_source


def test_wechat_mp_material_parse_feishu_surfaces_backend_detail():
    from pathlib import Path

    source = Path("frontend/src/pages/platforms/wechat-mp/assets-page.tsx").read_text(encoding="utf-8")

    assert "function errorMessage" in source
    assert "response?.data?.detail" in source
    assert "catch (err)" in source
    assert "errorMessage(err" in source


def test_wechat_mp_material_library_crud_is_owner_scoped(api_client, auth_headers):
    client, _ = api_client

    created = client.post(
        "/api/platforms/wechat-mp/materials",
        json={
            "title": "软考资料",
            "material_type": "text",
            "content": "信息系统工程核心考点",
            "source_url": "https://example.com/source",
            "tags": ["软考", "公众号"],
            "notes": "适合整理成速查手册",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    material_id = created.json()["id"]

    listed = client.get("/api/platforms/wechat-mp/materials?q=软考", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["title"] == "软考资料"

    updated = client.patch(
        f"/api/platforms/wechat-mp/materials/{material_id}",
        json={"notes": "更新后的备注", "tags": ["考试"]},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["notes"] == "更新后的备注"
    assert updated.json()["tags"] == ["考试"]

    other = client.post("/api/auth/register", json={"username": "wechat-material-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.get("/api/platforms/wechat-mp/materials", headers=other_headers).json()["total"] == 0
    assert client.patch(
        f"/api/platforms/wechat-mp/materials/{material_id}",
        json={"title": "偷改"},
        headers=other_headers,
    ).status_code == 404

    deleted = client.delete(f"/api/platforms/wechat-mp/materials/{material_id}", headers=auth_headers)
    assert deleted.status_code == 200
    assert client.get("/api/platforms/wechat-mp/materials", headers=auth_headers).json()["total"] == 0


def test_wechat_mp_material_upload_file_is_owner_scoped(api_client, auth_headers):
    client, _ = api_client

    uploaded = client.post(
        "/api/platforms/wechat-mp/materials/upload",
        files={"file": ("brief.md", b"# brief\nhello", "text/markdown")},
        headers=auth_headers,
    )
    assert uploaded.status_code == 201
    data = uploaded.json()
    assert data["material_type"] == "file"
    assert data["original_file_name"] == "brief.md"
    assert data["file_size"] == len(b"# brief\nhello")
    assert data["download_url"].startswith("/api/platforms/wechat-mp/materials/files/")

    downloaded = client.get(data["download_url"], headers=auth_headers)
    assert downloaded.status_code == 200
    assert downloaded.content == b"# brief\nhello"

    other = client.post("/api/auth/register", json={"username": "wechat-material-file-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.get(data["download_url"], headers=other_headers).status_code == 404

    deleted = client.delete(f"/api/platforms/wechat-mp/materials/{data['id']}", headers=auth_headers)
    assert deleted.status_code == 200
    assert client.get(data["download_url"], headers=auth_headers).status_code == 404


def test_wechat_mp_material_parse_feishu_updates_content(api_client, auth_headers, monkeypatch):
    from backend.app.api.platforms.wechat_mp import materials as materials_api

    client, _ = api_client
    monkeypatch.setenv("FEISHU_APP_ID", "cli_a_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret-value")
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    def fake_post(url, json, timeout):
        calls.append(("token", url, json, timeout))
        return FakeResponse({"code": 0, "tenant_access_token": "tenant-token"})

    def fake_get(url, headers, timeout):
        calls.append(("raw", url, headers, timeout))
        return FakeResponse({"code": 0, "data": {"content": "飞书正文内容\n\n适合写公众号。"}})

    monkeypatch.setattr(materials_api.requests, "post", fake_post)
    monkeypatch.setattr(materials_api.requests, "get", fake_get)

    created = client.post(
        "/api/platforms/wechat-mp/materials",
        json={
            "title": "飞书资料",
            "material_type": "link",
            "source_url": "https://example.feishu.cn/docx/AbCd1234?from=copylink",
            "tags": ["资料"],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201

    parsed = client.post(
        f"/api/platforms/wechat-mp/materials/{created.json()['id']}/parse-feishu",
        headers=auth_headers,
    )

    assert parsed.status_code == 200
    data = parsed.json()
    assert data["content"] == "飞书正文内容\n\n适合写公众号。"
    assert data["material_type"] == "link"
    assert data["tags"] == ["资料", "飞书"]
    assert calls[0] == (
        "token",
        materials_api.FEISHU_TOKEN_URL,
        {"app_id": "cli_a_test", "app_secret": "secret-value"},
        20,
    )
    assert calls[1] == (
        "raw",
        "https://open.feishu.cn/open-apis/docx/v1/documents/AbCd1234/raw_content",
        {"Authorization": "Bearer tenant-token"},
        30,
    )


def test_wechat_mp_material_parse_feishu_wiki_resolves_node_before_content(api_client, auth_headers, monkeypatch):
    from backend.app.api.platforms.wechat_mp import materials as materials_api

    client, _ = api_client
    monkeypatch.setenv("FEISHU_APP_ID", "cli_a_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret-value")
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    def fake_post(url, json, timeout):
        calls.append(("token", url, json, timeout))
        return FakeResponse({"code": 0, "tenant_access_token": "tenant-token"})

    def fake_get(url, headers, timeout):
        calls.append(("get", url, headers, timeout))
        if "wiki/v2/spaces/get_node" in url:
            return FakeResponse({"code": 0, "data": {"node": {"obj_type": "docx", "obj_token": "DocxRealToken"}}})
        return FakeResponse({"code": 0, "data": {"content": "知识库正文内容"}})

    monkeypatch.setattr(materials_api.requests, "post", fake_post)
    monkeypatch.setattr(materials_api.requests, "get", fake_get)

    created = client.post(
        "/api/platforms/wechat-mp/materials",
        json={
            "title": "飞书知识库资料",
            "material_type": "link",
            "source_url": "https://example.feishu.cn/wiki/WikiNodeToken?from=from_copylink",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201

    parsed = client.post(
        f"/api/platforms/wechat-mp/materials/{created.json()['id']}/parse-feishu",
        headers=auth_headers,
    )

    assert parsed.status_code == 200
    assert parsed.json()["content"] == "知识库正文内容"
    assert calls[1] == (
        "get",
        "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?token=WikiNodeToken",
        {"Authorization": "Bearer tenant-token"},
        30,
    )
    assert calls[2] == (
        "get",
        "https://open.feishu.cn/open-apis/docx/v1/documents/DocxRealToken/raw_content",
        {"Authorization": "Bearer tenant-token"},
        30,
    )


def test_wechat_mp_material_parse_feishu_rejects_unsupported_link_types():
    from backend.app.api.platforms.wechat_mp.materials import FeishuMaterialParseError, _parse_feishu_document

    try:
        _parse_feishu_document("https://example.feishu.cn/base/AbCd1234")
    except FeishuMaterialParseError as exc:
        assert "暂只支持飞书 docx/doc/wiki 文档链接" in str(exc)
    else:
        raise AssertionError("base links should not be accepted as documents")


def test_wechat_mp_material_parse_feishu_requires_credentials(api_client, auth_headers, monkeypatch):
    client, _ = api_client
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.delenv("LARK_APP_ID", raising=False)
    monkeypatch.delenv("LARK_APP_SECRET", raising=False)

    created = client.post(
        "/api/platforms/wechat-mp/materials",
        json={
            "title": "飞书资料",
            "material_type": "link",
            "source_url": "https://example.feishu.cn/docx/AbCd1234",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201

    parsed = client.post(
        f"/api/platforms/wechat-mp/materials/{created.json()['id']}/parse-feishu",
        headers=auth_headers,
    )

    assert parsed.status_code == 400
    assert "未配置飞书应用凭证" in parsed.json()["detail"]


def test_wechat_mp_writer_shows_inline_generated_images_next_to_prompts():
    source = Path("frontend/src/pages/platforms/wechat-mp/writer-page.tsx").read_text(encoding="utf-8")

    assert "promptAsset" in source
    assert "段落配图预览" in source
    assert "重新生成正文图片" in source
    assert "focusPromptId" in source
    assert "scrollIntoView" in source
    assert "wechat-prompt-" in source
    assert ">保存提示词<" not in source


def test_wechat_mp_writer_cover_generation_is_independent_and_inline_previewed():
    source = Path("frontend/src/pages/platforms/wechat-mp/writer-page.tsx").read_text(encoding="utf-8")

    assert "coverBusy" in source
    assert "setCoverBusy(true)" in source
    assert "loading={coverBusy}" in source
    assert "封面提示词" in source
    assert "封面预览" in source
    assert "article.cover_brief" in source
    assert "coverAsset.public_url" in source
    assert "loading={promptBusy}" in source


def test_wechat_mp_illustration_characters_are_user_managed(api_client, auth_headers):
    client, _ = api_client

    listed = client.get("/api/platforms/wechat-mp/illustration-characters", headers=auth_headers)
    assert listed.status_code == 200
    assert [item["skill_name"] for item in listed.json()][:2] == ["xiaomao-illustrations", "none"]
    assert listed.json()[0]["name"] == "小猫生图"
    assert "少量浅橙、红、蓝批注" not in listed.json()[0]["prompt"]

    created = client.post(
        "/api/platforms/wechat-mp/illustration-characters",
        json={
            "name": "白熊讲师",
            "prompt": "白色北极熊讲师，戴圆框眼镜，温和但专业，白底手绘线稿。",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    data = created.json()
    assert data["name"] == "白熊讲师"
    assert data["skill_name"].startswith("custom-")
    assert data["is_builtin"] is False

    listed_again = client.get("/api/platforms/wechat-mp/illustration-characters", headers=auth_headers)
    assert any(item["skill_name"] == data["skill_name"] and "白色北极熊讲师" in item["prompt"] for item in listed_again.json())

    other = client.post("/api/auth/register", json={"username": "wechat-character-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert all(item["skill_name"] != data["skill_name"] for item in client.get("/api/platforms/wechat-mp/illustration-characters", headers=other_headers).json())


def test_wechat_mp_character_requires_four_confirmed_views_and_replacement_resets_state(api_client, auth_headers):
    client, _ = api_client
    created = client.post(
        "/api/platforms/wechat-mp/illustration-characters",
        json={"name": "四视图熊", "prompt": "固定外观的手绘白熊。"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    character_id = created.json()["id"]
    assert [view["view"] for view in created.json()["views"]] == ["front", "back", "left", "right"]

    missing = client.post(
        f"/api/platforms/wechat-mp/illustration-characters/{character_id}/views/front/confirm",
        headers=auth_headers,
    )
    assert missing.status_code == 400

    for view in ("front", "back", "left", "right"):
        uploaded = client.post(
            f"/api/platforms/wechat-mp/illustration-characters/{character_id}/views/{view}/upload",
            files={"file": (f"{view}.png", b"not-a-real-png-but-a-stored-test-file", "image/png")},
            headers=auth_headers,
        )
        assert uploaded.status_code == 201
        confirmed = client.post(
            f"/api/platforms/wechat-mp/illustration-characters/{character_id}/views/{view}/confirm",
            headers=auth_headers,
        )
        assert confirmed.status_code == 200

    listed = client.get("/api/platforms/wechat-mp/illustration-characters", headers=auth_headers).json()
    character = next(item for item in listed if item["id"] == character_id)
    assert character["status"] == "confirmed"
    assert character["is_available"] is True

    replacement = client.post(
        f"/api/platforms/wechat-mp/illustration-characters/{character_id}/views/front/upload",
        files={"file": ("front.png", b"replacement", "image/png")},
        headers=auth_headers,
    )
    assert replacement.status_code == 201
    listed_after = client.get("/api/platforms/wechat-mp/illustration-characters", headers=auth_headers).json()
    character_after = next(item for item in listed_after if item["id"] == character_id)
    assert character_after["status"] == "draft"
    assert character_after["is_available"] is False


def test_wechat_mp_character_view_endpoints_are_owner_scoped(api_client, auth_headers):
    client, _ = api_client
    created = client.post(
        "/api/platforms/wechat-mp/illustration-characters",
        json={"name": "私有角色", "prompt": "只属于当前用户。"},
        headers=auth_headers,
    )
    other = client.post("/api/auth/register", json={"username": "wechat-four-view-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    response = client.post(
        f"/api/platforms/wechat-mp/illustration-characters/{created.json()['id']}/views/front/confirm",
        headers=other_headers,
    )
    assert response.status_code == 404


def test_custom_wechat_mp_character_prompt_is_used_for_image_prompt(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    client, _ = api_client
    created = client.post(
        "/api/platforms/wechat-mp/illustration-characters",
        json={"name": "小护士", "prompt": "主角是一名小护士，蓝白制服，手绘科普风。"},
        headers=auth_headers,
    )
    skill_name = created.json()["skill_name"]
    captured = {}

    def fake_prompt_batch(**kwargs):
        captured["character_prompt"] = kwargs["character"].prompt
        return _successful_prompt_batch(kwargs["candidates"], prompt="画面：小护士指向流程图")

    monkeypatch.setattr(prompt_service, "generate_semantic_prompts", fake_prompt_batch)
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts",
        json={"skill_name": skill_name},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["items"][0]["skill_name"] == skill_name
    assert "主角是一名小护士" in captured["character_prompt"]


def test_wechat_mp_writer_can_select_materials_from_library():
    writer_source = Path("frontend/src/pages/platforms/wechat-mp/writer-page.tsx").read_text(encoding="utf-8")
    assets_source = Path("frontend/src/pages/platforms/wechat-mp/assets-page.tsx").read_text(encoding="utf-8")

    assert "fetchWechatMpMaterials" in writer_source
    assert "fetchWechatMpIllustrationCharacters" in writer_source
    assert "createWechatMpIllustrationCharacter" not in writer_source
    assert "自定义形象提示词" not in writer_source
    assert "/platforms/wechat-mp/characters" in writer_source
    assert "形象管理" in writer_source
    assert "selectedMaterialIds" in writer_source
    assert "material_ids: selectedMaterialIds" in writer_source
    assert "从资料库选择素材" in writer_source
    assert "usage_status" in assets_source
    assert "已写过" in assets_source
    assert "未使用" in assets_source


def test_wechat_mp_character_management_is_a_separate_module():
    page_source = Path("frontend/src/pages/platforms/wechat-mp/characters-page.tsx").read_text(encoding="utf-8")
    router_source = Path("frontend/src/app/router.tsx").read_text(encoding="utf-8")
    shell_source = Path("frontend/src/components/layout/app-shell.tsx").read_text(encoding="utf-8")

    assert "WechatMpCharactersPage" in page_source
    assert "fetchWechatMpIllustrationCharacters" in page_source
    assert "createWechatMpIllustrationCharacter" in page_source
    assert "自定义形象提示词" in page_source
    assert "新增形象" in page_source
    assert "形象库" in page_source
    assert "/platforms/wechat-mp/characters" in router_source
    assert "/platforms/wechat-mp/characters" in shell_source
    assert 'label: "形象"' in shell_source


def test_wechat_mp_layout_removes_duplicate_tab_navigation():
    layout_source = Path("frontend/src/pages/platforms/wechat-mp/wechat-mp-layout.tsx").read_text(encoding="utf-8")

    assert "Segmented" not in layout_source
    assert "sections" not in layout_source
    assert "useNavigate" not in layout_source


def test_global_nav_keeps_last_workspace_on_shared_pages():
    shell_source = Path("frontend/src/components/layout/app-shell.tsx").read_text(encoding="utf-8")

    assert 'localStorage.getItem("spider-last-workspace")' in shell_source
    assert 'localStorage.setItem("spider-last-workspace", "wechat-mp")' in shell_source
    assert 'localStorage.setItem("spider-last-workspace", "xhs")' in shell_source
    assert 'lastWorkspace === "wechat-mp"' in shell_source
    assert '{ key: "/tasks", icon: <ScheduleOutlined />, label: "任务中心" }' in shell_source
    assert '{ key: "/models", icon: <RobotOutlined />, label: "模型配置" }' in shell_source


def test_wechat_mp_account_list_is_scoped_to_owner(api_client, auth_headers):
    client, _ = api_client
    _create_wechat_account(client, auth_headers)
    other = client.post("/api/auth/register", json={"username": "wechat-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    response = client.get("/api/platforms/wechat-mp/accounts", headers=other_headers)

    assert response.status_code == 200
    assert response.json() == []


def test_wechat_mp_account_test_hides_foreign_account(api_client, auth_headers):
    client, _ = api_client
    account = _create_wechat_account(client, auth_headers)
    other = client.post("/api/auth/register", json={"username": "wechat-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    response = client.post(f"/api/platforms/wechat-mp/accounts/{account['id']}/test", headers=other_headers)

    assert response.status_code == 404


def test_wechat_mp_account_test_returns_404_for_nonexistent_account(api_client, auth_headers):
    client, _ = api_client

    response = client.post("/api/platforms/wechat-mp/accounts/999999/test", headers=auth_headers)

    assert response.status_code == 404


def test_wechat_mp_account_test_surfaces_wechat_error_detail(api_client, auth_headers, monkeypatch):
    client, session_factory = api_client
    account = _create_wechat_account(client, auth_headers)

    class FakeWechatMpAdapter:
        def get_access_token(self, *, app_id, app_secret):
            from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError

            raise WechatMpApiError(
                "wechat access_token request failed",
                errcode=40164,
                payload={"errcode": 40164, "errmsg": "invalid ip 124.160.245.210, not in whitelist"},
            )

    from backend.app.api.platforms.wechat_mp.accounts import get_wechat_mp_api_adapter
    from backend.app.main import app

    app.dependency_overrides[get_wechat_mp_api_adapter] = lambda: FakeWechatMpAdapter()
    try:
        response = client.post(f"/api/platforms/wechat-mp/accounts/{account['id']}/test", headers=auth_headers)
    finally:
        app.dependency_overrides.pop(get_wechat_mp_api_adapter, None)

    assert response.status_code == 502
    assert "not in whitelist" in response.json()["detail"]
    assert "40164" in response.json()["detail"]

    from backend.app.models import WechatMpAccount

    session = session_factory()
    try:
        stored = session.get(WechatMpAccount, account["id"])
        assert stored.connection_status == "error"
    finally:
        session.close()


def test_wechat_mp_account_test_caches_successful_token(api_client, auth_headers, monkeypatch):
    client, session_factory = api_client
    account = _create_wechat_account(client, auth_headers)

    class FakeWechatMpAdapter:
        def get_access_token(self, *, app_id, app_secret):
            assert app_id == "wx123"
            assert app_secret == "secret-value"
            return {"access_token": "token-value", "expires_in": 7200}

    from backend.app.api.platforms.wechat_mp.accounts import get_wechat_mp_api_adapter
    from backend.app.main import app

    app.dependency_overrides[get_wechat_mp_api_adapter] = lambda: FakeWechatMpAdapter()
    try:
        response = client.post(f"/api/platforms/wechat-mp/accounts/{account['id']}/test", headers=auth_headers)
    finally:
        app.dependency_overrides.pop(get_wechat_mp_api_adapter, None)

    assert response.status_code == 200
    assert response.json()["connection_status"] == "connected"
    from backend.app.models import WechatMpAccount

    session = session_factory()
    try:
        stored = session.get(WechatMpAccount, account["id"])
        from backend.app.services.wechat_mp_token_service import get_cached_access_token
        assert "token-value" not in str(stored.token_cache)
        assert get_cached_access_token(stored.token_cache) == "token-value"
        assert stored.token_cache["expires_in"] == 7200
        assert time.time() + 7100 < stored.token_cache["expires_at"] < time.time() + 7200
    finally:
        session.close()


def test_create_wechat_mp_article_generates_markdown_html_and_usage(api_client, auth_headers, monkeypatch):
    from backend.app.models import UsageRecord
    from backend.app.services import wechat_mp_writer_service as writer
    from backend.app.services.wechat_mp_character_service import XIAOMAO_PROMPT

    def fake_call(*, topic, source_material, target_reader, tone, model_name, **kwargs):
        return {
            "title": "会偷懒的人，反而更稳定",
            "markdown_body": "## 开头\n正文第一段\n\n## 方法\n正文第二段",
            "digest": "一篇关于稳定输出的文章",
            "cover_brief": f"{XIAOMAO_PROMPT}\n小猫压住一张计划表",
            "input_tokens": 100,
            "output_tokens": 200,
            "model_name": model_name,
        }

    monkeypatch.setattr(writer, "_call_writer_model", fake_call)
    client, session_factory = api_client
    response = client.post(
        "/api/platforms/wechat-mp/articles",
        json={"title": "稳定输出", "topic": "稳定输出", "illustration_skill": "xiaomao-illustrations"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "会偷懒的人，反而更稳定"
    assert "<h2>开头</h2>" in data["html_body"]
    assert data["illustration_skill"] == "xiaomao-illustrations"
    assert data["cover_brief"] == "主角：@小猫生图\n具体画面：小猫压住一张计划表"

    session = session_factory()
    try:
        assert session.query(UsageRecord).filter_by(platform="wechat_mp", step="write_article").count() == 1
    finally:
        session.close()


def test_writer_requests_a_visual_cover_scene_instead_of_a_title_repetition():
    from backend.app.services.wechat_mp_writer_service import _WRITER_PROMPT

    assert "cover_brief 必须描述可直接绘制的封面场景" in _WRITER_PROMPT
    assert "不能只复述文章标题" in _WRITER_PROMPT
    assert "主题结构是主体，角色只作辅助" in _WRITER_PROMPT


def test_create_wechat_mp_article_can_use_material_library_items(api_client, auth_headers, monkeypatch):
    from backend.app.models import WechatMpArticleMaterial
    from backend.app.services import wechat_mp_writer_service as writer

    captured = {}

    def fake_call(*, topic, source_material, target_reader, tone, model_name, **kwargs):
        captured["source_material"] = source_material
        return {
            "title": "用资料写出的文章",
            "markdown_body": "## 开头\n资料里的观点已经被使用",
            "digest": "资料文章",
            "cover_brief": "小猫翻资料",
            "input_tokens": 100,
            "output_tokens": 200,
            "model_name": model_name,
        }

    monkeypatch.setattr(writer, "_call_writer_model", fake_call)
    client, session_factory = api_client
    material = client.post(
        "/api/platforms/wechat-mp/materials",
        json={
            "title": "飞书整理",
            "material_type": "link",
            "content": "飞书解析后的重点：先写结论，再补案例。",
            "source_url": "https://example.feishu.cn/docx/AbCd1234",
            "notes": "适合写公众号",
        },
        headers=auth_headers,
    )
    assert material.status_code == 201
    material_id = material.json()["id"]

    created = client.post(
        "/api/platforms/wechat-mp/articles",
        json={
            "title": "资料选题",
            "topic": "资料选题",
            "source_material": "手动补充素材",
            "material_ids": [material_id],
        },
        headers=auth_headers,
    )

    assert created.status_code == 201
    assert "飞书整理" in captured["source_material"]
    assert "飞书解析后的重点" in captured["source_material"]
    assert "手动补充素材" in captured["source_material"]
    session = session_factory()
    try:
        links = session.query(WechatMpArticleMaterial).all()
        assert len(links) == 1
        assert links[0].article_id == created.json()["id"]
        assert links[0].material_id == material_id
    finally:
        session.close()

    materials = client.get("/api/platforms/wechat-mp/materials", headers=auth_headers)
    assert materials.status_code == 200
    item = materials.json()["items"][0]
    assert item["usage_status"] == "used"
    assert item["used_article_count"] == 1


def test_generate_prompts_defaults_to_xiaomao_skill(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    def fake_prompt_batch(**kwargs):
        assert kwargs["character"].skill_name == "xiaomao-illustrations"
        return _successful_prompt_batch(
            kwargs["candidates"],
            prompt="Generate one 16:9 Chinese article illustration. 小猫 lazily presses a messy note stack.",
            input_tokens=50,
            output_tokens=80,
        )

    monkeypatch.setattr(prompt_service, "generate_semantic_prompts", fake_prompt_batch)
    client, _ = api_client
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts",
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()["items"]
    assert data[0]["skill_name"] == "xiaomao-illustrations"
    assert data[0]["editable_prompt"].startswith("主角：@小猫生图\n具体画面：")
    assert "主角必须是一只胖胖慵懒" not in data[0]["editable_prompt"]
    assert data[0]["editable_prompt"].count("主角：@") == 1
    assert data[0]["status"] == "prompt_ready"
    assert data[0]["version"] == 1
    assert data[0]["editable_prompt"] == data[0]["prompt"]


def test_list_prompts_returns_persisted_prompts_for_owned_article(api_client, auth_headers, created_wechat_prompt):
    client, _ = api_client

    response = client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}/prompts",
        headers=auth_headers,
    )

    assert response.status_code == 200
    prompts = response.json()
    assert len(prompts) == 1
    assert prompts[0]["id"] == created_wechat_prompt.id
    assert prompts[0]["article_id"] == created_wechat_prompt.article_id
    assert prompts[0]["editable_prompt"] == "一只小猫开始最小动作"


def test_list_prompts_repairs_persisted_legacy_character_details(
    api_client, auth_headers, created_wechat_prompt,
):
    from backend.app.models import User, WechatMpImagePrompt
    from backend.app.services.wechat_mp_character_service import ensure_builtin_character

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        character = ensure_builtin_character(session, owner.id)
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        prompt.character_id = character.id
        prompt.skill_name = character.skill_name
        prompt.prompt = (
            "主角：@小猫生图\n"
            "具体画面：白色背景，横向画幅，轻微抖动的手绘线稿；"
            "一只胖胖慵懒的玳瑁猫，半闭眼、冷淡表情；"
            "不得渲染标题、比例、尺寸、提示词、说明文字、水印、签名或图中文字。"
        )
        prompt.editable_prompt = prompt.prompt
        session.commit()
    finally:
        session.close()

    response = client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}/prompts",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()[0]["editable_prompt"] == (
        "主角：@小猫生图\n具体画面：先完成最小动作"
    )
    session = session_factory()
    try:
        repaired = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        assert repaired.prompt == repaired.editable_prompt == response.json()[0]["editable_prompt"]
    finally:
        session.close()


def test_generate_prompts_creates_shotlist_and_records_article_usage(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.models import UsageRecord
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: _successful_prompt_batch(kwargs["candidates"]),
    )
    client, session_factory = api_client
    response = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)

    assert response.status_code == 201
    items = response.json()["items"]
    assert 1 <= len(items) <= 8
    assert all(prompt["cost_estimate"]["total_yuan"] != "" for prompt in items)
    session = session_factory()
    try:
        usages = session.query(UsageRecord).filter_by(step="generate_image_prompts_batch").all()
        assert len(usages) == 1
        assert all(usage.platform == "wechat_mp" for usage in usages)
        assert all(usage.resource_type == "wechat_mp_article" for usage in usages)
        assert all(usage.resource_id == created_wechat_article.id for usage in usages)
    finally:
        session.close()


def test_wechat_mp_shotlist_prioritizes_exact_process_diagrams():
    from backend.app.services.wechat_mp_shotlist_service import choose_candidate_sections

    candidates = choose_candidate_sections(
        "## 数据工程\n\n"
        "2.4 数据标准化\n\n"
        "确定数据需求 → 制定数据标准 → 批准数据标准 → 实施数据标准\n\n"
        "普通解释段落，没有明显图解价值。"
    )

    assert candidates[0]["source_excerpt"] == "确定数据需求 → 制定数据标准 → 批准数据标准 → 实施数据标准"
    assert "图解类型：流程图" in candidates[0]["summary"]
    assert "确定数据需求 -> 制定数据标准 -> 批准数据标准 -> 实施数据标准" in candidates[0]["summary"]


def test_wechat_mp_shotlist_skips_plain_headings_when_diagram_sections_exist():
    from backend.app.services.wechat_mp_shotlist_service import choose_candidate_sections

    candidates = choose_candidate_sections(
        "## 一、软件工程（重点）\n\n"
        "1.1 软件工程组成\n\n"
        "软件工程的三大要素：方法、工具、过程。\n\n"
        "需求获取 → 需求分析 → 需求规格说明书编制 → 需求验证与确认"
    )

    assert all(not item["source_excerpt"].startswith("## ") for item in candidates)
    assert candidates[0]["source_excerpt"] == "需求获取 → 需求分析 → 需求规格说明书编制 → 需求验证与确认"


def test_xiaomao_prompt_contract_preserves_exact_diagram_nodes():
    from backend.app.services.wechat_mp_image_prompt_service import build_skill_prompt

    prompt = build_skill_prompt(
        "xiaomao-illustrations",
        "数据工程",
        "图解类型：流程图\n必须准确呈现节点：确定数据需求 -> 制定数据标准 -> 批准数据标准 -> 实施数据标准\n原文：确定数据需求 → 制定数据标准 → 批准数据标准 → 实施数据标准",
    )

    assert "必须逐字保留图解节点" in prompt
    assert "确定数据需求 -> 制定数据标准 -> 批准数据标准 -> 实施数据标准" in prompt
    assert "不要把流程改成泛化插画" in prompt


def test_deterministic_prompts_keep_canonical_character_mentions_and_exact_labels():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content
    from backend.app.services.wechat_mp_image_prompt_service import build_deterministic_prompt
    from backend.app.models.wechat_mp import WechatMpIllustrationCharacter

    character = WechatMpIllustrationCharacter(name="团团", user_id=1, skill_name="custom-1", prompt="自定义形象")
    analysis = analyze_content(
        "收集需求 → 分析需求 → 确认需求\n\n"
        "| 阶段 | 产物 |\n| --- | --- |\n| 收集 | 清单 |\n\n"
        "输入：原始数据\n输出：标准数据"
    )
    prompts = {
        candidate.kind: build_deterministic_prompt(candidate, character)
        for candidate in analysis.deterministic_candidates
    }

    assert prompts["flow"].startswith("主角：@团团\n具体画面：横向有序流程信息图")
    assert "收集需求 → 分析需求 → 确认需求" in prompts["flow"]
    assert "列为产物" in prompts["table"] and "收集：清单" in prompts["table"]
    assert "输入、原始数据" in prompts["classification"] and "输出、标准数据" in prompts["classification"]
    assert all("标题" not in prompt and "尺寸" not in prompt and "水印" not in prompt for prompt in prompts.values())


def test_ordered_scene_contract_preserves_numbered_rows_in_generation_order():
    from backend.app.services.wechat_mp_image_service import _structured_scene_contract

    contract = _structured_scene_contract(
        "具体画面：# | 过程 | 过程组\n"
        "1 | 规划范围管理 | 规划\n"
        "2 | 收集需求 | 规划\n"
        "3 | 定义范围 | 规划\n"
        "4 | 创建WBS | 规划"
    )

    assert "固定顺序：1 -> 2 -> 3 -> 4" in contract
    assert "1｜规划范围管理｜规划" in contract
    assert "4｜创建WBS｜规划" in contract
    assert "不得交换、合并、省略或新增节点" in contract
    assert "主角最多出现一次" in contract
    assert contract.index("规划范围管理") < contract.index("收集需求") < contract.index("定义范围") < contract.index("创建WBS")

    flow_contract = _structured_scene_contract("确定数据需求 → 制定数据标准 → 批准数据标准 → 实施数据标准")
    assert "固定流程：确定数据需求 -> 制定数据标准 -> 批准数据标准 -> 实施数据标准" in flow_contract
    assert "不得反转箭头" in flow_contract


def test_table_scene_contract_builds_one_integrated_visual_matrix():
    from backend.app.services.wechat_mp_image_service import _structured_scene_contract

    contract = _structured_scene_contract(
        "具体画面：对比项 | 产品范围 | 项目范围\n"
        "定义 | 产品或服务应包含的功能和特征 | 为交付产品所必须做的工作\n"
        "完成判断 | 产品是否满足产品描述 | 是否符合范围基准"
    )

    assert "统一的 3 行 3 列二维对比矩阵" in contract
    assert "同一行横向对比，同一列纵向归类" in contract
    assert "不是多个互不相关的独立插画或文案卡片" in contract
    assert "长句语义转成图标、物体、状态或关系" in contract
    assert "文字只保留表头、行名和必要短标签" in contract
    assert "对比项｜产品范围｜项目范围" in contract
    assert "完成判断｜产品是否满足产品描述｜是否符合范围基准" in contract


def test_deterministic_prompts_use_no_model_calls_or_text_usage(api_client, auth_headers, monkeypatch):
    from backend.app.models import UsageRecord, User, WechatMpArticle
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="不应进入提示词",
            markdown_body="收集需求 → 分析需求 → 确认需求\n\n输入：原始数据\n输出：标准数据",
            html_body="<p>收集需求 → 分析需求 → 确认需求</p><p>输入：原始数据<br>输出：标准数据</p>",
            status="layout_ready",
        )
        session.add(article)
        session.commit()
        article_id = article.id
    finally:
        session.close()

    monkeypatch.setattr(prompt_service, "_call_prompt_model", lambda **kwargs: pytest.fail("deterministic candidates must not call the prompt model"))

    response = client.post(f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers)

    assert response.status_code == 201
    assert [item["cost_estimate"] for item in response.json()["items"]] == [
        {"currency": "CNY", "total_yuan": "0.0000", "calls": 0},
        {"currency": "CNY", "total_yuan": "0.0000", "calls": 0},
    ]
    session = session_factory()
    try:
        assert session.query(UsageRecord).filter_by(step="generate_image_prompt").count() == 0
    finally:
        session.close()


def test_deterministic_prompt_reuse_survives_reruns_and_paragraph_moves(db_session, test_user, monkeypatch):
    from backend.app.models.wechat_mp import WechatMpArticle, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    article = WechatMpArticle(
        user_id=test_user.id,
        title="不应进入提示词",
        markdown_body="说明段落。\n\n收集需求 → 分析需求 → 确认需求\n\n结尾段落。",
        html_body="<p>说明段落。</p><p>收集需求 → 分析需求 → 确认需求</p><p>结尾段落。</p>",
        status="layout_ready",
    )
    db_session.add(article)
    db_session.commit()
    monkeypatch.setattr(prompt_service, "_call_prompt_model", lambda **kwargs: pytest.fail("deterministic candidates must not call the prompt model"))

    first = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )
    rerun = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )
    article.markdown_body = "收集需求 → 分析需求 → 确认需求\n\n说明段落。\n\n结尾段落。"
    article.html_body = "<p>收集需求 → 分析需求 → 确认需求</p><p>说明段落。</p><p>结尾段落。</p>"
    db_session.commit()
    moved = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )

    assert [prompt.id for prompt in rerun] == [prompt.id for prompt in first]
    assert [prompt.id for prompt in moved] == [prompt.id for prompt in first]
    assert db_session.query(WechatMpImagePrompt).filter_by(article_id=article.id).count() == 1


def test_article_patch_preserves_moved_deterministic_prompt_ids_and_cleans_stale_markers(
    api_client, auth_headers, monkeypatch,
):
    from backend.app.models import User, WechatMpArticle
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="流程",
            markdown_body="收集甲 → 分析甲 → 确认甲\n\n收集乙 → 分析乙 → 确认乙",
            html_body="<p>收集甲 → 分析甲 → 确认甲</p><p>收集乙 → 分析乙 → 确认乙</p>",
            status="layout_ready",
        )
        session.add(article)
        session.commit()
        article_id = article.id
    finally:
        session.close()
    monkeypatch.setattr(prompt_service, "_call_prompt_model", lambda **kwargs: pytest.fail("exact flows must not call the prompt model"))

    first = client.post(f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers)
    assert first.status_code == 201
    retained_prompt_id = first.json()["items"][1]["id"]
    stale_prompt_id = first.json()["items"][0]["id"]
    updated = client.patch(
        f"/api/platforms/wechat-mp/articles/{article_id}",
        json={"markdown_body": "收集乙 → 分析乙 → 确认乙"},
        headers=auth_headers,
    )
    assert updated.status_code == 200

    regenerated = client.post(f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers)
    assert regenerated.status_code == 201
    assert [item["id"] for item in regenerated.json()["items"]] == [retained_prompt_id]
    assert [item["id"] for item in client.get(
        f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers,
    ).json()] == [retained_prompt_id]
    html_body = client.get(f"/api/platforms/wechat-mp/articles/{article_id}", headers=auth_headers).json()["html_body"]
    assert f"{{{{image:prompt-{retained_prompt_id}}}}}" in html_body
    assert f"{{{{image:prompt-{stale_prompt_id}}}}}" not in html_body


def test_duplicate_deterministic_blocks_keep_distinct_prompt_ids_across_reruns(
    api_client, auth_headers, monkeypatch,
):
    from backend.app.models import User, WechatMpArticle, WechatMpArticleSection, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="重复流程",
            markdown_body="收集需求 → 分析需求 → 确认需求\n\n收集需求 → 分析需求 → 确认需求",
            html_body="<p>收集需求 → 分析需求 → 确认需求</p><p>收集需求 → 分析需求 → 确认需求</p>",
            status="layout_ready",
        )
        session.add(article)
        session.commit()
        article_id = article.id
    finally:
        session.close()
    monkeypatch.setattr(prompt_service, "_call_prompt_model", lambda **kwargs: pytest.fail("exact flows must not call the prompt model"))

    first = client.post(f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers)
    second = client.post(f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert len({item["id"] for item in first.json()["items"]}) == 2
    assert [item["id"] for item in second.json()["items"]] == [item["id"] for item in first.json()["items"]]
    session = session_factory()
    try:
        assert session.query(WechatMpArticleSection).filter_by(article_id=article_id).count() == 2
        assert session.query(WechatMpImagePrompt).filter_by(article_id=article_id).count() == 2
    finally:
        session.close()


def test_article_patch_blocks_stale_prompt_image_generation_until_reconciliation(
    api_client, auth_headers, monkeypatch,
):
    from backend.app.models import User, WechatMpArticle, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="流程",
            markdown_body="收集需求 → 分析需求 → 确认需求",
            html_body="<p>收集需求 → 分析需求 → 确认需求</p>",
            status="layout_ready",
        )
        session.add(article)
        session.commit()
        article_id = article.id
    finally:
        session.close()
    monkeypatch.setattr(prompt_service, "_call_prompt_model", lambda **kwargs: pytest.fail("exact flows must not call the prompt model"))

    generated = client.post(f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers)
    assert generated.status_code == 201
    prompt_id = generated.json()["items"][0]["id"]
    updated = client.patch(
        f"/api/platforms/wechat-mp/articles/{article_id}",
        json={"markdown_body": "收集新需求 → 分析新需求 → 确认新需求"},
        headers=auth_headers,
    )
    assert updated.status_code == 200

    image = client.post(
        f"/api/platforms/wechat-mp/prompts/{prompt_id}/image",
        json={"size": "16:9"},
        headers=auth_headers,
    )
    assert image.status_code == 502
    assert "not ready" in image.json()["detail"]
    session = session_factory()
    try:
        assert session.get(WechatMpImagePrompt, prompt_id).status == "stale"
    finally:
        session.close()


def test_none_generation_and_regeneration_never_call_models_or_write_usage(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.models import UsageRecord
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service
    from backend.app.services import wechat_mp_model_service as model_service

    client, session_factory = api_client
    monkeypatch.setattr(prompt_service, "_call_prompt_model", lambda **kwargs: pytest.fail("none must not call the prompt model"))
    monkeypatch.setattr(model_service, "resolve_wechat_mp_model", lambda **kwargs: pytest.fail("none must not resolve a text model"))
    updated = client.patch(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}",
        json={"illustration_skill": "none"},
        headers=auth_headers,
    )
    assert updated.status_code == 200

    generated = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts",
        json={"skill_name": "none"},
        headers=auth_headers,
    )
    assert generated.status_code == 201
    assert generated.json()["items"] == []
    session = session_factory()
    try:
        assert session.query(UsageRecord).filter_by(step="generate_image_prompt").count() == 0
    finally:
        session.close()


def test_regenerate_deterministic_prompt_never_calls_a_text_model(api_client, auth_headers, monkeypatch):
    from backend.app.models import UsageRecord, User, WechatMpArticle
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service
    from backend.app.services import wechat_mp_model_service as model_service

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="流程",
            markdown_body="收集需求 → 分析需求 → 确认需求",
            html_body="<p>收集需求 → 分析需求 → 确认需求</p>",
            status="layout_ready",
        )
        session.add(article)
        session.commit()
        article_id = article.id
    finally:
        session.close()
    monkeypatch.setattr(prompt_service, "_call_prompt_model", lambda **kwargs: pytest.fail("exact flows must not call the prompt model"))
    generated = client.post(f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers)
    assert generated.status_code == 201
    monkeypatch.setattr(model_service, "resolve_wechat_mp_model", lambda **kwargs: pytest.fail("deterministic prompts must not resolve a model"))

    regenerated = client.post(
        f"/api/platforms/wechat-mp/articles/{article_id}/prompts/{generated.json()['items'][0]['id']}/regenerate",
        headers=auth_headers,
    )
    assert regenerated.status_code == 200
    assert regenerated.json()["cost_estimate"]["calls"] == 0
    session = session_factory()
    try:
        assert session.query(UsageRecord).filter_by(step="generate_image_prompt").count() == 0
    finally:
        session.close()


def test_generation_fingerprint_separates_missing_character_skills_and_updates_association(db_session, test_user, monkeypatch):
    from backend.app.models.wechat_mp import WechatMpArticle
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    article = WechatMpArticle(
        user_id=test_user.id,
        title="语义段落",
        markdown_body="制定步骤前必须明确问题、方法、风险和结果，避免遗漏关键约束。",
        html_body="<p>制定步骤前必须明确问题、方法、风险和结果，避免遗漏关键约束。</p>",
        status="layout_ready",
    )
    db_session.add(article)
    db_session.commit()
    calls = []

    def fake_batch(**kwargs):
        skill = f"missing-skill-{'a' if not calls else 'b'}"
        calls.append(skill)
        return _successful_prompt_batch(kwargs["candidates"], prompt=skill, input_tokens=1, output_tokens=1)

    monkeypatch.setattr(prompt_service, "generate_semantic_prompts", fake_batch)

    first = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name="missing-skill-a",
    )
    second = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name="missing-skill-b",
    )

    assert calls == ["missing-skill-a", "missing-skill-b"]
    assert first[0].id == second[0].id
    assert second[0].skill_name == "missing-skill-b"
    assert second[0].character_id is None
    assert second[0].version == 2


def test_generating_prompts_twice_reuses_prompts_and_placeholders(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.models import WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: _successful_prompt_batch(kwargs["candidates"], prompt="提示词：稳定输出"),
    )
    client, session_factory = api_client

    first = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)
    second = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)

    assert first.status_code == 201
    assert second.status_code == 201
    first_items = first.json()["items"]
    second_items = second.json()["items"]
    assert [prompt["id"] for prompt in second_items] == [prompt["id"] for prompt in first_items]
    html_body = client.get(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}", headers=auth_headers).json()["html_body"]
    assert all(html_body.count(f"{{{{image:prompt-{prompt['id']}}}}}") == 1 for prompt in second_items)
    session = session_factory()
    try:
        assert session.query(WechatMpImagePrompt).filter_by(article_id=created_wechat_article.id).count() == len(first_items)
    finally:
        session.close()


def test_regenerating_embedded_prompt_restores_marker_for_next_image(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.models import WechatMpAsset
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service
    from backend.app.services import wechat_mp_image_service as image_service

    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: _successful_prompt_batch(kwargs["candidates"], prompt="第一版提示词"),
    )
    generated_urls = iter(("/api/files/media/wechat-mp-first.png", "/api/files/media/wechat-mp-second.png"))
    monkeypatch.setattr(
        image_service,
        "_call_image_model",
        lambda **kwargs: (lambda url: {"file_path": url, "public_url": url, "provider_response": {"ok": True}})(next(generated_urls)),
    )
    client, session_factory = api_client
    created = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)
    assert created.status_code == 201
    prompt_id = created.json()["items"][0]["id"]

    first_image = client.post(
        f"/api/platforms/wechat-mp/prompts/{prompt_id}/image",
        json={"image_model": "doubao-seedream-4-0-250828"},
        headers=auth_headers,
    )
    assert first_image.status_code == 201
    marker = f"{{{{image:prompt-{prompt_id}}}}}"
    assert marker not in client.get(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}", headers=auth_headers).json()["html_body"]

    monkeypatch.setattr(
        prompt_service,
        "_call_prompt_model",
        lambda **kwargs: {"prompt": "第二版提示词", "input_tokens": 12, "output_tokens": 24, "model_name": kwargs["model_name"]},
    )
    regenerated = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts/{prompt_id}/regenerate",
        headers=auth_headers,
    )
    assert regenerated.status_code == 200
    assert client.get(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}", headers=auth_headers).json()["html_body"].count(marker) == 1

    second_image = client.post(
        f"/api/platforms/wechat-mp/prompts/{prompt_id}/image",
        json={"image_model": "doubao-seedream-4-0-250828"},
        headers=auth_headers,
    )
    assert second_image.status_code == 201
    html_body = client.get(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}", headers=auth_headers).json()["html_body"]
    assert "/api/files/media/wechat-mp-first.png" not in html_body
    assert "/api/files/media/wechat-mp-second.png" in html_body
    session = session_factory()
    try:
        assert session.query(WechatMpAsset).filter_by(prompt_id=prompt_id).count() == 2
    finally:
        session.close()


def test_generate_prompts_rolls_back_when_the_semantic_batch_fails(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.models import UsageRecord, WechatMpArticle, WechatMpArticleSection, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    from backend.app.services.wechat_mp_prompt_batch_service import BatchPromptResult

    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: BatchPromptResult((), 0, 0, "qwen3.7-max", 1, "provider_failed"),
    )
    client, session_factory = api_client
    session = session_factory()
    try:
        article = session.get(WechatMpArticle, created_wechat_article.id)
        article.markdown_body = "核心问题是计划入口太多，解决方法是先做最小动作并根据结果选择下一步。"
        session.commit()
    finally:
        session.close()
    response = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)

    assert response.status_code == 502
    session = session_factory()
    try:
        assert session.query(WechatMpArticleSection).filter_by(article_id=created_wechat_article.id).count() == 0
        assert session.query(WechatMpImagePrompt).filter_by(article_id=created_wechat_article.id).count() == 0
        assert session.query(UsageRecord).filter_by(resource_id=created_wechat_article.id).count() == 0
    finally:
        session.close()


def test_generate_prompts_returns_empty_for_semantic_candidates_without_user_model_config(
    api_client, auth_headers, created_wechat_article, monkeypatch,
):
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service
    from backend.app.services.wechat_mp_prompt_batch_service import BatchPromptResult

    monkeypatch.setenv("WECHAT_MP_PROMPT_BASE_URL", "https://prompt.example")
    monkeypatch.setenv("WECHAT_MP_PROMPT_API_KEY", "test-key")
    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: BatchPromptResult((), 0, 0, None, 0, "no_config"),
    )
    client, _ = api_client

    response = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)

    assert response.status_code == 201
    assert response.json()["items"] == []
    assert response.json()["analysis"]["model_calls"] == 0


def test_edit_and_regenerate_prompt_increment_version(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: _successful_prompt_batch(kwargs["candidates"], prompt="第一版提示词"),
    )
    client, _ = api_client
    created = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)
    prompt_id = created.json()["items"][0]["id"]
    marker = f"{{{{image:prompt-{prompt_id}}}}}"
    assert client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}", headers=auth_headers
    ).json()["html_body"].count(marker) == 1

    edited = client.patch(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts/{prompt_id}",
        json={"editable_prompt": "编辑后的提示词"},
        headers=auth_headers,
    )
    assert edited.status_code == 200
    assert edited.json()["editable_prompt"] == "主角：@小猫生图\n具体画面：编辑后的提示词"
    assert edited.json()["version"] == 2

    monkeypatch.setattr(
        prompt_service,
        "_call_prompt_model",
        lambda **kwargs: {"prompt": "再生成的提示词", "input_tokens": 15, "output_tokens": 30, "model_name": kwargs["model_name"]},
    )
    regenerated = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts/{prompt_id}/regenerate",
        headers=auth_headers,
    )
    assert regenerated.status_code == 200
    assert regenerated.json()["prompt"] == "主角：@小猫生图\n具体画面：再生成的提示词"
    assert regenerated.json()["editable_prompt"] == "主角：@小猫生图\n具体画面：再生成的提示词"
    assert regenerated.json()["version"] == 3
    assert client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}", headers=auth_headers
    ).json()["html_body"].count(marker) == 1


def test_prompt_endpoints_hide_foreign_article_and_prompt(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: _successful_prompt_batch(kwargs["candidates"], prompt="提示词", input_tokens=1, output_tokens=1),
    )
    client, _ = api_client
    created = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)
    prompt_id = created.json()["items"][0]["id"]
    other = client.post("/api/auth/register", json={"username": "wechat-prompt-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    assert client.get(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=other_headers).status_code == 404
    assert client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=other_headers).status_code == 404
    assert client.patch(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts/{prompt_id}",
        json={"editable_prompt": "越权"},
        headers=other_headers,
    ).status_code == 404
    assert client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts/{prompt_id}/regenerate",
        headers=other_headers,
    ).status_code == 404


def test_wechat_mp_layout_renderer_supports_article_blocks():
    from backend.app.services.wechat_mp_layout_service import render_wechat_html

    html = render_wechat_html(
        "# 标题\n## 小节\n> 引文\n- 无序项\n1. 有序项\n\n{{image:cover}}",
        [{"placeholder": "{{image:cover}}", "url": "https://example.com/cover.png", "alt": "封面"}],
    )

    assert "<h1>标题</h1>" in html
    assert "<h2>小节</h2>" in html
    assert "<blockquote" in html
    assert "<ul " in html
    assert "<ol " in html
    assert 'src="https://example.com/cover.png"' in html


def test_wechat_mp_layout_renderer_turns_details_into_answer_card():
    from backend.app.services.wechat_mp_layout_service import render_wechat_html

    html = render_wechat_html(
        "### 题目 1\nA. 支持型\n\n<details>\n<summary>💡 点击查看答案与解析</summary>\n\n**答案：A**\n\n**解析：** PMO 类型说明\n\n</details>\n---",
        [],
    )

    assert "&lt;details&gt;" not in html
    assert "&lt;summary&gt;" not in html
    assert "</details>" not in html
    assert "点击查看答案与解析" in html
    assert "答案：A" in html
    assert "<strong>答案：A</strong>" in html
    assert "border-left:4px solid #008575" in html
    assert "<hr" in html


def test_wechat_mp_layout_renderer_removes_markdown_syntax_in_headings_lists_and_tables():
    from backend.app.services.wechat_mp_layout_service import render_wechat_html

    html = render_wechat_html(
        "### 1.10 软件测试\n"
        "- **静态测试**：文档检查、代码走查\n"
        "- **动态测试-白盒**：单元测试\n\n"
        "| 类型 | 说明 |\n"
        "|-----|-----|\n"
        "| **静态测试** | 文档检查、代码走查 |\n"
        "---",
        [],
    )

    assert "<h3>1.10 软件测试</h3>" in html
    assert "<strong>静态测试</strong>" in html
    assert "<strong>动态测试-白盒</strong>" in html
    assert "<table" in html
    assert "|-----|-----|" not in html
    assert "### 1.10 软件测试" not in html
    assert "**" not in html
    assert "<hr" in html


def test_wechat_mp_layout_renderer_supports_tables_with_blank_lines_between_rows():
    from backend.app.services.wechat_mp_layout_service import render_wechat_html

    html = render_wechat_html(
        "| 风格 | 包含类型 |\n\n"
        "|------|----------|\n\n"
        "| **数据流风格** | 批处理序列、管道/过滤器 |\n\n"
        "| **调用/返回风格** | 主程序/子程序、数据抽象和面向对象、层次结构 |\n\n"
        "| **独立构件风格** | 进程通讯、事件驱动系统 |\n\n"
        "| **虚拟机风格** | 解释器、基于规则的系统 |\n\n"
        "| **仓库风格** | 数据库系统、黑板系统、超文本系统 |",
        [],
    )

    assert "<table" in html
    assert html.count("<tr>") == 6
    assert "<strong>数据流风格</strong>" in html
    assert "批处理序列、管道/过滤器" in html
    assert "|------|----------|" not in html
    assert "| **仓库风格** |" not in html


def test_wechat_mp_layout_renderer_supports_wrapped_markdown_tables_from_model_output():
    from backend.app.services.wechat_mp_layout_service import render_wechat_html

    html = render_wechat_html(
        "【这是考试中**必考**的知识点，要求能**区分具体类型属于哪种风格**。\n\n"
        "| 风格 | 包含类型 |\n\n"
        "|------|----------|\n\n"
        "| **数据流风格** | 批处理序列、管道/过滤器 |\n\n"
        "| **调用/返回风格** | 主程序/子程序、数据抽象和面向对象、层次结构 |\n\n"
        "| **独立构件风格** | 进程通讯、事件驱动系统 |\n\n"
        "| **虚拟机风格** | 解释器、基于规则的系统 |\n\n"
        "| **仓库风格** | 数据库系统、黑板系统、超文本系统 |】",
        [],
    )

    assert "<table" in html
    assert "<strong>必考</strong>" in html
    assert "<strong>仓库风格</strong>" in html
    assert "数据库系统、黑板系统、超文本系统" in html
    assert "|------|----------|" not in html
    assert "**仓库风格**" not in html
    assert "【" not in html
    assert "】" not in html


def test_wechat_mp_layout_style_upgrades_saved_markdown_table_paragraphs():
    from backend.app.services.wechat_mp_layout_service import apply_wechat_layout_style

    stale_html = (
        '<p style="margin:16px 0;">这是考试中<strong>必考</strong>的知识点，要求能<strong>区分具体类型属于哪种风格</strong>。</p>'
        '<p style="margin:16px 0;">| 风格 | 包含类型 |</p>'
        '<p style="margin:16px 0;">|------|----------|</p>'
        '<p style="margin:16px 0;">| **数据流风格** | 批处理序列、管道/过滤器 |</p>'
        '<p style="margin:16px 0;">| **调用/返回风格** | 主程序/子程序、数据抽象和面向对象、层次结构 |</p>'
        '<p style="margin:16px 0;">| **独立构件风格** | 进程通讯、事件驱动系统 |</p>'
        '<p style="margin:16px 0;">| **虚拟机风格** | 解释器、基于规则的系统 |</p>'
        '<p style="margin:16px 0;">| **仓库风格** | 数据库系统、黑板系统、超文本系统 |</p>'
    )

    html = apply_wechat_layout_style(stale_html)

    assert "<table" in html
    assert "<strong>仓库风格</strong>" in html
    assert "数据库系统、黑板系统、超文本系统" in html
    assert "|------|----------|" not in html
    assert "**仓库风格**" not in html


def test_wechat_mp_layout_style_upgrades_saved_br_joined_markdown_tables():
    from backend.app.services.wechat_mp_layout_service import apply_wechat_layout_style

    stale_html = (
        '<p style="margin:16px 0;">| 风格 | 包含类型 |<br />'
        '|------|----------|<br />'
        '| <strong>数据流风格</strong> | 批处理序列、管道/过滤器 |<br />'
        '| **调用/返回风格** | 主程序/子程序、数据抽象和面向对象、层次结构 |</p>'
    )

    html = apply_wechat_layout_style(stale_html)

    assert "<table" in html
    assert "<strong>数据流风格</strong>" in html
    assert "<strong>调用/返回风格</strong>" in html
    assert "主程序/子程序、数据抽象和面向对象、层次结构" in html
    assert "|------|----------|" not in html
    assert "| 风格 |" not in html


def test_wechat_mp_layout_style_upgrades_saved_collapsed_markdown_tables():
    from backend.app.services.wechat_mp_layout_service import apply_wechat_layout_style

    stale_html = (
        '<p style="margin:10px 0;line-height:1.8;color:#25322f;">'
        '| 风格 | 包含类型 | |------|----------| '
        '| <strong>数据流风格</strong> | 批处理序列、管道/过滤器 | '
        '| <strong>调用/返回风格</strong> | 主程序/子程序、数据抽象和面向对象、层次结构 |'
        '</p>'
    )

    html = apply_wechat_layout_style(stale_html)

    assert "<table" in html
    assert "<strong>数据流风格</strong>" in html
    assert "<strong>调用/返回风格</strong>" in html
    assert "批处理序列、管道/过滤器" in html
    assert "|------|----------|" not in html
    assert "| 风格 |" not in html


def test_wechat_mp_layout_style_upgrades_saved_markdown_paragraph_leftovers():
    from backend.app.services.wechat_mp_layout_service import apply_wechat_layout_style

    stale_html = (
        '<p style="margin:16px 0;">**UML关系强弱排序**（必须牢记）：</p>'
        '<p style="margin:16px 0;">```</p>'
        '<p style="margin:16px 0;">泛化 = 实现 &gt; 组合 &gt; 聚合 &gt; 关联 &gt; 依赖</p>'
        '<p style="margin:16px 0;">```</p>'
        '<p style="margin:16px 0;">💡 🧠 **速记口诀**：泛化&gt;实现&gt;组合&gt;聚合&gt;关联&gt;依赖</p>'
        '<p style="margin:16px 0;">**UML五种视图**：</p>'
    )

    html = apply_wechat_layout_style(stale_html)

    assert "<strong>UML关系强弱排序</strong>" in html
    assert "<strong>速记口诀</strong>" in html
    assert "<strong>UML五种视图</strong>" in html
    assert "<pre" in html
    assert "泛化 = 实现 &gt; 组合 &gt; 聚合 &gt; 关联 &gt; 依赖" in html
    assert "```" not in html
    assert "**" not in html


def test_get_wechat_mp_article_repairs_saved_markdown_table_html(
    api_client, auth_headers, created_wechat_article, created_wechat_account
):
    from backend.app.models import WechatMpArticle, WechatMpDraftSync

    client, session_factory = api_client
    session = session_factory()
    try:
        article = session.get(WechatMpArticle, created_wechat_article.id)
        article.html_body = (
            '<p>| 风格 | 包含类型 |</p>'
            '<p>|------|----------|</p>'
            '<p>| **数据流风格** | 批处理序列、管道/过滤器 |</p>'
        )
        article.status = "synced_to_wechat"
        sync = WechatMpDraftSync(
            user_id=article.user_id,
            account_id=created_wechat_account.id,
            article_id=article.id,
            article_revision=article.revision,
            wechat_media_id="old-draft",
            status="synced",
        )
        session.add(sync)
        session.commit()
        original_revision = article.revision
    finally:
        session.close()

    response = client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert "<table" in response.json()["html_body"]
    assert "|------|----------|" not in response.json()["html_body"]
    assert response.json()["revision"] == original_revision + 1
    assert response.json()["status"] == "layout_ready"
    session = session_factory()
    try:
        article = session.get(WechatMpArticle, created_wechat_article.id)
        assert "<table" in article.html_body
        assert session.query(WechatMpDraftSync).filter_by(article_id=article.id).one().status == "stale"
    finally:
        session.close()


def test_wechat_mp_layout_renderer_supports_common_markdown_formatting():
    from backend.app.services.wechat_mp_layout_service import render_wechat_html

    html = render_wechat_html(
        "## 核心总结\n"
        "第一行说明\n"
        "第二行包含 [参考链接](https://example.com/doc) 和 `status_code`\n\n"
        "> 第一句引用\n"
        "> 第二句引用\n\n"
        "```python\n"
        "print('hello')\n"
        "```\n\n"
        "- *斜体重点*、~~过时说法~~、**最终结论**",
        [],
    )

    assert "<h2>核心总结</h2>" in html
    assert "第一行说明<br />第二行包含" in html
    assert '<a href="https://example.com/doc"' in html
    assert "<code" in html
    assert "status_code" in html
    assert "第一句引用<br />第二句引用" in html
    assert "<pre" in html
    assert "print(&#x27;hello&#x27;)" in html
    assert "<em>斜体重点</em>" in html
    assert "<del>过时说法</del>" in html
    assert "<strong>最终结论</strong>" in html
    assert "```" not in html


def test_wechat_mp_layout_style_upgrades_previously_escaped_details():
    from backend.app.services.wechat_mp_layout_service import apply_wechat_layout_style

    html = (
        '<p style="margin:16px 0;">&lt;details&gt;</p>'
        '<p style="margin:16px 0;">&lt;summary&gt;💡 点击查看答案与解析&lt;/summary&gt;</p>'
        '<p style="margin:16px 0;">**答案：A**</p>'
        '<p style="margin:16px 0;">&lt;/details&gt;</p>'
    )
    styled = apply_wechat_layout_style(html, "classic")

    assert "&lt;details&gt;" not in styled
    assert "点击查看答案与解析" in styled
    assert "<strong>答案：A</strong>" in styled
    assert "border-left:4px solid #008575" in styled


def test_wechat_mp_layout_style_cleans_existing_markdown_leftovers():
    from backend.app.services.wechat_mp_layout_service import apply_wechat_layout_style

    html = (
        '<p style="margin:16px 0;">### 1.10 软件测试</p>'
        '<blockquote style="margin:16px 0;">📚 **软考高级·信息系统项目管理师**</blockquote>'
        '<ul style="padding-left:1.5em;margin:16px 0;">'
        '<li style="margin:8px 0;">**静态测试**：文档检查、代码走查</li>'
        '</ul>'
        '<p style="margin:16px 0;">---</p>'
    )
    styled = apply_wechat_layout_style(html, "study_green")

    assert "### 1.10 软件测试" not in styled
    assert "<strong>软考高级·信息系统项目管理师</strong>" in styled
    assert "<strong>静态测试</strong>" in styled
    assert "**" not in styled
    assert "<hr" in styled


def test_wechat_mp_layout_styles_create_polished_publish_html():
    from backend.app.services.wechat_mp_layout_service import apply_wechat_layout_style, get_wechat_layout_styles, render_wechat_html

    html = render_wechat_html(
        "## 01 信息系统管理\n正文说明\n> 口诀：规划运优\n\n| 阶段 | 常见考法 |\n| --- | --- |\n| 规划 | 问先做什么 |\n\n{{image:inline}}",
        [{"placeholder": "{{image:inline}}", "url": "/api/files/media/inline.png", "alt": "配图"}],
    )
    styled = apply_wechat_layout_style(html, "study_green", hero_image_url="/api/files/media/cover.png")

    assert any(item["id"] == "study_green" for item in get_wechat_layout_styles())
    assert "章节复习" in styled
    assert "max-width:677px" in styled
    assert "border-radius:18px" in styled
    assert 'src="/api/files/media/cover.png"' in styled
    assert "<table" in styled
    assert "background:#e5f4ef" in styled


def test_wechat_mp_publish_page_supports_layout_style_preview():
    from pathlib import Path

    page_source = Path("frontend/src/pages/platforms/wechat-mp/publish-page.tsx").read_text()
    api_source = Path("frontend/src/lib/api.ts").read_text()

    assert "fetchWechatMpLayoutStyles" in page_source
    assert "fetchWechatMpLayoutPreview" in page_source
    assert "refreshLayoutPreview" in page_source
    assert "previewKey" in page_source
    assert "canSyncDraft" in page_source
    assert "请先预览并确认排版布局" in page_source
    assert "排版风格" in page_source
    assert "发布前预览" in page_source
    assert "重新生成排版预览" in page_source
    assert "dangerouslySetInnerHTML" in page_source
    assert "extractMissingPromptIds" in page_source
    assert "回写作页补图" in page_source
    assert "&prompt=${missingPromptIds[0]}" in page_source
    assert "fetchLatestWechatMpDraftSync" in api_source
    assert "fetchLatestWechatMpDraftSync" in page_source
    assert "setSync(latestSync)" in page_source
    assert "canPublish" in page_source
    assert "layout_style" in api_source


def test_wechat_mp_articles_are_owner_scoped_and_patch_renders_markdown(api_client, auth_headers):
    client, session_factory = api_client
    from backend.app.models import User, WechatMpArticle

    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="初稿",
            markdown_body="初稿正文",
            html_body="<p>初稿正文</p>",
            digest="摘要",
            cover_brief="封面说明",
            status="layout_ready",
            illustration_skill="xiaomao-illustrations",
        )
        session.add(article)
        session.commit()
        article_id = article.id
    finally:
        session.close()

    assert client.get("/api/platforms/wechat-mp/articles", headers=auth_headers).json()[0]["id"] == article_id
    assert client.get(f"/api/platforms/wechat-mp/articles/{article_id}", headers=auth_headers).status_code == 200
    update = client.patch(
        f"/api/platforms/wechat-mp/articles/{article_id}",
        json={"title": "更新标题", "markdown_body": "## 更新\n更新正文", "illustration_skill": "custom-skill"},
        headers=auth_headers,
    )
    assert update.status_code == 200
    assert update.json()["title"] == "更新标题"
    assert "<h2>更新</h2>" in update.json()["html_body"]
    assert update.json()["illustration_skill"] == "custom-skill"

    other = client.post("/api/auth/register", json={"username": "wechat-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.get("/api/platforms/wechat-mp/articles", headers=other_headers).json() == []
    assert client.get(f"/api/platforms/wechat-mp/articles/{article_id}", headers=other_headers).status_code == 404
    assert client.patch(f"/api/platforms/wechat-mp/articles/{article_id}", json={"title": "越权"}, headers=other_headers).status_code == 404


def test_wechat_writer_refreshes_article_after_saving_markdown():
    source = open("frontend/src/pages/platforms/wechat-mp/writer-page.tsx", encoding="utf-8").read()

    save_start = source.index("async function saveArticle()")
    save_end = source.index("async function makePrompts()", save_start)
    save_source = source[save_start:save_end]
    assert "await fetchWechatMpArticle(article.id)" in save_source
    assert "setArticle(refreshed)" in save_source


def test_noop_article_save_preserves_embedded_images_and_revision(
    api_client, auth_headers, created_wechat_prompt
):
    from backend.app.models import WechatMpArticle, WechatMpImagePrompt

    client, session_factory = api_client
    session = session_factory()
    try:
        article = session.get(WechatMpArticle, created_wechat_prompt.article_id)
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        article.html_body = (
            f'<p>正文</p><img src="/api/files/media/embedded.png" alt="配图" />'
        )
        prompt.status = "generated"
        article.status = "images_ready"
        session.commit()
        original_html = article.html_body
        original_revision = article.revision
        markdown_body = article.markdown_body
        title = article.title
    finally:
        session.close()

    response = client.patch(
        f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}",
        json={"title": title, "markdown_body": markdown_body},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["html_body"] == original_html
    assert response.json()["revision"] == original_revision
    assert response.json()["status"] == "images_ready"


def test_body_edit_resets_inline_state_and_stales_synced_draft(
    api_client, auth_headers, created_wechat_prompt, created_wechat_account
):
    from backend.app.models import (
        WechatMpArticle,
        WechatMpArticleSection,
        WechatMpAsset,
        WechatMpDraftSync,
        WechatMpImagePrompt,
    )

    client, session_factory = api_client
    session = session_factory()
    try:
        article = session.get(WechatMpArticle, created_wechat_prompt.article_id)
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        asset = WechatMpAsset(
            user_id=article.user_id,
            article_id=article.id,
            prompt_id=prompt.id,
            role="inline_illustration",
            file_path="/tmp/old-inline.png",
            public_url="/api/files/media/old-inline.png",
            prompt=prompt.editable_prompt,
            skill_name=prompt.skill_name,
            model_name="test-model",
        )
        article.html_body = '<p>旧正文</p><img src="/api/files/media/old-inline.png" alt="旧图" />'
        article.status = "images_ready"
        prompt.status = "generated"
        sync = WechatMpDraftSync(
            user_id=article.user_id,
            account_id=created_wechat_account.id,
            article_id=article.id,
            article_revision=article.revision,
            wechat_media_id="old-synced-draft",
            status="synced",
        )
        session.add_all([asset, sync])
        session.commit()
        original_revision = article.revision
        asset_id = asset.id
    finally:
        session.close()

    response = client.patch(
        f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}",
        json={"markdown_body": "## 新正文\n内容已重写"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["revision"] == original_revision + 1
    assert response.json()["status"] == "layout_ready"
    assert "old-inline.png" not in response.json()["html_body"]
    assert "{{image:" not in response.json()["html_body"]
    session = session_factory()
    try:
        retained_prompt = session.query(WechatMpImagePrompt).filter_by(article_id=created_wechat_prompt.article_id).one()
        assert retained_prompt.status == "stale"
        assert session.query(WechatMpArticleSection).filter_by(article_id=created_wechat_prompt.article_id).count() == 1
        assert session.get(WechatMpAsset, asset_id).prompt_id is None
        assert session.query(WechatMpDraftSync).filter_by(article_id=created_wechat_prompt.article_id).one().status == "stale"
    finally:
        session.close()


def test_wechat_mp_article_writer_value_error_maps_to_502(api_client, auth_headers, monkeypatch):
    from backend.app.services import wechat_mp_writer_service as writer

    def malformed_response(**kwargs):
        raise ValueError("invalid JSON")

    monkeypatch.setattr(writer, "_call_writer_model", malformed_response)
    client, _ = api_client
    response = client.post(
        "/api/platforms/wechat-mp/articles",
        json={"title": "稳定输出", "topic": "稳定输出"},
        headers=auth_headers,
    )

    assert response.status_code == 502


def test_wechat_mp_crypto_round_trip_and_rejects_empty_secret():
    from backend.app.services.wechat_mp_crypto_service import decrypt_secret, encrypt_secret

    encrypted = encrypt_secret("secret-value")

    assert encrypted != "secret-value"
    assert decrypt_secret(encrypted) == "secret-value"
    with pytest.raises(ValueError, match="app_secret is required"):
        encrypt_secret("")


def test_wechat_mp_adapter_requests_access_token(monkeypatch):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiAdapter

    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"access_token": "token-value", "expires_in": 7200}

    def fake_get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse()

    monkeypatch.setattr("requests.get", fake_get)

    payload = WechatMpApiAdapter().get_access_token(app_id="wx123", app_secret="secret-value")

    assert payload == {"access_token": "token-value", "expires_in": 7200}
    assert calls == [
        (
            "https://api.weixin.qq.com/cgi-bin/token",
            {"grant_type": "client_credential", "appid": "wx123", "secret": "secret-value"},
            20,
        )
    ]


def test_wechat_mp_adapter_raises_for_wechat_error(monkeypatch):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiAdapter, WechatMpApiError

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"errcode": 40013, "errmsg": "invalid appid"}

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(WechatMpApiError) as error:
        WechatMpApiAdapter().get_access_token(app_id="wx123", app_secret="secret-value")

    assert error.value.errcode == 40013
    assert error.value.payload["errmsg"] == "invalid appid"


def test_wechat_mp_adapter_raises_for_http_status_error(monkeypatch):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiAdapter, WechatMpApiError

    class FakeResponse:
        status_code = 503

        def json(self):
            return {"errmsg": "service unavailable"}

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(WechatMpApiError) as error:
        WechatMpApiAdapter().get_access_token(app_id="wx123", app_secret="secret-value")

    assert error.value.payload == {"errmsg": "service unavailable"}


def test_wechat_mp_publish_status_includes_submitted():
    from typing import get_args
    from backend.app.schemas.wechat_mp import WechatMpPublishStatus

    assert "submitted" in get_args(WechatMpPublishStatus)


def test_xiaomao_prompt_contract_keeps_rendering_instructions_out_of_image_text():
    from backend.app.services.wechat_mp_image_prompt_service import build_skill_prompt

    prompt = build_skill_prompt("xiaomao-illustrations", "稳定输出", "先做最小动作")
    assert "主角引用：@小猫生图" in prompt
    for excluded in ("白色背景", "手绘", "慵懒", "玳瑁猫", "不得渲染"):
        assert excluded not in prompt
    assert "只描述具体画面" in prompt
    assert "16:9" not in prompt
    assert "横版构图" not in prompt
    assert "15-25%" not in prompt

    fallback_prompt = build_skill_prompt("missing-character", "稳定输出", "先做最小动作")
    assert "16:9" not in fallback_prompt


def test_none_skill_rejects_image_generation(api_client, auth_headers, created_wechat_prompt):
    from backend.app.models import WechatMpArticle, WechatMpImagePrompt

    client, session_factory = api_client
    session = session_factory()
    try:
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        article = session.get(WechatMpArticle, created_wechat_prompt.article_id)
        prompt.skill_name = "none"
        article.illustration_skill = "none"
        session.commit()
    finally:
        session.close()

    response = client.post(
        f"/api/platforms/wechat-mp/prompts/{created_wechat_prompt.id}/image",
        json={"size": "16:9"}, headers=auth_headers,
    )
    assert response.status_code == 400
    assert "none" in str(response.json()["detail"]).lower()


def test_wechat_mp_writer_uses_configured_default_text_model(api_client, auth_headers, monkeypatch):
    from backend.app.core.security import encrypt_text
    from backend.app.models import ModelConfig, User
    from backend.app.services import wechat_mp_writer_service as writer_service

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        session.add(ModelConfig(
            user_id=owner.id, name="公众号默认文本模型", model_type="text",
            provider="openai-compatible", model_name="configured-writer",
            base_url="https://models.example/v1", encrypted_api_key=encrypt_text("configured-key"),
            is_default=True,
        ))
        session.commit()
    finally:
        session.close()

    captured = {}
    def fake_writer_call(**kwargs):
        captured.update(kwargs)
        return {
            "title": "配置模型文章", "markdown_body": "正文", "digest": "摘要", "cover_brief": "封面",
            "input_tokens": 10, "output_tokens": 20, "model_name": kwargs["model_name"],
        }

    monkeypatch.setattr(writer_service, "_call_writer_model", fake_writer_call)
    response = client.post(
        "/api/platforms/wechat-mp/articles",
        json={"title": "配置模型文章", "topic": "配置模型"}, headers=auth_headers,
    )
    assert response.status_code == 201
    assert captured["model_name"] == "configured-writer"
    assert captured["base_url"] == "https://models.example/v1"
    assert captured["api_key"] == "configured-key"
    assert response.json()["cost_estimate"]["total_yuan"] != ""


def test_article_edit_invalidates_synced_revision_and_blocks_publish(api_client, auth_headers, synced_wechat_article, monkeypatch):
    from backend.app.models import WechatMpDraftSync
    from backend.app.services import wechat_mp_publish_service as publish_service

    class NeverCalledAdapter:
        def submit_publish(self, **kwargs):
            raise AssertionError("stale drafts must not be published")

    monkeypatch.setattr(publish_service, "WechatMpApiAdapter", lambda: NeverCalledAdapter())
    client, session_factory = api_client
    updated = client.patch(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}",
        json={"markdown_body": "## 新正文\n内容已变化"}, headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["status"] == "layout_ready"
    publish = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True}, headers=auth_headers,
    )
    assert publish.status_code == 400
    session = session_factory()
    try:
        sync = session.query(WechatMpDraftSync).filter_by(article_id=synced_wechat_article.id).one()
        assert sync.status == "stale"
        assert sync.article_revision == 1
    finally:
        session.close()


def test_prompt_generation_invalidates_synced_article_revision(api_client, auth_headers, synced_wechat_article, monkeypatch):
    from backend.app.models import WechatMpDraftSync
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: _successful_prompt_batch(kwargs["candidates"], prompt="小猫处理新结构"),
    )
    client, session_factory = api_client
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/prompts",
        headers=auth_headers,
    )
    assert response.status_code == 201
    article = client.get(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}", headers=auth_headers,
    ).json()
    assert article["revision"] == 2
    session = session_factory()
    try:
        assert session.query(WechatMpDraftSync).filter_by(article_id=synced_wechat_article.id).one().status == "stale"
    finally:
        session.close()


def test_failed_draft_sync_is_journaled(api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
    from backend.app.models import WechatMpDraftSync
    from backend.app.services import wechat_mp_draft_service as draft_service

    class FailingAdapter:
        def upload_permanent_image(self, **kwargs): return {"media_id": "thumb"}
        def upload_content_image(self, **kwargs): return {"url": "https://mmbiz.qpic.cn/content.png"}
        def add_draft(self, **kwargs):
            raise WechatMpApiError("draft failed", errcode=40001, payload={"errcode": 40001, "errmsg": "invalid"})

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: FailingAdapter())
    client, session_factory = api_client
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": created_wechat_account.id}, headers=auth_headers,
    )
    assert response.status_code == 502
    session = session_factory()
    try:
        record = session.query(WechatMpDraftSync).filter_by(article_id=created_wechat_article_with_image.id).one()
        assert record.status == "failed"
        assert record.active_key is None
        assert record.raw_response["errcode"] == 40001
        assert record.error_message
    finally:
        session.close()


@pytest.mark.parametrize("outcome", ["timeout", "malformed"])
def test_ambiguous_draft_add_keeps_guard_and_prevents_duplicate_retry(
    api_client, auth_headers, created_wechat_article_with_image, created_wechat_account,
    monkeypatch, outcome,
):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
    from backend.app.models import WechatMpDraftSync
    from backend.app.services import wechat_mp_draft_service as draft_service

    calls = []

    class AmbiguousAdapter:
        def upload_permanent_image(self, **kwargs):
            return {"media_id": "thumb"}

        def upload_content_image(self, **kwargs):
            return {"url": "https://mmbiz.qpic.cn/content.png"}

        def add_draft(self, **kwargs):
            calls.append(kwargs)
            if outcome == "timeout":
                raise WechatMpApiError("wechat draft add timed out")
            return {}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: AmbiguousAdapter())
    client, session_factory = api_client
    url = f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft"
    payload = {"account_id": created_wechat_account.id}

    first = client.post(url, json=payload, headers=auth_headers)
    repeated = client.post(url, json=payload, headers=auth_headers)

    assert first.status_code == 502
    assert repeated.status_code == 400
    assert len(calls) == 1
    session = session_factory()
    try:
        record = session.query(WechatMpDraftSync).filter_by(
            article_id=created_wechat_article_with_image.id,
        ).one()
        assert record.status == "pending"
        assert record.active_key == (
            f"account:{created_wechat_account.id}:article:"
            f"{created_wechat_article_with_image.id}:revision:{record.article_revision}"
        )
    finally:
        session.close()


def test_pre_draft_upload_failure_releases_guard_and_allows_retry(
    api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch
):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
    from backend.app.models import WechatMpDraftSync
    from backend.app.services import wechat_mp_draft_service as draft_service

    upload_attempts = 0
    draft_calls = []

    class RetryableAdapter:
        def upload_permanent_image(self, **kwargs):
            nonlocal upload_attempts
            upload_attempts += 1
            if upload_attempts == 1:
                raise WechatMpApiError("cover upload timed out")
            return {"media_id": "thumb"}

        def upload_content_image(self, **kwargs):
            return {"url": "https://mmbiz.qpic.cn/content.png"}

        def add_draft(self, **kwargs):
            draft_calls.append(kwargs)
            return {"media_id": "retry-draft"}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: RetryableAdapter())
    client, session_factory = api_client
    url = f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft"
    payload = {"account_id": created_wechat_account.id}

    first = client.post(url, json=payload, headers=auth_headers)
    retried = client.post(url, json=payload, headers=auth_headers)

    assert first.status_code == 502
    assert retried.status_code == 201
    assert len(draft_calls) == 1
    session = session_factory()
    try:
        records = session.query(WechatMpDraftSync).order_by(WechatMpDraftSync.id).all()
        assert [record.status for record in records] == ["failed", "synced"]
        assert records[0].active_key is None
        assert records[1].active_key is None
    finally:
        session.close()


def test_failed_publish_submit_is_journaled(api_client, auth_headers, synced_wechat_article, monkeypatch):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
    from backend.app.models import WechatMpPublishJob
    from backend.app.services import wechat_mp_publish_service as publish_service

    class FailingAdapter:
        def submit_publish(self, **kwargs):
            raise WechatMpApiError("publish failed", errcode=40001, payload={"errcode": 40001, "errmsg": "invalid"})

    monkeypatch.setattr(publish_service, "WechatMpApiAdapter", lambda: FailingAdapter())
    client, session_factory = api_client
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True}, headers=auth_headers,
    )
    assert response.status_code == 502
    session = session_factory()
    try:
        record = session.query(WechatMpPublishJob).filter_by(article_id=synced_wechat_article.id).one()
        assert record.status == "failed"
        assert record.raw_response["errcode"] == 40001
        assert record.error_message
    finally:
        session.close()


def test_publish_timeout_keeps_active_guard_and_prevents_duplicate_retry(
    api_client, auth_headers, synced_wechat_article, monkeypatch
):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
    from backend.app.models import WechatMpPublishJob
    from backend.app.services import wechat_mp_publish_service as publish_service

    calls = []

    class TimeoutAdapter:
        def submit_publish(self, **kwargs):
            calls.append(kwargs)
            raise WechatMpApiError("wechat publish submit timed out")

    monkeypatch.setattr(publish_service, "WechatMpApiAdapter", lambda: TimeoutAdapter())
    client, session_factory = api_client
    url = f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish"

    first = client.post(url, json={"confirm": True}, headers=auth_headers)
    repeated = client.post(url, json={"confirm": True}, headers=auth_headers)

    assert first.status_code == 502
    assert repeated.status_code == 201
    assert len(calls) == 1
    session = session_factory()
    try:
        job = session.query(WechatMpPublishJob).filter_by(article_id=synced_wechat_article.id).one()
        assert repeated.json()["id"] == job.id
        assert job.status == "pending"
        assert job.active_key == (
            f"account:{job.account_id}:article:{job.article_id}:revision:1"
        )
        assert "timed out" in job.error_message
    finally:
        session.close()


def test_publish_timeout_guard_survives_resync_of_same_revision(
    api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch
):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
    from backend.app.services import wechat_mp_draft_service as draft_service
    from backend.app.services import wechat_mp_publish_service as publish_service

    draft_ids = iter(("draft-a", "draft-b"))

    class DraftAdapter:
        def upload_permanent_image(self, **kwargs):
            return {"media_id": "thumb"}

        def upload_content_image(self, **kwargs):
            return {"url": "https://mmbiz.qpic.cn/content.png"}

        def add_draft(self, **kwargs):
            return {"media_id": next(draft_ids)}

    submit_calls = []

    class PublishAdapter:
        def submit_publish(self, **kwargs):
            submit_calls.append(kwargs)
            raise WechatMpApiError("wechat publish submit timed out")

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: DraftAdapter())
    monkeypatch.setattr(publish_service, "WechatMpApiAdapter", lambda: PublishAdapter())
    client, session_factory = api_client
    sync_url = f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft"
    publish_url = f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/publish"

    first_sync = client.post(
        sync_url, json={"account_id": created_wechat_account.id}, headers=auth_headers,
    )
    first_publish = client.post(publish_url, json={"confirm": True}, headers=auth_headers)
    session = session_factory()
    try:
        from backend.app.models import WechatMpPublishJob
        guarded_job_id = session.query(WechatMpPublishJob.id).scalar()
    finally:
        session.close()
    second_sync = client.post(
        sync_url, json={"account_id": created_wechat_account.id}, headers=auth_headers,
    )
    second_publish = client.post(publish_url, json={"confirm": True}, headers=auth_headers)

    assert first_sync.status_code == 201
    assert first_publish.status_code == 502
    assert second_sync.status_code == 201
    assert second_sync.json()["id"] != first_sync.json()["id"]
    assert second_publish.status_code == 201
    assert second_publish.json()["id"] == guarded_job_id
    assert len(submit_calls) == 1


def test_resync_rebinds_scheduled_publish_to_current_draft(
    api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch
):
    from datetime import datetime

    from backend.app.models import WechatMpDraftSync, WechatMpPublishJob
    from backend.app.services import wechat_mp_draft_service as draft_service
    from backend.app.services import wechat_mp_publish_service as publish_service

    draft_ids = iter(("draft-a", "draft-b"))

    class DraftAdapter:
        def upload_permanent_image(self, **kwargs):
            return {"media_id": "thumb"}

        def upload_content_image(self, **kwargs):
            return {"url": "https://mmbiz.qpic.cn/content.png"}

        def add_draft(self, **kwargs):
            return {"media_id": next(draft_ids)}

    submit_calls = []

    class PublishAdapter:
        def submit_publish(self, **kwargs):
            submit_calls.append(kwargs)
            return {"publish_id": "scheduled-publish"}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: DraftAdapter())
    monkeypatch.setattr(publish_service, "_get_access_token", lambda account, adapter: "token")
    client, session_factory = api_client
    sync_url = f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft"
    publish_url = f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/publish"

    first_sync = client.post(sync_url, json={"account_id": created_wechat_account.id}, headers=auth_headers)
    scheduled = client.post(
        publish_url,
        json={"confirm": True, "scheduled_at": "2026-07-20T00:00:00"},
        headers=auth_headers,
    )
    second_sync = client.post(sync_url, json={"account_id": created_wechat_account.id}, headers=auth_headers)

    assert first_sync.status_code == scheduled.status_code == second_sync.status_code == 201
    session = session_factory()
    try:
        job = session.get(WechatMpPublishJob, scheduled.json()["id"])
        assert job.draft_sync_id == second_sync.json()["id"]
        assert session.get(WechatMpDraftSync, first_sync.json()["id"]).status == "stale"
        result = publish_service.run_due_publish_jobs(
            db=session, now=datetime(2026, 7, 21), adapter_factory=PublishAdapter,
        )
        assert result["executed_count"] == 1
        assert session.get(WechatMpPublishJob, job.id).status == "submitted"
    finally:
        session.close()
    assert submit_calls == [{"access_token": "token", "media_id": "draft-b"}]


def test_resync_does_not_rebind_pending_publish_job(
    api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch
):
    from backend.app.models import WechatMpPublishJob
    from backend.app.services import wechat_mp_draft_service as draft_service

    draft_ids = iter(("draft-a", "draft-b"))

    class DraftAdapter:
        def upload_permanent_image(self, **kwargs):
            return {"media_id": "thumb-media-id"}

        def upload_content_image(self, **kwargs):
            return {"url": "https://mmbiz.qpic.cn/content.png"}

        def add_draft(self, **kwargs):
            return {"media_id": next(draft_ids)}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: DraftAdapter())
    client, session_factory = api_client
    sync_url = f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft"
    publish_url = f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/publish"

    first_sync = client.post(sync_url, json={"account_id": created_wechat_account.id}, headers=auth_headers)
    scheduled = client.post(
        publish_url,
        json={"confirm": True, "scheduled_at": "2026-07-20T00:00:00"},
        headers=auth_headers,
    )
    assert first_sync.status_code == scheduled.status_code == 201

    session = session_factory()
    try:
        job = session.get(WechatMpPublishJob, scheduled.json()["id"])
        job.status = "pending"
        session.commit()
    finally:
        session.close()

    second_sync = client.post(sync_url, json={"account_id": created_wechat_account.id}, headers=auth_headers)
    assert second_sync.status_code == 201

    session = session_factory()
    try:
        job = session.get(WechatMpPublishJob, scheduled.json()["id"])
        assert job.status == "pending"
        assert job.draft_sync_id == first_sync.json()["id"]
    finally:
        session.close()


@pytest.mark.parametrize("token_outcome", ["timeout", "malformed"])
def test_publish_token_failure_is_definite_and_allows_retry(
    api_client, auth_headers, synced_wechat_article, monkeypatch, token_outcome
):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
    from backend.app.models import WechatMpAccount, WechatMpPublishJob
    from backend.app.services import wechat_mp_publish_service as publish_service

    client, session_factory = api_client
    session = session_factory()
    try:
        account = session.query(WechatMpAccount).one()
        account.token_cache = None
        session.commit()
    finally:
        session.close()

    token_attempts = 0
    submit_calls = []

    class TokenRetryAdapter:
        def get_access_token(self, **kwargs):
            nonlocal token_attempts
            token_attempts += 1
            if token_attempts == 1:
                if token_outcome == "timeout":
                    raise WechatMpApiError("wechat access_token request timed out")
                return {}
            return {"access_token": "retry-token", "expires_in": 7200}

        def submit_publish(self, **kwargs):
            submit_calls.append(kwargs)
            return {"publish_id": "retry-publish"}

    monkeypatch.setattr(publish_service, "WechatMpApiAdapter", lambda: TokenRetryAdapter())
    url = f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish"

    first = client.post(url, json={"confirm": True}, headers=auth_headers)
    retried = client.post(url, json={"confirm": True}, headers=auth_headers)

    assert first.status_code == 502
    assert retried.status_code == 201
    assert len(submit_calls) == 1
    session = session_factory()
    try:
        jobs = session.query(WechatMpPublishJob).order_by(WechatMpPublishJob.id).all()
        assert [job.status for job in jobs] == ["failed", "submitted"]
        assert jobs[0].active_key is None
    finally:
        session.close()


def test_due_publish_runner_executes_due_job(api_client, auth_headers, synced_wechat_article, monkeypatch):
    from datetime import datetime
    from backend.app.models import WechatMpPublishJob
    from backend.app.services import wechat_mp_publish_service as publish_service

    client, session_factory = api_client
    due = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True, "scheduled_at": "2026-07-20T00:00:00"}, headers=auth_headers,
    )
    assert due.status_code == 201
    calls = []

    class FakeAdapter:
        def submit_publish(self, **kwargs):
            calls.append(kwargs)
            return {"publish_id": "due-publish-id"}

    monkeypatch.setattr(publish_service, "_get_access_token", lambda account, adapter: "token")
    session = session_factory()
    try:
        result = publish_service.run_due_publish_jobs(
            db=session, now=datetime(2026, 7, 21), adapter_factory=FakeAdapter,
        )
        assert result["executed_count"] == 1
        assert session.get(WechatMpPublishJob, due.json()["id"]).status == "submitted"
    finally:
        session.close()
    assert len(calls) == 1


def test_scheduled_publish_can_be_cancelled(api_client, auth_headers, synced_wechat_article):
    client, _ = api_client
    scheduled = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True, "scheduled_at": "2030-01-02T03:04:05"}, headers=auth_headers,
    )
    cancelled = client.post(
        f"/api/platforms/wechat-mp/publish-jobs/{scheduled.json()['id']}/cancel", headers=auth_headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_cancelling_job_claimed_by_due_runner_does_not_clear_active_state(
    api_client, auth_headers, synced_wechat_article, monkeypatch
):
    from backend.app.models import WechatMpPublishJob
    from backend.app.services import wechat_mp_publish_service as publish_service

    client, session_factory = api_client
    scheduled = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True, "scheduled_at": "2030-01-02T03:04:05"}, headers=auth_headers,
    )
    assert scheduled.status_code == 201

    session = session_factory()
    try:
        job = session.get(WechatMpPublishJob, scheduled.json()["id"])
        assert job is not None
        active_key = job.active_key
        execute = session.execute

        def claim_before_cancel_update(statement, *args, **kwargs):
            if statement.is_update and statement.table.name == "wechat_mp_publish_jobs":
                job.status = "pending"
                session.flush()
            return execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", claim_before_cancel_update)
        with pytest.raises(
            publish_service.WechatMpPublishValidationError,
            match="Only scheduled WeChat MP publish jobs can be cancelled",
        ):
            publish_service.cancel_publish_job(session, job.user_id, job.id)

        session.expire_all()
        persisted = session.get(WechatMpPublishJob, job.id)
        assert persisted.status == "pending"
        assert persisted.active_key == active_key
    finally:
        session.close()


def test_wechat_mp_due_runner_is_registered_with_scheduler():
    from backend.app.services.scheduler_service import build_wechat_mp_publish_scheduler

    scheduler = build_wechat_mp_publish_scheduler(60)
    try:
        assert scheduler.get_job("wechat_mp_due_publish_runner") is not None
    finally:
        scheduler.shutdown(wait=False) if scheduler.running else None


def test_token_cache_encrypts_access_token_at_rest_and_can_decrypt():
    from backend.app.services.wechat_mp_token_service import get_cached_access_token, normalize_token_cache

    cache = normalize_token_cache({"access_token": "raw-wechat-token", "expires_in": 7200})
    assert "raw-wechat-token" not in str(cache)
    assert get_cached_access_token(cache) == "raw-wechat-token"


def test_deleted_generated_asset_removes_broken_url_before_sync(
    api_client, auth_headers, created_wechat_article_with_image, created_wechat_account, monkeypatch
):
    from backend.app.models import WechatMpAsset
    from backend.app.services import wechat_mp_draft_service as draft_service

    class FakeAdapter:
        def upload_permanent_image(self, **kwargs): return {"media_id": "thumb"}
        def add_draft(self, **kwargs):
            assert "/api/files/media/wechat-inline.png" not in kwargs["article"]["content"]
            return {"media_id": "clean-draft"}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: FakeAdapter())

    client, session_factory = api_client
    session = session_factory()
    try:
        inline = session.query(WechatMpAsset).filter_by(
            article_id=created_wechat_article_with_image.id, role="inline_illustration",
        ).one()
        inline_id = inline.id
    finally:
        session.close()

    deleted = client.delete(f"/api/platforms/wechat-mp/assets/{inline_id}", headers=auth_headers)
    assert deleted.status_code == 200
    article = client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}", headers=auth_headers,
    ).json()
    assert "/api/files/media/wechat-inline.png" not in article["html_body"]
    sync = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": created_wechat_account.id}, headers=auth_headers,
    )
    assert sync.status_code == 201


def test_draft_sync_rejects_missing_local_asset_file(
    api_client, auth_headers, created_wechat_article_with_image, created_wechat_account
):
    from pathlib import Path
    from backend.app.models import WechatMpAsset

    client, session_factory = api_client
    session = session_factory()
    try:
        cover = session.query(WechatMpAsset).filter_by(
            article_id=created_wechat_article_with_image.id, role="cover",
        ).one()
        Path(cover.file_path).unlink()
    finally:
        session.close()

    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article_with_image.id}/sync-draft",
        json={"account_id": created_wechat_account.id}, headers=auth_headers,
    )
    assert response.status_code == 400
    assert "missing local asset" in response.json()["detail"]


def test_repeated_immediate_publish_returns_existing_active_job(
    api_client, auth_headers, synced_wechat_article, monkeypatch
):
    from backend.app.models import WechatMpPublishJob
    from backend.app.services import wechat_mp_publish_service as publish_service

    calls = []

    class FakeAdapter:
        def submit_publish(self, **kwargs):
            calls.append(kwargs)
            return {"publish_id": "publish-once"}

    monkeypatch.setattr(publish_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    client, session_factory = api_client
    url = f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish"

    first = client.post(url, json={"confirm": True}, headers=auth_headers)
    repeated = client.post(url, json={"confirm": True}, headers=auth_headers)

    assert first.status_code == repeated.status_code == 201
    assert repeated.json()["id"] == first.json()["id"]
    assert len(calls) == 1
    session = session_factory()
    try:
        assert session.query(WechatMpPublishJob).filter_by(
            article_id=synced_wechat_article.id,
        ).count() == 1
    finally:
        session.close()


def test_repeated_scheduled_publish_returns_existing_job_and_lists_it(
    api_client, auth_headers, synced_wechat_article
):
    from backend.app.models import WechatMpPublishJob

    client, session_factory = api_client
    url = f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish"
    payload = {"confirm": True, "scheduled_at": "2030-01-02T03:04:05"}

    first = client.post(url, json=payload, headers=auth_headers)
    repeated = client.post(url, json=payload, headers=auth_headers)
    listed = client.get(
        "/api/platforms/wechat-mp/publish-jobs",
        params={"article_id": synced_wechat_article.id},
        headers=auth_headers,
    )

    assert first.status_code == repeated.status_code == 201
    assert repeated.json()["id"] == first.json()["id"]
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [first.json()["id"]]
    session = session_factory()
    try:
        job = session.query(WechatMpPublishJob).one()
        assert job.active_key == (
            f"account:{job.account_id}:article:{job.article_id}:revision:1"
        )
    finally:
        session.close()


def test_due_runner_submits_only_one_legacy_duplicate(
    api_client, auth_headers, synced_wechat_article, monkeypatch
):
    from datetime import datetime

    from backend.app.models import WechatMpPublishJob
    from backend.app.services import wechat_mp_publish_service as publish_service

    client, session_factory = api_client
    scheduled = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True, "scheduled_at": "2026-07-20T00:00:00"},
        headers=auth_headers,
    )
    assert scheduled.status_code == 201
    session = session_factory()
    try:
        original = session.get(WechatMpPublishJob, scheduled.json()["id"])
        duplicate = WechatMpPublishJob(
            user_id=original.user_id,
            account_id=original.account_id,
            article_id=original.article_id,
            draft_sync_id=original.draft_sync_id,
            status="scheduled",
            scheduled_at=original.scheduled_at,
            active_key=None,
        )
        session.add(duplicate)
        session.commit()
        duplicate_id = duplicate.id
    finally:
        session.close()

    calls = []

    class FakeAdapter:
        def submit_publish(self, **kwargs):
            calls.append(kwargs)
            return {"publish_id": "deduplicated-publish"}

    monkeypatch.setattr(publish_service, "_get_access_token", lambda account, adapter: "token")
    session = session_factory()
    try:
        result = publish_service.run_due_publish_jobs(
            db=session, now=datetime(2026, 7, 21), adapter_factory=FakeAdapter,
        )
        assert result["executed_count"] == 1
        assert session.get(WechatMpPublishJob, scheduled.json()["id"]).status == "submitted"
        duplicate = session.get(WechatMpPublishJob, duplicate_id)
        assert duplicate.status == "cancelled"
        assert "duplicate" in duplicate.error_message.lower()
    finally:
        session.close()
    assert len(calls) == 1


def test_wechat_mp_scheduler_starts_when_xhs_scheduler_is_disabled(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from backend.app import main

    calls = []
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(scheduler_enabled=False, scheduler_interval_seconds=37),
    )
    monkeypatch.setattr(main, "start_due_publish_scheduler", lambda interval: calls.append(("xhs", interval)))
    monkeypatch.setattr(
        main,
        "start_wechat_mp_publish_scheduler",
        lambda interval: calls.append(("wechat_mp", interval)) or SimpleNamespace(running=False),
    )
    monkeypatch.setattr(main, "shutdown_due_publish_scheduler", lambda scheduler: None)

    async def exercise_lifespan():
        app = SimpleNamespace(state=SimpleNamespace())
        async with main.lifespan(app):
            assert app.state.scheduler is None
            assert app.state.wechat_mp_scheduler is not None

    asyncio.run(exercise_lifespan())
    assert calls == [("wechat_mp", 37)]


def test_editing_generated_prompt_restores_marker_and_allows_regeneration(
    api_client, auth_headers, created_wechat_prompt, monkeypatch
):
    from backend.app.models import WechatMpArticle
    from backend.app.services import wechat_mp_image_service as image_service

    generated_urls = iter(("/api/files/media/first.png", "/api/files/media/second.png"))
    monkeypatch.setattr(
        image_service,
        "_call_image_model",
        lambda **kwargs: {
            "file_path": "/tmp/wechat-prompt-edit.png",
            "public_url": next(generated_urls),
            "provider_response": {"ok": True},
        },
    )
    client, session_factory = api_client
    image_url = f"/api/platforms/wechat-mp/prompts/{created_wechat_prompt.id}/image"
    first = client.post(image_url, json={"size": "16:9"}, headers=auth_headers)
    assert first.status_code == 201

    edited = client.patch(
        f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}/prompts/{created_wechat_prompt.id}",
        json={"editable_prompt": "编辑后重新生成"},
        headers=auth_headers,
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "prompt_ready"
    article = client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}",
        headers=auth_headers,
    ).json()
    assert article["status"] == "prompts_ready"
    assert f"{{{{image:prompt-{created_wechat_prompt.id}}}}}" in article["html_body"]
    assert "/api/files/media/first.png" not in article["html_body"]

    second = client.post(image_url, json={"size": "16:9"}, headers=auth_headers)
    assert second.status_code == 201
    session = session_factory()
    try:
        assert "/api/files/media/second.png" in session.get(
            WechatMpArticle, created_wechat_prompt.article_id,
        ).html_body
    finally:
        session.close()


def test_none_skill_allows_cover_but_still_uses_normalized_doubao_size(
    api_client, auth_headers, created_wechat_article, monkeypatch
):
    from backend.app.models import WechatMpArticle
    from backend.app.services import wechat_mp_image_service as image_service

    client, session_factory = api_client
    session = session_factory()
    try:
        article = session.get(WechatMpArticle, created_wechat_article.id)
        article.cover_brief = "主角：@小猫生图\n具体画面：小猫压住计划表"
        session.commit()
    finally:
        session.close()

    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {
            "file_path": "/tmp/wechat-none-cover.png",
            "public_url": "/api/files/media/wechat-none-cover.png",
            "provider_response": {"ok": True},
        }

    monkeypatch.setattr(image_service, "_call_image_model", fake_generate)
    switched = client.patch(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}",
        json={"illustration_skill": "none"},
        headers=auth_headers,
    )
    assert switched.status_code == 200
    assert "主角：@" not in switched.json()["cover_brief"]
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/cover",
        json={"size": "16:9"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["role"] == "cover"
    assert captured["model_name"] == "doubao-seedream-4-0-250828"
    assert captured["size"] == "2732x1536"
    assert "主角：@" not in captured["prompt"]
    assert "主角必须是一只胖胖慵懒" not in captured["prompt"]
    assert captured["reference_images"] is None


def test_none_workflow_returns_no_prompts_without_markers_and_syncs(
    api_client, auth_headers, created_wechat_article, created_wechat_account, monkeypatch, tmp_path
):
    from backend.app.services import wechat_mp_draft_service as draft_service
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service
    from backend.app.services import wechat_mp_image_service as image_service

    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: pytest.fail("none must not call the semantic batch"),
    )
    client, _ = api_client
    updated = client.patch(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}",
        json={"illustration_skill": "none"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    prompts = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts",
        json={"skill_name": "none"},
        headers=auth_headers,
    )
    assert prompts.status_code == 201
    assert prompts.json()["items"] == []
    assert "{{image:" not in client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}", headers=auth_headers,
    ).json()["html_body"]

    cover_path = tmp_path / "none-cover.png"
    cover_path.write_bytes(b"cover")
    monkeypatch.setattr(
        image_service,
        "_call_image_model",
        lambda **kwargs: {
            "file_path": str(cover_path),
            "public_url": "/api/files/media/none-cover.png",
            "provider_response": {"ok": True},
        },
    )
    cover = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/cover",
        json={"size": "16:9"},
        headers=auth_headers,
    )
    assert cover.status_code == 201

    class FakeAdapter:
        def upload_permanent_image(self, **kwargs): return {"media_id": "none-thumb"}
        def upload_content_image(self, **kwargs): raise AssertionError("none has no inline images")
        def add_draft(self, **kwargs): return {"media_id": "none-draft"}

    monkeypatch.setattr(draft_service, "WechatMpApiAdapter", lambda: FakeAdapter())
    sync = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/sync-draft",
        json={"account_id": created_wechat_account.id},
        headers=auth_headers,
    )
    assert sync.status_code == 201
    assert sync.json()["wechat_media_id"] == "none-draft"


def test_failed_inline_image_generation_can_retry_with_same_prompt(
    api_client, auth_headers, created_wechat_prompt, monkeypatch
):
    from backend.app.services import wechat_mp_image_service as image_service

    attempts = 0

    def generate(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("provider unavailable")
        return {
            "file_path": "/tmp/retried-inline.png",
            "public_url": "/api/files/media/retried-inline.png",
            "provider_response": {"ok": True},
        }

    monkeypatch.setattr(image_service, "_call_image_model", generate)
    client, _ = api_client
    url = f"/api/platforms/wechat-mp/prompts/{created_wechat_prompt.id}/image"

    first = client.post(url, json={"size": "16:9"}, headers=auth_headers)
    failed_prompt = client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}/prompts",
        headers=auth_headers,
    ).json()[0]
    second = client.post(url, json={"size": "16:9"}, headers=auth_headers)

    assert first.status_code == 502
    assert failed_prompt["status"] == "failed"
    assert second.status_code == 201
    assert second.json()["prompt"] == created_wechat_prompt.editable_prompt
    assert attempts == 2


def test_scheduled_publish_round_trips_as_explicit_utc(
    api_client, auth_headers, synced_wechat_article
):
    from datetime import datetime
    from backend.app.models import WechatMpPublishJob

    client, session_factory = api_client
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{synced_wechat_article.id}/publish",
        json={"confirm": True, "scheduled_at": "2030-01-02T03:04:05+08:00"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["scheduled_at"] == "2030-01-01T19:04:05Z"
    session = session_factory()
    try:
        assert session.get(WechatMpPublishJob, response.json()["id"]).scheduled_at == datetime(2030, 1, 1, 19, 4, 5)
    finally:
        session.close()


def test_image_cost_estimate_uses_requested_or_default_model(api_client, auth_headers):
    client, _ = api_client

    response = client.get(
        "/api/platforms/wechat-mp/image-cost-estimate",
        params={"image_model": "doubao-seedream-4-0-250828"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "model_name": "doubao-seedream-4-0-250828",
        "currency": "CNY",
        "estimated_yuan": "0.2000",
        "pricing_available": True,
    }


def test_deleting_obsolete_asset_keeps_current_prompt_and_article_state(
    api_client, auth_headers, created_wechat_prompt
):
    from backend.app.models import WechatMpArticle, WechatMpAsset, WechatMpImagePrompt

    client, session_factory = api_client
    session = session_factory()
    try:
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        article = session.get(WechatMpArticle, created_wechat_prompt.article_id)
        old_asset = WechatMpAsset(
            user_id=prompt.user_id,
            article_id=article.id,
            prompt_id=prompt.id,
            role="inline_illustration",
            file_path="/tmp/wechat-old.png",
            public_url="/api/files/media/wechat-old.png",
            prompt="old",
            skill_name=prompt.skill_name,
            model_name="test-model",
        )
        current_asset = WechatMpAsset(
            user_id=prompt.user_id,
            article_id=article.id,
            prompt_id=prompt.id,
            role="inline_illustration",
            file_path="/tmp/wechat-current.png",
            public_url="/api/files/media/wechat-current.png",
            prompt="current",
            skill_name=prompt.skill_name,
            model_name="test-model",
        )
        session.add_all([old_asset, current_asset])
        session.flush()
        old_asset_id = old_asset.id
        prompt.status = "generated"
        article.status = "images_ready"
        article.html_body += '<img src="/api/files/media/wechat-current.png" alt="current" />'
        original_revision = article.revision
        original_html = article.html_body
        session.commit()
    finally:
        session.close()

    response = client.delete(
        f"/api/platforms/wechat-mp/assets/{old_asset_id}", headers=auth_headers,
    )
    assert response.status_code == 200
    session = session_factory()
    try:
        article = session.get(WechatMpArticle, created_wechat_prompt.article_id)
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        assert article.html_body == original_html
        assert article.status == "images_ready"
        assert article.revision == original_revision
        assert prompt.status == "generated"
    finally:
        session.close()


def test_wechat_mp_writer_recovers_article_generation_after_slow_response():
    api_source = Path("frontend/src/lib/api.ts").read_text()
    writer_source = Path("frontend/src/pages/platforms/wechat-mp/writer-page.tsx").read_text()

    assert "WECHAT_MP_ARTICLE_TIMEOUT_MS = 420000" in api_source
    assert '"/platforms/wechat-mp/articles", payload, { timeout: WECHAT_MP_ARTICLE_TIMEOUT_MS }' in api_source
    assert "fetchWechatMpArticles" in writer_source
    assert "recoverCreatedArticle" in writer_source
    assert "window.setInterval" in writer_source
    assert "文章已生成，已自动进入编辑步骤。" in writer_source


def test_wechat_mp_writer_surfaces_prompt_analysis_result():
    types_source = Path("frontend/src/types/index.ts").read_text(encoding="utf-8")
    api_source = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")
    writer_source = Path("frontend/src/pages/platforms/wechat-mp/writer-page.tsx").read_text(encoding="utf-8")

    assert "export type WechatMpPromptAnalysis" in types_source
    assert "export type WechatMpPromptGenerationResult" in types_source
    assert "Promise<WechatMpPromptGenerationResult>" in api_source
    assert "http.post<WechatMpPromptGenerationResult>" in api_source
    assert "http.get<WechatMpImagePrompt[]>(`/platforms/wechat-mp/articles/${articleId}/prompts`)" in api_source
    assert "const [promptAnalysis, setPromptAnalysis]" in writer_source
    assert "setPrompts(result.items)" in writer_source
    assert "setPromptAnalysis(result.analysis)" in writer_source
    assert "本次分析：原文 ${promptAnalysis.source_blocks} 段，过滤 ${promptAnalysis.filtered_blocks} 段，复用 ${promptAnalysis.reused_prompts} 条，模型调用 ${promptAnalysis.model_calls} 次，Token ${promptAnalysis.input_tokens + promptAnalysis.output_tokens}。" in writer_source
    assert "未发现值得配图的正文内容，本次未生成装饰性配图。" in writer_source
    assert "已跳过正文提示词和正文生图费用。" in writer_source


def test_wechat_mp_writer_ignores_stale_prompt_generation_updates():
    writer_source = Path("frontend/src/pages/platforms/wechat-mp/writer-page.tsx").read_text(encoding="utf-8")
    make_start = writer_source.index("async function makePrompts()")
    make_end = writer_source.index("async function regenerate(", make_start)
    make_source = writer_source[make_start:make_end]

    assert "const activePromptArticleIdRef = useRef<number | null>(null);" in writer_source
    assert "const promptGenerationTokenRef = useRef(0);" in writer_source
    assert "activePromptArticleIdRef.current = articleId || null;" in writer_source
    assert "promptGenerationTokenRef.current += 1;" in writer_source
    assert "setPrompts([]);" in writer_source
    assert "setPromptAnalysis(null);" in writer_source
    assert "setPromptBusy(false);" in writer_source
    assert "const requestedArticleId = article.id;" in make_source
    assert "const requestToken = ++promptGenerationTokenRef.current;" in make_source
    assert "requestToken === promptGenerationTokenRef.current && activePromptArticleIdRef.current === requestedArticleId" in make_source
    assert make_source.count("if (!isCurrentPromptRequest()) return;") >= 2
    assert "catch (err) {\n      if (!isCurrentPromptRequest()) return;" in make_source
    assert "if (isCurrentPromptRequest()) setPromptBusy(false);" in make_source


def _semantic_batch_candidates(count=2):
    from backend.app.services.wechat_mp_content_analysis_service import ContentBlock, VisualCandidate

    return tuple(
        VisualCandidate(
            ContentBlock(
                source_index=index,
                heading_path=("方案复盘",),
                raw_text=f"候选正文 {index}",
                cleaned_text=f"第{index}个方案需要说明核心问题、实施方法、风险控制与预期结果。",
                fingerprint=f"semantic-{index}",
            ),
            "semantic",
            (),
            0.8,
        )
        for index in range(count)
    )


def test_semantic_batch_sends_one_compact_request_and_prefers_configured_max(monkeypatch):
    import json

    from backend.app.services import wechat_mp_prompt_batch_service as batch_service
    from backend.app.services.wechat_mp_model_service import WechatMpModelContext

    candidates = _semantic_batch_candidates()
    captured_requests = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": json.dumps({"items": [
                    {"id": "0", "prompt": "画出方案实施的关键场景"},
                    {"id": "1", "prompt": "画出风险控制的对比场景"},
                ]}, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 31, "completion_tokens": 17},
            }

    def fake_post(*args, **kwargs):
        captured_requests.append((args, kwargs))
        return FakeResponse()

    monkeypatch.setattr(
        batch_service,
        "resolve_wechat_mp_shotlist_model",
        lambda **kwargs: WechatMpModelContext("qwen3.7-max", "https://models.example/v1", "test-key"),
    )
    monkeypatch.setattr(batch_service.requests, "post", fake_post)

    result = batch_service.generate_semantic_prompts(
        db=Mock(), user_id=11, article_title="方案复盘", candidates=(candidates[0], candidates[1], candidates[0]), character=None,
    )

    assert result.model_calls == 1
    assert result.model_name == "qwen3.7-max"
    assert result.outcome == "success"
    assert result.input_tokens == 31
    assert result.output_tokens == 17
    assert [(item.candidate_id, item.prompt) for item in result.items] == [
        ("0", "画出方案实施的关键场景"),
        ("1", "画出风险控制的对比场景"),
    ]
    assert len(captured_requests) == 1
    request_body = captured_requests[0][1]["json"]
    assert request_body["model"] == "qwen3.7-max"
    assert "方案复盘" not in request_body["messages"][0]["content"]
    payload = json.loads(request_body["messages"][1]["content"])
    assert payload["article_title"] == "方案复盘"
    assert payload["remaining_slots"] == 2
    assert [candidate["id"] for candidate in payload["candidates"]] == ["0", "1"]
    assert all(set(candidate) == {"id", "heading", "text"} for candidate in payload["candidates"])


def test_semantic_batch_sends_only_character_reference_not_character_contract(monkeypatch):
    import json

    from backend.app.models import WechatMpIllustrationCharacter
    from backend.app.services import wechat_mp_prompt_batch_service as batch_service
    from backend.app.services.wechat_mp_model_service import WechatMpModelContext

    character = WechatMpIllustrationCharacter(
        user_id=11,
        name="小猫生图",
        skill_name="xiaomao-illustrations",
        prompt="主角必须是一只胖胖慵懒的玳瑁猫",
    )
    captured = {}

    monkeypatch.setattr(
        batch_service,
        "resolve_wechat_mp_shotlist_model",
        lambda **kwargs: WechatMpModelContext("qwen3.7-max", "https://models.example/v1", "test-key"),
    )
    monkeypatch.setattr(
        batch_service,
        "_call_batch_prompt_model",
        lambda **kwargs: captured.update(kwargs) or {
            "content": '{"items":[]}', "input_tokens": 1, "output_tokens": 1,
        },
    )

    batch_service.generate_semantic_prompts(
        db=Mock(),
        user_id=11,
        article_title="项目管理",
        candidates=_semantic_batch_candidates()[:1],
        character=character,
    )

    payload = json.loads(captured["user_payload"])
    assert payload["character"] == "@小猫生图"
    assert "胖胖慵懒" not in captured["user_payload"]
    assert "只描述具体画面" in batch_service._SYSTEM_PROMPT


def test_semantic_batch_strict_json_ignores_invalid_duplicate_unknown_and_overflow_ids(monkeypatch):
    import json

    from backend.app.services import wechat_mp_prompt_batch_service as batch_service
    from backend.app.services.wechat_mp_model_service import WechatMpModelContext

    candidates = _semantic_batch_candidates(7)
    calls = []
    response_items = [
        {"id": "0", "prompt": "保留的第一条"},
        {"id": "0", "prompt": "重复条目"},
        {"id": "unknown", "prompt": "未知条目"},
        {"id": "6", "prompt": "超出六张上限"},
        {"id": "1", "prompt": "保留的第二条"},
    ]

    monkeypatch.setattr(
        batch_service,
        "resolve_wechat_mp_shotlist_model",
        lambda **kwargs: WechatMpModelContext("qwen3.7-max", "https://models.example/v1", "test-key"),
    )
    monkeypatch.setattr(
        batch_service,
        "_call_batch_prompt_model",
        lambda **kwargs: calls.append(kwargs) or {
            "content": json.dumps({"items": response_items}, ensure_ascii=False),
            "input_tokens": 9,
            "output_tokens": 5,
        },
    )

    result = batch_service.generate_semantic_prompts(
        db=Mock(), user_id=11, article_title="方案复盘", candidates=candidates, character=None,
    )

    assert len(calls) == 1
    assert result.model_calls == 1
    assert [(item.candidate_id, item.prompt) for item in result.items] == [
        ("0", "保留的第一条"),
        ("1", "保留的第二条"),
    ]


def test_semantic_batch_malformed_or_non_quota_failures_degrade_without_retry(monkeypatch):
    from backend.app.services import wechat_mp_prompt_batch_service as batch_service
    from backend.app.services.wechat_mp_model_service import WechatMpModelContext

    candidates = _semantic_batch_candidates()
    calls = []
    monkeypatch.setattr(
        batch_service,
        "resolve_wechat_mp_shotlist_model",
        lambda **kwargs: WechatMpModelContext("qwen3.7-max", "https://models.example/v1", "test-key"),
    )
    monkeypatch.setattr(
        batch_service,
        "_call_batch_prompt_model",
        lambda **kwargs: calls.append(kwargs) or {"content": "```json\\n{}\\n```", "input_tokens": 8, "output_tokens": 2},
    )

    malformed = batch_service.generate_semantic_prompts(
        db=Mock(), user_id=11, article_title="方案复盘", candidates=candidates, character=None,
    )

    assert malformed.items == ()
    assert malformed.outcome == "parse_degraded"
    assert malformed.model_calls == 1
    assert malformed.input_tokens == 8
    assert len(calls) == 1
    monkeypatch.setattr(batch_service, "_call_batch_prompt_model", lambda **kwargs: calls.append(kwargs) or (_ for _ in ()).throw(ValueError("connection reset")))

    failed = batch_service.generate_semantic_prompts(
        db=Mock(), user_id=11, article_title="方案复盘", candidates=candidates, character=None,
    )

    assert failed.items == ()
    assert failed.outcome == "provider_failed"
    assert failed.model_calls == 1
    assert len(calls) == 2


def test_semantic_batch_retries_once_with_shotlist_fallback_only_for_quota_errors(monkeypatch):
    import json

    from backend.app.services import wechat_mp_prompt_batch_service as batch_service
    from backend.app.services.wechat_mp_model_service import WechatMpModelContext

    candidates = _semantic_batch_candidates()
    resolved = []
    calls = []

    def resolve_model(**kwargs):
        resolved.append(kwargs.get("excluded_model_names", set()))
        return WechatMpModelContext(
            "qwen3.7-max" if len(resolved) == 1 else "qwen3.7-plus",
            "https://models.example/v1",
            "test-key",
        )

    def call_model(**kwargs):
        calls.append(kwargs["model"].model_name)
        if len(calls) == 1:
            raise ValueError("quota exhausted")
        return {
            "content": json.dumps({"items": [{"id": "0", "prompt": "降级模型生成的场景"}]}, ensure_ascii=False),
            "input_tokens": 12,
            "output_tokens": 7,
        }

    monkeypatch.setattr(batch_service, "resolve_wechat_mp_shotlist_model", resolve_model)
    monkeypatch.setattr(batch_service, "_call_batch_prompt_model", call_model)

    result = batch_service.generate_semantic_prompts(
        db=Mock(), user_id=11, article_title="方案复盘", candidates=candidates, character=None,
    )

    assert calls == ["qwen3.7-max", "qwen3.7-plus"]
    assert resolved == [set(), {"qwen3.7-max"}]
    assert result.model_calls == 2
    assert result.model_name == "qwen3.7-plus"
    assert [(item.candidate_id, item.prompt) for item in result.items] == [("0", "降级模型生成的场景")]


def test_semantic_batch_does_not_count_a_failed_fallback_selection_as_a_model_call(monkeypatch):
    from backend.app.services import wechat_mp_prompt_batch_service as batch_service
    from backend.app.services.model_selector_service import ModelSelectionError
    from backend.app.services.wechat_mp_model_service import WechatMpModelContext

    resolved = []

    def resolve_model(**kwargs):
        resolved.append(kwargs.get("excluded_model_names", set()))
        if len(resolved) == 1:
            return WechatMpModelContext("qwen3.7-max", "https://models.example/v1", "test-key")
        raise ModelSelectionError("No configured text model supports shotlist")

    monkeypatch.setattr(batch_service, "resolve_wechat_mp_shotlist_model", resolve_model)
    monkeypatch.setattr(
        batch_service,
        "_call_batch_prompt_model",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("quota exhausted")),
    )

    result = batch_service.generate_semantic_prompts(
        db=Mock(), user_id=11, article_title="方案复盘", candidates=_semantic_batch_candidates(), character=None,
    )

    assert resolved == [set(), {"qwen3.7-max"}]
    assert result.items == ()
    assert result.outcome == "provider_failed"
    assert result.model_calls == 1


def test_semantic_batch_without_a_config_degrades_before_any_provider_call(db_session, test_user, monkeypatch):
    from backend.app.services import wechat_mp_prompt_batch_service as batch_service

    monkeypatch.setattr(batch_service.requests, "post", lambda **kwargs: pytest.fail("missing config must not call provider"))

    result = batch_service.generate_semantic_prompts(
        db=db_session, user_id=test_user.id, article_title="方案复盘", candidates=_semantic_batch_candidates(), character=None,
    )

    assert result.items == ()
    assert result.outcome == "no_config"
    assert result.model_name is None
    assert result.model_calls == 0


def test_semantic_batch_skips_unusable_max_for_an_eligible_user_scoped_fallback(db_session, test_user, monkeypatch):
    import json

    from backend.app.core.security import encrypt_text
    from backend.app.models import ModelConfig
    from backend.app.services import wechat_mp_prompt_batch_service as batch_service

    db_session.add_all([
        ModelConfig(
            user_id=test_user.id, name="Unavailable Max", model_type="text", provider="openai-compatible",
            model_name="qwen3.7-max", base_url="https://max.example/v1", encrypted_api_key="", is_default=True,
        ),
        ModelConfig(
            user_id=test_user.id, name="Usable Plus", model_type="text", provider="openai-compatible",
            model_name="qwen3.7-plus", base_url="https://plus.example/v1", encrypted_api_key=encrypt_text("plus-key"), is_default=False,
        ),
    ])
    db_session.commit()
    captured = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": json.dumps({"items": [{"id": "0", "prompt": "备用模型提示词"}]}, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }

    monkeypatch.setenv("WECHAT_MP_PROMPT_API_KEY", "process-wide-secret")
    monkeypatch.setattr(batch_service.requests, "post", lambda *args, **kwargs: captured.append(kwargs) or FakeResponse())

    result = batch_service.generate_semantic_prompts(
        db=db_session, user_id=test_user.id, article_title="方案复盘", candidates=_semantic_batch_candidates(), character=None,
    )

    assert result.model_name == "qwen3.7-plus"
    assert result.model_calls == 1
    assert len(captured) == 1
    assert captured[0]["json"]["model"] == "qwen3.7-plus"
    assert captured[0]["headers"]["Authorization"] == "Bearer plus-key"


def test_semantic_batch_never_uses_process_wide_secrets_for_an_incomplete_user_config(db_session, test_user, monkeypatch):
    from backend.app.models import ModelConfig
    from backend.app.services import wechat_mp_prompt_batch_service as batch_service

    db_session.add(ModelConfig(
        user_id=test_user.id, name="Incomplete Max", model_type="text", provider="openai-compatible",
        model_name="qwen3.7-max", base_url="", encrypted_api_key="", is_default=True,
    ))
    db_session.commit()
    monkeypatch.setenv("WECHAT_MP_PROMPT_BASE_URL", "https://process.example/v1")
    monkeypatch.setenv("WECHAT_MP_PROMPT_API_KEY", "process-wide-secret")
    monkeypatch.setattr(batch_service.requests, "post", lambda **kwargs: pytest.fail("incomplete user config must not call provider"))

    result = batch_service.generate_semantic_prompts(
        db=db_session, user_id=test_user.id, article_title="方案复盘", candidates=_semantic_batch_candidates(), character=None,
    )

    assert result.items == ()
    assert result.outcome == "no_config"
    assert result.model_name is None
    assert result.model_calls == 0


def test_semantic_batch_counts_a_failed_provider_call_after_successful_fallback_selection(monkeypatch):
    from backend.app.services import wechat_mp_prompt_batch_service as batch_service
    from backend.app.services.wechat_mp_model_service import WechatMpModelContext

    resolved = []
    provider_calls = []

    def resolve_model(**kwargs):
        resolved.append(kwargs.get("excluded_model_names", set()))
        return WechatMpModelContext(
            "qwen3.7-max" if len(resolved) == 1 else "qwen3.7-plus",
            "https://models.example/v1",
            "test-key",
        )

    def call_model(**kwargs):
        provider_calls.append(kwargs["model"].model_name)
        raise ValueError("quota exhausted" if len(provider_calls) == 1 else "provider unavailable")

    monkeypatch.setattr(batch_service, "resolve_wechat_mp_shotlist_model", resolve_model)
    monkeypatch.setattr(batch_service, "_call_batch_prompt_model", call_model)

    result = batch_service.generate_semantic_prompts(
        db=Mock(), user_id=11, article_title="方案复盘", candidates=_semantic_batch_candidates(), character=None,
    )

    assert resolved == [set(), {"qwen3.7-max"}]
    assert provider_calls == ["qwen3.7-max", "qwen3.7-plus"]
    assert result.items == ()
    assert result.model_name == "qwen3.7-plus"
    assert result.model_calls == 2


def test_wechat_shotlist_model_prefers_configured_qwen_max_and_uses_selector_when_excluded(db_session, test_user, monkeypatch):
    from backend.app.core.security import encrypt_text
    from backend.app.models import ModelConfig
    from backend.app.services import wechat_mp_model_service as model_service

    qwen_max = ModelConfig(
        user_id=test_user.id, name="Qwen Max", model_type="text", provider="openai-compatible",
        model_name="qwen3.7-max", base_url="https://max.example/v1", encrypted_api_key=encrypt_text("max-key"), is_default=False,
    )
    fallback = ModelConfig(
        user_id=test_user.id, name="Qwen Plus", model_type="text", provider="openai-compatible",
        model_name="qwen3.7-plus", base_url="https://plus.example/v1", encrypted_api_key=encrypt_text("plus-key"), is_default=True,
    )
    db_session.add_all([qwen_max, fallback])
    db_session.commit()
    selector_calls = []
    monkeypatch.setattr(
        model_service,
        "select_model_config",
        lambda *args, **kwargs: selector_calls.append(kwargs.get("excluded_model_names", set())) or fallback,
    )

    preferred = model_service.resolve_wechat_mp_shotlist_model(db=db_session, user_id=test_user.id)
    excluded = model_service.resolve_wechat_mp_shotlist_model(
        db=db_session, user_id=test_user.id, excluded_model_names={"qwen3.7-max"},
    )

    assert preferred.model_name == "qwen3.7-max"
    assert preferred.api_key == "max-key"
    assert excluded.model_name == "qwen3.7-plus"
    assert selector_calls == [{"qwen3.7-max"}]


def _orchestration_semantic_paragraphs():
    return [
        "交付延误的核心问题是跨团队等待，方法是合并审批节点并追踪结果。",
        "用户流失的关键原因是首次体验复杂，策略是缩短注册路径并对比转化。",
        "库存风险来自销量波动，解决原则是分层补货与每日预警。",
        "数据质量下降会影响结论，实践方法是溯源异常字段并校验修复结果。",
        "远程协作的冲突集中在信息不对称，关键选择是公开决策记录。",
        "营销投放结果低于目标，调整策略是分组实验创意与人群。",
        "客诉处理的方法是先识别情绪风险，再根据责任范围给出解决结果。",
    ]


def test_prompt_orchestration_mixes_deterministic_and_one_capped_semantic_batch_with_exact_cost(
    db_session, test_user, monkeypatch,
):
    from decimal import Decimal

    from backend.app.models import UsageRecord, WechatMpArticle
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service
    from backend.app.services.wechat_mp_prompt_batch_service import BatchPromptItem, BatchPromptResult

    article = WechatMpArticle(
        user_id=test_user.id,
        title="混合候选",
        markdown_body=(
            "收集需求 → 分析需求 → 确认需求\n\n"
            "| 阶段 | 产物 |\n| --- | --- |\n| 收集 | 清单 |\n\n"
            "输入：原始数据\n输出：标准数据\n\n"
            + "\n\n".join(_orchestration_semantic_paragraphs())
        ),
        html_body="<p>混合候选</p>",
        status="layout_ready",
    )
    db_session.add(article)
    db_session.commit()
    batch_calls = []
    commits = []
    real_commit = db_session.commit

    def tracked_commit():
        commits.append(True)
        real_commit()

    monkeypatch.setattr(db_session, "commit", tracked_commit)

    def fake_batch(**kwargs):
        batch_calls.append(kwargs["candidates"])
        assert len(kwargs["candidates"]) == 5
        return BatchPromptResult(
            items=tuple(
                BatchPromptItem(candidate_id=str(candidate.source_index), prompt=f"语义提示词 {candidate.source_index}")
                for candidate in kwargs["candidates"]
            ),
            input_tokens=1,
            output_tokens=20,
            model_name="qwen3.7-max",
            model_calls=1,
            outcome="success",
        )

    monkeypatch.setattr(prompt_service, "generate_semantic_prompts", fake_batch)

    result = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )

    assert len(batch_calls) == 1
    assert len(commits) == 1
    assert len(result.items) == 8
    assert result.analysis.deterministic_prompts == 3
    assert result.analysis.semantic_candidates == 5
    assert result.analysis.model_calls == 1
    usage = db_session.query(UsageRecord).filter_by(
        resource_id=article.id, step="generate_image_prompts_batch",
    ).one()
    semantic_costs = [
        Decimal(prompt.cost_estimate["total_yuan"])
        for prompt in result.items
        if "语义提示词" in prompt.prompt
    ]
    assert sum(semantic_costs, Decimal("0.0000")) == usage.cost_yuan
    assert db_session.query(UsageRecord).filter_by(resource_id=article.id).count() == 1


def test_prompt_orchestration_caps_pure_semantic_batch_at_six(db_session, test_user, monkeypatch):
    from backend.app.models import UsageRecord, WechatMpArticle
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service
    from backend.app.services.wechat_mp_prompt_batch_service import BatchPromptItem, BatchPromptResult

    article = WechatMpArticle(
        user_id=test_user.id,
        title="纯语义候选",
        markdown_body="\n\n".join(_orchestration_semantic_paragraphs()),
        html_body="<p>纯语义候选</p>",
        status="layout_ready",
    )
    db_session.add(article)
    db_session.commit()
    batch_sizes = []

    def fake_batch(**kwargs):
        batch_sizes.append(len(kwargs["candidates"]))
        return BatchPromptResult(
            items=tuple(
                BatchPromptItem(candidate_id=str(candidate.source_index), prompt=f"语义提示词 {candidate.source_index}")
                for candidate in kwargs["candidates"]
            ),
            input_tokens=10,
            output_tokens=30,
            model_name="qwen3.7-max",
            model_calls=1,
            outcome="success",
        )

    monkeypatch.setattr(prompt_service, "generate_semantic_prompts", fake_batch)

    result = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )

    assert batch_sizes == [6]
    assert len(result.items) == 6
    assert len(result.items) <= 8
    assert result.analysis.deterministic_prompts == 0
    assert result.analysis.semantic_candidates == 6
    assert db_session.query(UsageRecord).filter_by(
        resource_id=article.id, step="generate_image_prompts_batch",
    ).count() == 1


@pytest.mark.parametrize(
    ("markdown_body", "skill_name"),
    [
        ("# 结尾\n\n欢迎关注，下一篇再见。", None),
        ("核心问题、解决方法、执行风险和最终结果都需要展示。", "none"),
    ],
)
def test_prompt_api_returns_201_empty_response_and_zero_usage_for_no_candidate_or_none(
    api_client, auth_headers, monkeypatch, markdown_body, skill_name,
):
    from decimal import Decimal

    from backend.app.models import UsageRecord, User, WechatMpArticle
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="空结果",
            markdown_body=markdown_body,
            html_body="<p>空结果</p>",
            status="layout_ready",
            illustration_skill=skill_name or "xiaomao-illustrations",
        )
        session.add(article)
        session.commit()
        article_id = article.id
    finally:
        session.close()
    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: pytest.fail("empty and none flows must not call a semantic batch"),
    )

    response = client.post(
        f"/api/platforms/wechat-mp/articles/{article_id}/prompts",
        json={"skill_name": skill_name} if skill_name else None,
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert set(response.json()) == {"items", "analysis"}
    assert response.json()["items"] == []
    assert response.json()["analysis"]["model_calls"] == 0
    session = session_factory()
    try:
        assert session.query(UsageRecord).filter_by(resource_id=article_id).count() == 0
        cost_estimate = session.get(WechatMpArticle, article_id).cost_estimate
        assert Decimal(str(cost_estimate.get("total_yuan", "0"))) == Decimal("0.0000")
    finally:
        session.close()


def test_prompt_api_returns_400_for_article_without_rendered_layout(api_client, auth_headers, monkeypatch):
    from backend.app.models import User, WechatMpArticle
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="未排版文章",
            markdown_body="核心问题需要解决。",
            html_body="",
            status="draft_local",
        )
        session.add(article)
        session.commit()
        article_id = article.id
    finally:
        session.close()
    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: pytest.fail("invalid article state must not call a semantic batch"),
    )

    response = client.post(
        f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers,
    )

    assert response.status_code == 400


def test_prompt_orchestration_cleans_obsolete_prompts_but_retains_asset_row_and_file(
    db_session, test_user, tmp_path, monkeypatch,
):
    from backend.app.models import WechatMpArticle, WechatMpArticleSection, WechatMpAsset, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    retained_file = tmp_path / "historical-inline.png"
    retained_file.write_bytes(b"historical")
    article = WechatMpArticle(
        user_id=test_user.id,
        title="已删除的候选",
        markdown_body="收集新需求 → 分析新需求 → 确认新需求",
        html_body="<p>收集新需求 → 分析新需求 → 确认新需求</p>",
        status="layout_ready",
    )
    db_session.add(article)
    db_session.flush()
    section = WechatMpArticleSection(
        user_id=test_user.id, article_id=article.id, section_index=0, summary="旧段落",
        source_excerpt="旧段落", source_fingerprint="obsolete", analysis_version="v2", needs_image=True,
    )
    db_session.add(section)
    db_session.flush()
    prompt = WechatMpImagePrompt(
        user_id=test_user.id, article_id=article.id, section_id=section.id, skill_name="xiaomao-illustrations",
        prompt="旧提示词", editable_prompt="旧提示词", generation_fingerprint="obsolete",
        status="prompt_ready", cost_estimate={"currency": "CNY", "total_yuan": "0.1000", "calls": 1},
    )
    db_session.add(prompt)
    db_session.flush()
    asset = WechatMpAsset(
        user_id=test_user.id, article_id=article.id, prompt_id=prompt.id, role="inline_illustration",
        file_path=str(retained_file), public_url="/api/files/media/historical-inline.png", prompt="旧提示词",
        skill_name="xiaomao-illustrations", model_name="image-model", status="generated",
    )
    db_session.add(asset)
    independent_asset = WechatMpAsset(
        user_id=test_user.id, article_id=article.id, prompt_id=None, role="inline_illustration",
        file_path=str(tmp_path / "independent.png"), public_url="/api/files/media/independent.png",
        prompt="独立配图", skill_name="xiaomao-illustrations", model_name="image-model", status="generated",
    )
    db_session.add(independent_asset)
    article.html_body = (
        '<p>收集新需求 → 分析新需求 → 确认新需求</p>\n'
        f'<p>旧段落</p>\n{{{{image:prompt-{prompt.id}}}}}\n'
        '<img src="/api/files/media/historical-inline.png" alt="旧配图" />\n'
        '<img src="/api/files/media/independent.png" alt="独立配图" />'
    )
    db_session.commit()
    asset_id = asset.id
    obsolete_prompt_id = prompt.id
    monkeypatch.setattr(
        prompt_service, "generate_semantic_prompts", lambda **kwargs: pytest.fail("no candidates must not call a batch"),
    )

    result = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )

    assert len(result.items) == 1
    assert db_session.query(WechatMpImagePrompt).filter_by(article_id=article.id).count() == 1
    assert db_session.query(WechatMpArticleSection).filter_by(article_id=article.id).count() == 1
    retained_asset = db_session.get(WechatMpAsset, asset_id)
    assert retained_asset is not None
    assert retained_asset.prompt_id is None
    assert retained_file.exists()
    current_marker = f"{{{{image:prompt-{result.items[0].id}}}}}"
    assert f"<p>旧段落</p>\n{{{{image:prompt-{obsolete_prompt_id}}}}}" not in article.html_body
    assert article.html_body.count(current_marker) == 1
    assert retained_asset.public_url not in article.html_body
    assert independent_asset.public_url in article.html_body


def test_unchanged_prompt_rerun_preserves_article_revision(db_session, test_user, monkeypatch):
    from backend.app.models import WechatMpArticle
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    article = WechatMpArticle(
        user_id=test_user.id,
        title="稳定流程",
        markdown_body="收集需求 → 分析需求 → 确认需求",
        html_body="<p>收集需求 → 分析需求 → 确认需求</p>",
        status="layout_ready",
    )
    db_session.add(article)
    db_session.commit()
    monkeypatch.setattr(
        prompt_service, "generate_semantic_prompts", lambda **kwargs: pytest.fail("deterministic flow must not call a batch"),
    )

    first = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )
    first_revision = article.revision
    second = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )

    assert [prompt.id for prompt in second.items] == [prompt.id for prompt in first.items]
    assert second.analysis.reused_prompts == 1
    assert article.revision == first_revision


def test_prompt_api_rolls_back_pure_semantic_provider_failure(api_client, auth_headers, monkeypatch):
    from backend.app.models import UsageRecord, User, WechatMpArticle, WechatMpArticleSection, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service
    from backend.app.services.wechat_mp_prompt_batch_service import BatchPromptResult

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="供应商失败",
            markdown_body="核心问题、解决方法、执行风险和最终结果都需要展示。",
            html_body="<p>核心问题、解决方法、执行风险和最终结果都需要展示。</p>",
            status="layout_ready",
        )
        session.add(article)
        session.commit()
        article_id = article.id
        original_revision = article.revision
    finally:
        session.close()
    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: BatchPromptResult((), 0, 0, "qwen3.7-max", 1, "provider_failed"),
    )

    response = client.post(
        f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers,
    )

    assert response.status_code == 502
    session = session_factory()
    try:
        assert session.query(WechatMpArticleSection).filter_by(article_id=article_id).count() == 0
        assert session.query(WechatMpImagePrompt).filter_by(article_id=article_id).count() == 0
        assert session.query(UsageRecord).filter_by(resource_id=article_id).count() == 0
        assert session.get(WechatMpArticle, article_id).revision == original_revision
    finally:
        session.close()


def test_unchanged_generated_prompt_preserves_embedded_asset_status_and_revision(
    db_session, test_user, tmp_path, monkeypatch,
):
    from backend.app.models import WechatMpArticle, WechatMpAsset
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    article = WechatMpArticle(
        user_id=test_user.id,
        title="已生成流程",
        markdown_body="收集需求 → 分析需求 → 确认需求",
        html_body="<p>收集需求 → 分析需求 → 确认需求</p>",
        status="layout_ready",
    )
    db_session.add(article)
    db_session.commit()
    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: pytest.fail("deterministic prompt must not call a semantic batch"),
    )
    first = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )
    prompt = first.items[0]
    marker = f"{{{{image:prompt-{prompt.id}}}}}"
    image_path = tmp_path / "current-generated.png"
    image_path.write_bytes(b"generated")
    public_url = "/api/files/media/current-generated.png"
    image_html = f'<img src="{public_url}" alt="当前配图" />'
    asset = WechatMpAsset(
        user_id=test_user.id,
        article_id=article.id,
        prompt_id=prompt.id,
        role="inline_illustration",
        file_path=str(image_path),
        public_url=public_url,
        prompt=prompt.prompt,
        skill_name=prompt.skill_name,
        model_name="image-model",
        status="generated",
    )
    db_session.add(asset)
    prompt.status = "generated"
    article.status = "images_ready"
    article.html_body = article.html_body.replace(marker, image_html)
    db_session.commit()
    original_html = article.html_body
    original_revision = article.revision

    rerun = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )

    assert [item.id for item in rerun.items] == [prompt.id]
    assert rerun.items[0].status == "generated"
    assert rerun.items[0].cost_estimate == {"currency": "CNY", "total_yuan": "0.0000", "calls": 0}
    assert article.html_body == original_html
    assert marker not in article.html_body
    assert article.revision == original_revision
    assert asset.prompt_id == prompt.id
    assert image_path.exists()


def test_prompt_api_degrades_malformed_semantic_json_without_502(api_client, auth_headers, monkeypatch):
    from backend.app.models import UsageRecord, User, WechatMpArticle
    from backend.app.services import wechat_mp_prompt_batch_service as batch_service
    from backend.app.services.wechat_mp_model_service import WechatMpModelContext

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="解析降级",
            markdown_body="核心问题是入口太多，解决方法是先完成最小动作并根据结果决定下一步。",
            html_body="<p>核心问题是入口太多，解决方法是先完成最小动作。</p>",
            status="layout_ready",
        )
        session.add(article)
        session.commit()
        article_id = article.id
    finally:
        session.close()
    monkeypatch.setattr(
        batch_service,
        "resolve_wechat_mp_shotlist_model",
        lambda **kwargs: WechatMpModelContext("qwen3.7-max", "https://models.example/v1", "test-key"),
    )
    monkeypatch.setattr(
        batch_service,
        "_call_batch_prompt_model",
        lambda **kwargs: {"content": "not-json", "input_tokens": 11, "output_tokens": 7},
    )

    response = client.post(
        f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["items"] == []
    assert response.json()["analysis"]["model_calls"] == 1
    session = session_factory()
    try:
        usage = session.query(UsageRecord).filter_by(
            resource_id=article_id, step="generate_image_prompts_batch",
        ).one()
        assert (usage.input_tokens, usage.output_tokens) == (11, 7)
    finally:
        session.close()


@pytest.mark.parametrize("failure_phase", ["initial", "fallback"])
def test_prompt_orchestration_propagates_model_resolution_db_errors_and_rolls_back(
    api_client, auth_headers, monkeypatch, failure_phase,
):
    from sqlalchemy.exc import SQLAlchemyError

    from backend.app.models import UsageRecord, User, WechatMpArticle, WechatMpArticleSection, WechatMpImagePrompt
    from backend.app.services import wechat_mp_prompt_batch_service as batch_service
    from backend.app.services.wechat_mp_model_service import WechatMpModelContext

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="事务回滚",
            markdown_body="关键问题是数据错乱，解决方法是溯源字段并验证修复结果。",
            html_body="<p>关键问题是数据错乱，解决方法是溯源字段。</p>",
            status="layout_ready",
        )
        session.add(article)
        session.commit()
        article_id = article.id
        original_revision = article.revision
    finally:
        session.close()
    resolution_calls = []

    def resolve_model(**kwargs):
        resolution_calls.append(kwargs.get("excluded_model_names", set()))
        if failure_phase == "initial" or len(resolution_calls) == 2:
            raise SQLAlchemyError(f"{failure_phase} resolution database failure")
        return WechatMpModelContext("qwen3.7-max", "https://models.example/v1", "test-key")

    monkeypatch.setattr(batch_service, "resolve_wechat_mp_shotlist_model", resolve_model)
    monkeypatch.setattr(
        batch_service,
        "_call_batch_prompt_model",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("quota exhausted")),
    )

    with pytest.raises(SQLAlchemyError, match="resolution database failure"):
        client.post(f"/api/platforms/wechat-mp/articles/{article_id}/prompts", headers=auth_headers)

    session = session_factory()
    try:
        assert session.query(WechatMpArticleSection).filter_by(article_id=article_id).count() == 0
        assert session.query(WechatMpImagePrompt).filter_by(article_id=article_id).count() == 0
        assert session.query(UsageRecord).filter_by(resource_id=article_id).count() == 0
        assert session.get(WechatMpArticle, article_id).revision == original_revision
    finally:
        session.close()


def test_prompt_orchestration_reconciles_duplicate_siblings_and_retains_assets(
    db_session, test_user, tmp_path, monkeypatch,
):
    from backend.app.models import WechatMpArticle, WechatMpAsset, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    article = WechatMpArticle(
        user_id=test_user.id,
        title="重复提示词",
        markdown_body="收集数据 → 清洗数据 → 输出数据",
        html_body="<p>收集数据 → 清洗数据 → 输出数据</p>",
        status="layout_ready",
    )
    db_session.add(article)
    db_session.commit()
    monkeypatch.setattr(
        prompt_service,
        "generate_semantic_prompts",
        lambda **kwargs: pytest.fail("deterministic prompt must not call a semantic batch"),
    )
    original = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    ).items[0]
    duplicate = WechatMpImagePrompt(
        user_id=original.user_id,
        article_id=original.article_id,
        section_id=original.section_id,
        character_id=original.character_id,
        skill_name=original.skill_name,
        skill_version=original.skill_version,
        prompt=original.prompt,
        editable_prompt=original.editable_prompt,
        generation_fingerprint=original.generation_fingerprint,
        version=original.version,
        status="prompt_ready",
        cost_estimate={"currency": "CNY", "total_yuan": "0.0000", "calls": 0},
    )
    db_session.add(duplicate)
    db_session.flush()
    old_file = tmp_path / "duplicate-old.png"
    old_file.write_bytes(b"old")
    old_url = "/api/files/media/duplicate-old.png"
    old_asset = WechatMpAsset(
        user_id=test_user.id,
        article_id=article.id,
        prompt_id=original.id,
        role="inline_illustration",
        file_path=str(old_file),
        public_url=old_url,
        prompt=original.prompt,
        skill_name=original.skill_name,
        model_name="image-model",
        status="generated",
    )
    db_session.add(old_asset)
    original_marker = f"{{{{image:prompt-{original.id}}}}}"
    duplicate_marker = f"{{{{image:prompt-{duplicate.id}}}}}"
    article.html_body = article.html_body.replace(
        original_marker,
        f'<img src="{old_url}" alt="旧图" />\n{original_marker}\n{duplicate_marker}',
    )
    db_session.commit()
    old_asset_id = old_asset.id
    original_id = original.id
    duplicate_id = duplicate.id

    result = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )

    assert [item.id for item in result.items] == [duplicate_id]
    assert db_session.query(WechatMpImagePrompt).filter_by(section_id=duplicate.section_id).count() == 1
    assert db_session.get(WechatMpImagePrompt, original_id) is None
    retained_asset = db_session.get(WechatMpAsset, old_asset_id)
    assert retained_asset is not None
    assert retained_asset.prompt_id is None
    assert old_file.exists()
    assert old_url not in article.html_body
    assert original_marker not in article.html_body
    assert article.html_body.count(duplicate_marker) == 1


def test_reused_semantic_prompt_has_zero_current_run_cost_without_changing_history(
    db_session, test_user, monkeypatch,
):
    from backend.app.models import UsageRecord, WechatMpArticle
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service
    from backend.app.services.wechat_mp_prompt_batch_service import BatchPromptItem, BatchPromptResult

    article = WechatMpArticle(
        user_id=test_user.id,
        title="复用成本",
        markdown_body="核心问题是路径太长，解决方法是合并节点并根据结果验证效果。",
        html_body="<p>核心问题是路径太长，解决方法是合并节点。</p>",
        status="layout_ready",
    )
    db_session.add(article)
    db_session.commit()
    batch_calls = []

    def fake_batch(**kwargs):
        batch_calls.append(True)
        candidate = kwargs["candidates"][0]
        return BatchPromptResult(
            items=(BatchPromptItem(str(candidate.source_index), "复用成本提示词"),),
            input_tokens=1000,
            output_tokens=2000,
            model_name="qwen3.7-max",
            model_calls=1,
            outcome="success",
        )

    monkeypatch.setattr(prompt_service, "generate_semantic_prompts", fake_batch)
    first = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )
    assert first.items[0].cost_estimate["calls"] == 1
    historical_article_cost = dict(article.cost_estimate)
    historical_usage_count = db_session.query(UsageRecord).filter_by(resource_id=article.id).count()
    historical_revision = article.revision

    second = prompt_service.generate_image_prompts(
        db=db_session, user_id=test_user.id, article_id=article.id, skill_name=None,
    )

    assert batch_calls == [True]
    assert second.items[0].cost_estimate == {"currency": "CNY", "total_yuan": "0.0000", "calls": 0}
    assert article.cost_estimate == historical_article_cost
    assert db_session.query(UsageRecord).filter_by(resource_id=article.id).count() == historical_usage_count
    assert article.revision == historical_revision


def test_allocate_cost_assigns_all_decimal_remainder_to_final_semantic_item():
    from decimal import Decimal

    from backend.app.services.wechat_mp_image_prompt_service import _allocate_cost

    allocations = _allocate_cost(Decimal("0.0005"), 3)

    assert allocations == [Decimal("0.0001"), Decimal("0.0001"), Decimal("0.0003")]
    assert sum(allocations, Decimal("0.0000")) == Decimal("0.0005")

def test_character_mention_formats_and_parses_the_full_reference_line():
    from backend.app.models import WechatMpIllustrationCharacter
    from backend.app.services.wechat_mp_character_service import (
        format_character_prompt,
        parse_character_mention,
    )

    character = WechatMpIllustrationCharacter(
        user_id=1,
        name="小猫生图",
        skill_name="xiaomao-illustrations",
        prompt="完整形象介绍",
    )
    stored = format_character_prompt(character, "小猫压住流程图")
    assert stored == "主角：@小猫生图\n具体画面：小猫压住流程图"
    assert parse_character_mention(stored) == ("小猫生图", "具体画面：小猫压住流程图")


def test_character_prompt_canonicalization_removes_legacy_character_rules_but_keeps_scene():
    from backend.app.models import WechatMpIllustrationCharacter
    from backend.app.services.wechat_mp_character_service import (
        canonicalize_character_prompt,
    )

    character = WechatMpIllustrationCharacter(
        user_id=1,
        name="小猫生图",
        skill_name="xiaomao-illustrations",
        prompt="自定义的新形象合同",
    )
    legacy_mixed_prompt = (
        "主角：@小猫生图\n"
        "具体画面：白色背景，横向画幅，轻微抖动的手绘线稿；"
        "一只胖胖慵懒、半推半就但会把活干完的玳瑁猫，身体以黑白色块为主，"
        "背、头、尾点缀少量橙斑，半闭眼、冷淡表情；"
        "小猫自然趴卧，爪子压着一张简单的树状结构图（代表WBS），"
        "旁边放着放大镜和打勾的印章；"
        "画面留白充足，一图一个核心结构，不使用写实摄影、3D 渲染、复杂背景或大段文字；"
        "不得渲染标题、比例、尺寸、提示词、说明文字、水印、签名或图中文字。"
    )

    result = canonicalize_character_prompt(character, legacy_mixed_prompt, include_character=True)

    assert result == (
        "主角：@小猫生图\n"
        "具体画面：小猫自然趴卧，爪子压着一张简单的树状结构图（代表WBS），"
        "旁边放着放大镜和打勾的印章"
    )
    assert "胖胖慵懒" not in result
    assert "手绘线稿" not in result
    assert "不得渲染" not in result


def test_ensure_builtin_character_upgrades_legacy_narrator_contract(db_session, test_user):
    from backend.app.models import WechatMpIllustrationCharacter
    from backend.app.services.wechat_mp_character_service import (
        XIAOMAO_PROMPT,
        ensure_builtin_character,
    )

    character = WechatMpIllustrationCharacter(
        user_id=test_user.id,
        name="小猫生图",
        skill_name="xiaomao-illustrations",
        prompt="小猫必须承担画面的核心概念动作",
        status="confirmed",
        anchor_version=4,
    )
    db_session.add(character)
    db_session.commit()

    upgraded = ensure_builtin_character(db_session, test_user.id)

    assert upgraded.prompt == XIAOMAO_PROMPT
    assert "小猫只是角落解说员" in upgraded.prompt
    assert "不得替代流程、表格、结构或对比关系" in upgraded.prompt
    assert upgraded.anchor_version == 5


def test_character_mention_rejects_multiple_primary_characters():
    from backend.app.services.wechat_mp_character_service import parse_character_mention

    with pytest.raises(ValueError, match="one primary"):
        parse_character_mention("主角：@小猫生图\n主角：@护士兔")


def test_character_mention_rejects_duplicate_primary_character_lines():
    from backend.app.services.wechat_mp_character_service import parse_character_mention

    with pytest.raises(ValueError, match="one primary"):
        parse_character_mention("主角：@小猫生图\n主角：@小猫生图")


def test_character_mention_backfill_is_idempotent_and_preserves_generated_data(
    api_client, auth_headers, created_wechat_prompt,
):
    from backend.app.models import (
        UsageRecord,
        User,
        WechatMpArticle,
        WechatMpAsset,
        WechatMpImagePrompt,
    )
    from backend.app.services.wechat_mp_character_service import XIAOMAO_PROMPT, ensure_builtin_character
    from backend.app.services.wechat_mp_character_mention_backfill import backfill_character_mentions

    legacy_builtin_prompt = XIAOMAO_PROMPT.replace(
        "轻微抖动的手绘线稿；",
        "轻微抖动的手绘线稿，少量浅橙、红、蓝批注；",
    )
    _, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        character = ensure_builtin_character(session, owner.id)
        article = session.get(WechatMpArticle, created_wechat_prompt.article_id)
        article.cover_brief = f"{XIAOMAO_PROMPT}\n小猫压住计划表"
        article.html_body = "<p>已经插入的正文图片</p>"
        article.cost_estimate = {"currency": "CNY", "total_yuan": "1.2345", "calls": 2}
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        prompt.character_id = character.id + 10_000
        prompt.skill_name = character.skill_name
        wrapped_legacy_prompt = (
            "主角：@小猫生图\n"
            f"具体画面：{legacy_builtin_prompt}\n"
            "图解硬约束：保留流程节点\n"
            "文章：项目管理\n"
            "场景：小猫整理便签"
        )
        prompt.prompt = wrapped_legacy_prompt
        prompt.editable_prompt = wrapped_legacy_prompt
        prompt.cost_estimate = {"currency": "CNY", "total_yuan": "0.1234", "calls": 1}
        asset = WechatMpAsset(
            user_id=owner.id,
            article_id=article.id,
            prompt_id=prompt.id,
            role="inline_illustration",
            file_path="/tmp/generated-before-backfill.png",
            public_url="/api/files/media/generated-before-backfill.png",
            prompt="生成时的完整提示词",
            skill_name=character.skill_name,
            model_name="test-model",
            status="generated",
        )
        usage = UsageRecord(
            user_id=owner.id,
            platform="wechat_mp",
            resource_type="wechat_mp_article",
            resource_id=article.id,
            step="generate_image_prompt",
            model="test-model",
            input_tokens=10,
            output_tokens=20,
        )
        session.add_all((asset, usage))
        session.commit()
        original_public_url = asset.public_url
        original_html = article.html_body
        original_article_cost = article.cost_estimate.copy()
        original_prompt_cost = prompt.cost_estimate.copy()
        original_usage_id = usage.id

        first = backfill_character_mentions(session, user_id=owner.id)
        second = backfill_character_mentions(session, user_id=owner.id)

        assert first == {"articles_updated": 1, "prompts_updated": 1}
        assert second == {"articles_updated": 0, "prompts_updated": 0}
        assert article.cover_brief.startswith("主角：@小猫生图")
        assert prompt.editable_prompt.startswith("主角：@小猫生图")
        assert "主角必须是一只胖胖慵懒" not in prompt.editable_prompt
        assert "图解硬约束：保留流程节点" in prompt.editable_prompt
        assert prompt.prompt == prompt.editable_prompt
        assert session.get(WechatMpAsset, asset.id).public_url == original_public_url
        assert article.html_body == original_html
        assert article.cost_estimate == original_article_cost
        assert prompt.cost_estimate == original_prompt_cost
        assert session.get(UsageRecord, original_usage_id) is not None
    finally:
        session.close()


def test_character_mention_backfill_scoped_owner_skips_cross_owner_prompt(
    api_client, auth_headers, created_wechat_prompt,
):
    from backend.app.models import User, WechatMpArticle, WechatMpImagePrompt
    from backend.app.services.wechat_mp_character_service import XIAOMAO_PROMPT, ensure_builtin_character
    from backend.app.services.wechat_mp_character_mention_backfill import backfill_character_mentions

    _, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        character = ensure_builtin_character(session, owner.id)
        article = session.get(WechatMpArticle, created_wechat_prompt.article_id)
        article.cover_brief = "主角：@小猫生图\n具体画面：小猫压住计划表"
        owner_prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        owner_prompt.character_id = character.id
        owner_prompt.skill_name = character.skill_name
        owner_prompt.prompt = "主角：@小猫生图\n具体画面：小猫整理便签"
        owner_prompt.editable_prompt = owner_prompt.prompt
        foreign_user = User(username="wechat-backfill-foreign", password_hash="unused")
        session.add(foreign_user)
        session.flush()
        foreign_prompt = WechatMpImagePrompt(
            user_id=foreign_user.id,
            article_id=article.id,
            section_id=owner_prompt.section_id,
            skill_name="xiaomao-illustrations",
            prompt=f"{XIAOMAO_PROMPT}\n外部用户的提示词",
            editable_prompt=f"{XIAOMAO_PROMPT}\n外部用户的提示词",
            status="prompt_ready",
        )
        session.add(foreign_prompt)
        session.commit()
        original_foreign_prompt = foreign_prompt.editable_prompt

        result = backfill_character_mentions(session, user_id=owner.id)

        assert result == {"articles_updated": 0, "prompts_updated": 0}
        assert session.get(WechatMpImagePrompt, foreign_prompt.id).prompt == original_foreign_prompt
        assert session.get(WechatMpImagePrompt, foreign_prompt.id).editable_prompt == original_foreign_prompt
    finally:
        session.close()


def test_wechat_writer_shows_hoverable_character_mentions_for_cover_and_inline_prompts():
    source = Path("frontend/src/pages/platforms/wechat-mp/writer-page.tsx").read_text()

    assert "Tooltip" in source
    assert "character.prompt" in source
    assert "主角：@" in source
    assert "replaceCharacterMention" in source
    assert source.count("characterMentionBadge") >= 2


def test_wechat_writer_hides_none_badges_and_persists_confirmed_character_selection():
    source = Path("frontend/src/pages/platforms/wechat-mp/writer-page.tsx").read_text()

    assert 'if (skillName === "none") return null;' in source
    assert 'character_id: character.id' in source
    assert 'skill_name: character.skill_name' in source
    assert "updateWechatMpPrompt(prompt.article_id, prompt.id, {" in source
    assert "character.skill_name !== \"none\"" in source
    assert "value: character.skill_name" in source
    assert "item.skill_name === skillName" in source
    assert "setError(errorMessage(err, `段落 #${prompt.section_id} 图片生成失败，请确认图片模型配置。`))" in source
    assert "四视图已确认" in source
    assert "待确认四视图" in source


def test_wechat_mp_character_page_exposes_custom_archive_action():
    source = Path("frontend/src/pages/platforms/wechat-mp/characters-page.tsx").read_text(encoding="utf-8")
    api_source = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")

    assert "archiveWechatMpIllustrationCharacter" in api_source
    assert "Popconfirm" in source
    assert "DeleteOutlined" in source
    assert "!character.is_builtin" in source
    assert "删除后不再出现在形象库，但历史文章仍保留" in source


def test_wechat_mp_character_page_keeps_list_when_a_preview_fails():
    source = Path("frontend/src/pages/platforms/wechat-mp/characters-page.tsx").read_text(encoding="utf-8")
    api_source = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")

    assert "Promise.allSettled" in source
    assert "部分形象预览加载失败" in source
    assert 'path.startsWith("/api/") ? path.slice(4) : path' in api_source
    assert 'responseType: "blob", _silent: true' in api_source


def test_wechat_mp_character_view_uses_provider_legal_square_size(api_client, auth_headers, monkeypatch):
    from backend.app.services import wechat_mp_character_service as character_service
    from backend.app.services import wechat_mp_image_service as image_service

    client, _ = api_client
    created = client.post(
        "/api/platforms/wechat-mp/illustration-characters",
        json={"name": "尺寸测试角色", "prompt": "固定外观的手绘角色。"},
        headers=auth_headers,
    )
    assert created.status_code == 201

    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {"image_ref": "https://example.com/character.png", "provider_response": {"ok": True}}

    class FakeDownload:
        content = b"generated-character-image"

    monkeypatch.setattr(image_service, "_call_image_model", fake_generate)
    monkeypatch.setattr(character_service.requests, "get", lambda *args, **kwargs: FakeDownload())

    response = client.post(
        f"/api/platforms/wechat-mp/illustration-characters/{created.json()['id']}/views/front/generate",
        params={"image_model": "doubao-seedream-5-0-260128"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert captured["size"] == "2048x2048"


def test_archive_wechat_mp_character_hides_it_and_preserves_historical_views(api_client, auth_headers):
    from backend.app.models import WechatMpCharacterView, WechatMpIllustrationCharacter, User
    from backend.app.services.wechat_mp_character_service import resolve_confirmed_character_anchor

    client, session_factory = api_client
    created = client.post(
        "/api/platforms/wechat-mp/illustration-characters",
        json={"name": "待归档角色", "prompt": "固定外观的手绘角色。"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    character_id = created.json()["id"]

    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        for view in ("front", "back", "left", "right"):
            session.add(WechatMpCharacterView(
                character_id=character_id,
                user_id=owner.id,
                view=view,
                public_url=f"/api/platforms/wechat-mp/illustration-characters/files/{view}.png",
                status="confirmed",
            ))
        session.commit()
    finally:
        session.close()

    archived = client.delete(
        f"/api/platforms/wechat-mp/illustration-characters/{character_id}",
        headers=auth_headers,
    )

    assert archived.status_code == 204
    assert archived.content == b""
    listed = client.get("/api/platforms/wechat-mp/illustration-characters", headers=auth_headers)
    assert all(item["id"] != character_id for item in listed.json())

    session = session_factory()
    try:
        character = session.get(WechatMpIllustrationCharacter, character_id)
        assert character.archived_at is not None
        assert session.query(WechatMpCharacterView).filter_by(character_id=character_id).count() == 4
        resolved, urls = resolve_confirmed_character_anchor(
            session,
            user_id=character.user_id,
            character_id=character_id,
        )
        assert resolved.id == character_id
        assert len(urls) == 4
    finally:
        session.close()

    repeated = client.delete(
        f"/api/platforms/wechat-mp/illustration-characters/{character_id}",
        headers=auth_headers,
    )
    assert repeated.status_code == 404


def test_archive_wechat_mp_character_rejects_builtin_and_other_users(api_client, auth_headers):
    client, _ = api_client
    listed = client.get("/api/platforms/wechat-mp/illustration-characters", headers=auth_headers)
    builtin = next(item for item in listed.json() if item["skill_name"] == "xiaomao-illustrations")

    builtin_response = client.delete(
        f"/api/platforms/wechat-mp/illustration-characters/{builtin['id']}",
        headers=auth_headers,
    )
    assert builtin_response.status_code == 400
    assert "cannot be deleted" in builtin_response.json()["detail"]

    created = client.post(
        "/api/platforms/wechat-mp/illustration-characters",
        json={"name": "私有归档角色", "prompt": "只属于当前用户。"},
        headers=auth_headers,
    )
    other = client.post(
        "/api/auth/register",
        json={"username": "wechat-archive-other", "password": "secret123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    foreign_response = client.delete(
        f"/api/platforms/wechat-mp/illustration-characters/{created.json()['id']}",
        headers=other_headers,
    )
    assert foreign_response.status_code == 404


def test_wechat_mp_image_provider_uses_volc_multi_image_contract(monkeypatch):
    from backend.app.services import wechat_mp_image_service as image_service

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"url": "https://example.com/generated.png"}]}

    def fake_post(*args, **kwargs):
        captured.update(kwargs["json"])
        return FakeResponse()

    monkeypatch.setattr(image_service.requests, "post", fake_post)
    result = image_service._call_image_model(
        prompt="scene", model_name="doubao-seedream-4-5-251128", size="2K",
        base_url="https://ark.example/api/v3", api_key="secret",
        reference_images=["https://example.com/front.png", "https://example.com/back.png"],
    )

    assert result["image_ref"] == "https://example.com/generated.png"
    assert captured["image"] == ["https://example.com/front.png", "https://example.com/back.png"]
    assert captured["sequential_image_generation"] == "disabled"
    assert "reference_images" not in captured


def test_wechat_mp_shotlist_skips_markup_and_click_instruction_flows():
    from backend.app.services.wechat_mp_shotlist_service import choose_candidate_sections

    candidates = choose_candidate_sections(
        "## 章节练习\n\n"
        "<details> → <summary> → 点击查看答案与解析\n\n"
        "需求获取 → 需求分析 → 需求规格说明书编制 → 需求验证与确认"
    )

    assert all("<details>" not in item["source_excerpt"] for item in candidates)
    assert candidates[0]["source_excerpt"] == "需求获取 → 需求分析 → 需求规格说明书编制 → 需求验证与确认"
    assert choose_candidate_sections(
        "<details> → <summary> → 点击查看答案与解析"
    ) == []


def test_regenerating_prompts_removes_obsolete_markup_prompt_from_article(
    api_client, auth_headers, created_wechat_article, monkeypatch
):
    from backend.app.models import WechatMpArticleSection, WechatMpAsset, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    client, session_factory = api_client
    session = session_factory()
    try:
        article = session.get(type(created_wechat_article), created_wechat_article.id)
        stale_section = WechatMpArticleSection(
            user_id=article.user_id,
            article_id=article.id,
            section_index=1,
            summary="图解类型：流程图\n必须准确呈现节点：<details> -> <summary> -> 点击查看答案与解析",
            source_excerpt="<details> → <summary> → 点击查看答案与解析",
            needs_image=True,
        )
        session.add(stale_section)
        session.flush()
        stale_prompt = WechatMpImagePrompt(
            user_id=article.user_id,
            article_id=article.id,
            section_id=stale_section.id,
            skill_name="xiaomao-illustrations",
            prompt="画出 details 和 summary",
            editable_prompt="画出 details 和 summary",
            status="generated",
        )
        session.add(stale_prompt)
        session.flush()
        stale_asset = WechatMpAsset(
            user_id=article.user_id,
            article_id=article.id,
            prompt_id=stale_prompt.id,
            role="inline_illustration",
            file_path="/tmp/stale-markup.png",
            public_url="/api/files/media/stale-markup.png",
            prompt=stale_prompt.editable_prompt,
            skill_name=stale_prompt.skill_name,
            model_name="test-image-model",
            status="generated",
        )
        session.add(stale_asset)
        article.markdown_body = "需求获取 → 需求分析 → 需求规格说明书编制 → 需求验证与确认"
        article.html_body = '<p>正文</p><img src="/api/files/media/stale-markup.png" alt="无效配图" />'
        article.status = "prompts_ready"
        session.commit()
        stale_section_id = stale_section.id
        stale_asset_id = stale_asset.id
    finally:
        session.close()

    monkeypatch.setattr(
        prompt_service,
        "_call_prompt_model",
        lambda **kwargs: {
            "prompt": "画出真实需求流程",
            "input_tokens": 12,
            "output_tokens": 24,
            "model_name": kwargs["model_name"],
        },
    )
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts",
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert len(response.json()) == 1
    assert response.json()[0]["editable_prompt"] != "画出 details 和 summary"
    article_data = client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}", headers=auth_headers
    ).json()
    assert "/api/files/media/stale-markup.png" not in article_data["html_body"]
    session = session_factory()
    try:
        assert session.get(WechatMpArticleSection, stale_section_id) is None
        assert session.query(WechatMpImagePrompt).filter_by(article_id=created_wechat_article.id).count() == 1
        assert session.get(WechatMpAsset, stale_asset_id).prompt_id is None
    finally:
        session.close()


def test_regenerate_prompt_passes_character_context_and_keeps_mention(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    client, _ = api_client
    captured = {}

    def fake_prompt_call(**kwargs):
        captured.update(kwargs)
        return {
            "prompt": "主角：@小猫生图\n具体画面：小猫把计划表压在爪下",
            "input_tokens": 15,
            "output_tokens": 30,
            "model_name": kwargs["model_name"],
        }

    monkeypatch.setattr(prompt_service, "_call_prompt_model", fake_prompt_call)
    created = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts",
        headers=auth_headers,
    )
    assert created.status_code == 201
    prompt_id = created.json()[0]["id"]
    captured.clear()
    regenerated = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts/{prompt_id}/regenerate",
        headers=auth_headers,
    )

    assert regenerated.status_code == 200
    assert captured["db"] is not None
    assert captured["user_id"] == created_wechat_article.user_id
    assert regenerated.json()["editable_prompt"].startswith("主角：@小猫生图\n具体画面：")


def test_cover_uses_character_anchor_and_expands_mentions_at_image_boundary(
    api_client, auth_headers, created_wechat_prompt, monkeypatch,
):
    from backend.app.models import (
        User,
        WechatMpArticle,
        WechatMpAsset,
        WechatMpCharacterView,
        WechatMpImagePrompt,
    )
    from backend.app.services import wechat_mp_image_service as image_service
    from backend.app.services.wechat_mp_character_service import ensure_builtin_character

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        character = ensure_builtin_character(session, owner.id)
        for view in ("front", "back", "left", "right"):
            session.add(WechatMpCharacterView(
                character_id=character.id,
                user_id=owner.id,
                view=view,
                public_url=f"/api/platforms/wechat-mp/illustration-characters/files/{view}.png",
                status="confirmed",
            ))
        article = session.get(WechatMpArticle, created_wechat_prompt.article_id)
        article.title = "软考高项·第9章 项目范围管理"
        article.cover_brief = "主角：@小猫生图\n具体画面：项目范围管理核心考点速记指南"
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        prompt.prompt = (
            "主角：@小猫生图\n具体画面：# | 过程 | 过程组\n"
            "1 | 规划范围管理 | 规划\n2 | 收集需求 | 规划\n"
            "3 | 定义范围 | 规划\n4 | 创建WBS | 规划"
        )
        prompt.editable_prompt = prompt.prompt
        session.commit()
    finally:
        session.close()

    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {
            "file_path": "/tmp/wechat-character-mention.png",
            "public_url": "/api/files/media/wechat-character-mention.png",
            "provider_response": {"ok": True},
        }

    monkeypatch.setattr(image_service, "_call_image_model", fake_generate)
    inline = client.post(
        f"/api/platforms/wechat-mp/prompts/{created_wechat_prompt.id}/image",
        json={"image_model": "doubao-seedream-4-0-250828", "size": "16:9"},
        headers=auth_headers,
    )

    assert inline.status_code == 201
    assert "主角：@小猫生图" not in captured["prompt"]
    assert "主角必须是一只胖胖慵懒" in captured["prompt"]
    assert "具体画面：" in captured["prompt"]
    assert "四张参考图属于同一只角色的不同视角" in captured["prompt"]
    assert "成图只能出现 1 只主角" in captured["prompt"]
    assert "不得复制、分身或在每个节点重复放置主角" in captured["prompt"]
    assert "知识内容和信息结构必须占画面 80-90%" in captured["prompt"]
    assert "主角只是角落解说员，只占画面 10-20%" in captured["prompt"]
    assert "不得替代流程节点、表格单元、结构框或对比关系" in captured["prompt"]
    assert "固定顺序：1 -> 2 -> 3 -> 4" in captured["prompt"]
    assert "不得交换、合并、省略或新增节点" in captured["prompt"]
    assert len(captured["reference_images"]) == 4
    session = session_factory()
    try:
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        asset = session.query(WechatMpAsset).filter_by(prompt_id=prompt.id).one()
        assert prompt.editable_prompt.startswith("主角：@小猫生图\n具体画面：")
        assert asset.prompt == captured["prompt"]
    finally:
        session.close()

    captured.clear()
    cover = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}/cover",
        json={"image_model": "doubao-seedream-4-0-250828", "size": "16:9"},
        headers=auth_headers,
    )

    assert cover.status_code == 201
    assert "主角：@小猫生图" not in captured["prompt"]
    assert "主角必须是一只胖胖慵懒" in captured["prompt"]
    assert "封面主题：软考高项·第9章 项目范围管理" in captured["prompt"]
    assert "主题结构占画面 80-90%" in captured["prompt"]
    assert "角色只占画面 10-20%" in captured["prompt"]
    assert "不得只画角色" in captured["prompt"]
    assert "严格继承参考图中的轮廓、黑白橙配色及橙斑位置" in captured["prompt"]
    assert "四张参考图属于同一只角色的不同视角" in captured["prompt"]
    assert "成图只能出现 1 只主角" in captured["prompt"]
    assert captured["prompt"].index("封面主题：") < captured["prompt"].index("主角必须是一只胖胖慵懒")
    assert len(captured["reference_images"]) == 4
    session = session_factory()
    try:
        article = session.get(WechatMpArticle, created_wechat_prompt.article_id)
        asset = session.query(WechatMpAsset).filter_by(article_id=article.id, role="cover").one()
        assert article.cover_brief == "主角：@小猫生图\n具体画面：项目范围管理核心考点速记指南"
        assert asset.prompt == captured["prompt"]
    finally:
        session.close()


def test_wechat_mp_adapter_routes_only_wechat_requests_through_configured_proxy(monkeypatch):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiAdapter

    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"access_token": "token-value", "expires_in": 7200}

    def fake_get(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("requests.get", fake_get)

    WechatMpApiAdapter(proxy_url="http://proxy-user:proxy-pass@203.0.113.10:3128").get_access_token(
        app_id="wx123",
        app_secret="secret-value",
    )

    assert captured["url"].startswith("https://api.weixin.qq.com/")
    assert captured["proxies"] == {
        "http": "http://proxy-user:proxy-pass@203.0.113.10:3128",
        "https": "http://proxy-user:proxy-pass@203.0.113.10:3128",
    }


def test_update_prompt_rejects_embedded_or_duplicate_character_mentions(
    api_client, auth_headers, created_wechat_prompt,
):
    client, _ = api_client

    response = client.patch(
        f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}/prompts/{created_wechat_prompt.id}",
        json={"editable_prompt": "主角：@小猫生图\n具体画面：小猫整理便签，主角：@护士兔"},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "mention" in response.json()["detail"].lower()


def test_update_prompt_switches_confirmed_character_and_image_keeps_selection(
    api_client, auth_headers, created_wechat_prompt, monkeypatch,
):
    from backend.app.models import User, WechatMpCharacterView, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_service as image_service
    from backend.app.services.wechat_mp_character_service import ensure_builtin_character

    client, session_factory = api_client
    custom_response = client.post(
        "/api/platforms/wechat-mp/illustration-characters",
        json={"name": "确认白熊", "prompt": "白熊角色契约，蓝围巾，固定四视图。"},
        headers=auth_headers,
    )
    assert custom_response.status_code == 201
    custom = custom_response.json()

    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        builtin = ensure_builtin_character(session, owner.id)
        for character in (builtin, session.get(type(builtin), custom["id"])):
            for view in ("front", "back", "left", "right"):
                session.add(WechatMpCharacterView(
                    character_id=character.id,
                    user_id=owner.id,
                    view=view,
                    public_url=f"/api/platforms/wechat-mp/illustration-characters/files/{character.id}-{view}.png",
                    status="confirmed",
                ))
        session.commit()
        builtin_id = builtin.id
    finally:
        session.close()

    prompt_url = f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}/prompts/{created_wechat_prompt.id}"
    builtin_update = client.patch(
        prompt_url,
        json={
            "editable_prompt": "主角：@小猫生图\n具体画面：小猫整理便签",
            "character_id": builtin_id,
            "skill_name": "xiaomao-illustrations",
        },
        headers=auth_headers,
    )
    assert builtin_update.status_code == 200
    assert builtin_update.json()["character_id"] == builtin_id
    assert builtin_update.json()["skill_name"] == "xiaomao-illustrations"
    assert builtin_update.json()["editable_prompt"].startswith("主角：@小猫生图\n")

    custom_update = client.patch(
        prompt_url,
        json={
            "editable_prompt": "主角：@确认白熊\n具体画面：白熊指向流程图",
            "character_id": custom["id"],
            "skill_name": custom["skill_name"],
        },
        headers=auth_headers,
    )
    assert custom_update.status_code == 200
    assert custom_update.json()["character_id"] == custom["id"]
    assert custom_update.json()["skill_name"] == custom["skill_name"]
    assert custom_update.json()["editable_prompt"].startswith("主角：@确认白熊\n")

    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {
            "file_path": "/tmp/confirmed-character.png",
            "public_url": "/api/files/media/confirmed-character.png",
            "provider_response": {"ok": True},
        }

    monkeypatch.setattr(image_service, "_call_image_model", fake_generate)
    generated = client.post(
        f"/api/platforms/wechat-mp/prompts/{created_wechat_prompt.id}/image",
        json={"image_model": "doubao-seedream-4-0-250828", "size": "16:9"},
        headers=auth_headers,
    )

    assert generated.status_code == 201
    assert "主角：@确认白熊" not in captured["prompt"]
    assert "白熊角色契约" in captured["prompt"]
    assert len(captured["reference_images"]) == 4
    session = session_factory()
    try:
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        assert prompt.character_id == custom["id"]
        assert prompt.skill_name == custom["skill_name"]
    finally:
        session.close()


def test_update_prompt_rejects_unconfirmed_or_foreign_character(
    api_client, auth_headers, created_wechat_prompt,
):
    client, _ = api_client
    unconfirmed = client.post(
        "/api/platforms/wechat-mp/illustration-characters",
        json={"name": "未确认角色", "prompt": "尚未确认四视图。"},
        headers=auth_headers,
    ).json()
    prompt_url = f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}/prompts/{created_wechat_prompt.id}"

    unconfirmed_response = client.patch(
        prompt_url,
        json={
            "editable_prompt": "主角：@未确认角色\n具体画面：测试",
            "character_id": unconfirmed["id"],
            "skill_name": unconfirmed["skill_name"],
        },
        headers=auth_headers,
    )
    assert unconfirmed_response.status_code == 400
    assert "confirmed" in unconfirmed_response.json()["detail"].lower()

    other = client.post("/api/auth/register", json={"username": "prompt-character-other", "password": "secret123"})
    foreign = client.post(
        "/api/platforms/wechat-mp/illustration-characters",
        json={"name": "他人角色", "prompt": "他人的角色契约。"},
        headers={"Authorization": f"Bearer {other.json()['access_token']}"},
    ).json()
    foreign_response = client.patch(
        prompt_url,
        json={
            "editable_prompt": "主角：@他人角色\n具体画面：测试",
            "character_id": foreign["id"],
            "skill_name": foreign["skill_name"],
        },
        headers=auth_headers,
    )
    assert foreign_response.status_code == 400


def test_same_name_characters_keep_selected_identity_and_reject_ambiguous_mentions(
    api_client, auth_headers, created_wechat_prompt, monkeypatch,
):
    from backend.app.models import User, WechatMpCharacterView, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_service as image_service
    from backend.app.services.wechat_mp_character_service import resolve_prompt_character

    client, session_factory = api_client
    characters = []
    for prompt in ("同名角色一号契约。", "同名角色二号契约。"):
        response = client.post(
            "/api/platforms/wechat-mp/illustration-characters",
            json={"name": "同名角色", "prompt": prompt},
            headers=auth_headers,
        )
        assert response.status_code == 201
        characters.append(response.json())

    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        for character in characters:
            for view in ("front", "back", "left", "right"):
                session.add(WechatMpCharacterView(
                    character_id=character["id"],
                    user_id=owner.id,
                    view=view,
                    public_url=f"/api/platforms/wechat-mp/illustration-characters/files/{character['id']}-{view}.png",
                    status="confirmed",
                ))
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        prompt.editable_prompt = "主角：@同名角色\n具体画面：自由输入的同名角色"
        prompt.character_id = None
        session.commit()
    finally:
        session.close()

    session = session_factory()
    try:
        with pytest.raises(ValueError, match="Ambiguous character mention"):
            resolve_prompt_character(
                session,
                user_id=created_wechat_prompt.user_id,
                default_skill_name="xiaomao-illustrations",
                text="主角：@同名角色\n具体画面：自由输入的同名角色",
            )
    finally:
        session.close()

    selected = characters[1]
    prompt_url = f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}/prompts/{created_wechat_prompt.id}"
    patched = client.patch(
        prompt_url,
        json={
            "editable_prompt": "主角：@同名角色\n具体画面：明确选择第二个角色",
            "character_id": selected["id"],
            "skill_name": selected["skill_name"],
        },
        headers=auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["character_id"] == selected["id"]
    assert patched.json()["skill_name"] == selected["skill_name"]

    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {
            "file_path": "/tmp/same-name-character.png",
            "public_url": "/api/files/media/same-name-character.png",
            "provider_response": {"ok": True},
        }

    monkeypatch.setattr(image_service, "_call_image_model", fake_generate)
    generated = client.post(
        f"/api/platforms/wechat-mp/prompts/{created_wechat_prompt.id}/image",
        json={"image_model": "doubao-seedream-4-0-250828", "size": "16:9"},
        headers=auth_headers,
    )
    assert generated.status_code == 201
    assert "同名角色二号契约" in captured["prompt"]
    assert "同名角色一号契约" not in captured["prompt"]
    session = session_factory()
    try:
        prompt = session.get(WechatMpImagePrompt, created_wechat_prompt.id)
        assert prompt.character_id == selected["id"]
        assert prompt.skill_name == selected["skill_name"]
    finally:
        session.close()


def test_cover_generation_uses_article_skill_to_disambiguate_same_name_characters(
    api_client, auth_headers, created_wechat_prompt, monkeypatch,
):
    from backend.app.models import WechatMpArticle, WechatMpCharacterView
    from backend.app.services import wechat_mp_image_service as image_service

    client, session_factory = api_client
    characters = []
    for prompt in ("封面同名角色一号契约。", "封面同名角色二号契约。"):
        response = client.post(
            "/api/platforms/wechat-mp/illustration-characters",
            json={"name": "封面同名角色", "prompt": prompt},
            headers=auth_headers,
        )
        assert response.status_code == 201
        characters.append(response.json())

    selected = characters[1]
    session = session_factory()
    try:
        for character in characters:
            for view in ("front", "back", "left", "right"):
                session.add(WechatMpCharacterView(
                    character_id=character["id"],
                    user_id=created_wechat_prompt.user_id,
                    view=view,
                    public_url=f"/api/platforms/wechat-mp/illustration-characters/files/{character['id']}-{view}.png",
                    status="confirmed",
                ))
        article = session.get(WechatMpArticle, created_wechat_prompt.article_id)
        article.illustration_skill = selected["skill_name"]
        article.cover_brief = "主角：@封面同名角色\n具体画面：角色压住文章标题"
        session.commit()
    finally:
        session.close()

    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {
            "file_path": "/tmp/same-name-cover.png",
            "public_url": "/api/files/media/same-name-cover.png",
            "provider_response": {"ok": True},
        }

    monkeypatch.setattr(image_service, "_call_image_model", fake_generate)
    generated = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_prompt.article_id}/cover",
        json={"image_model": "doubao-seedream-4-0-250828", "size": "16:9"},
        headers=auth_headers,
    )

    assert generated.status_code == 201
    assert "封面同名角色二号契约" in captured["prompt"]
    assert "封面同名角色一号契约" not in captured["prompt"]
    assert len(captured["reference_images"]) == 4


def test_unknown_illustration_skill_is_rejected_before_creating_article(api_client, auth_headers, monkeypatch):
    from backend.app.models import WechatMpArticle
    from backend.app.services import wechat_mp_writer_service as writer

    calls = []

    def fake_writer(**kwargs):
        calls.append(kwargs)
        return {
            "title": "不应创建",
            "markdown_body": "正文",
            "digest": "摘要",
            "cover_brief": "封面",
            "input_tokens": 1,
            "output_tokens": 1,
            "model_name": kwargs["model_name"],
        }

    monkeypatch.setattr(writer, "_call_writer_model", fake_writer)
    client, session_factory = api_client
    response = client.post(
        "/api/platforms/wechat-mp/articles",
        json={"title": "非法技能", "topic": "非法技能", "illustration_skill": "missing-skill"},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "illustration skill" in response.json()["detail"].lower()
    assert calls == []
    session = session_factory()
    try:
        assert session.query(WechatMpArticle).filter_by(title="不应创建").count() == 0
    finally:
        session.close()


def test_unknown_illustration_skill_is_rejected_before_generating_prompts(
    api_client, auth_headers, created_wechat_article, monkeypatch,
):
    from backend.app.models import WechatMpArticle, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    calls = []
    monkeypatch.setattr(
        prompt_service,
        "generate_article_shotlist",
        lambda **kwargs: calls.append(kwargs) or [],
    )
    client, session_factory = api_client
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts",
        json={"skill_name": "missing-skill"},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "illustration skill" in response.json()["detail"].lower()
    assert calls == []
    session = session_factory()
    try:
        article = session.get(WechatMpArticle, created_wechat_article.id)
        assert article.illustration_skill == "xiaomao-illustrations"
        assert session.query(WechatMpImagePrompt).filter_by(article_id=article.id).count() == 0
    finally:
        session.close()


def test_article_update_rejects_unknown_illustration_skill(api_client, auth_headers, created_wechat_article):
    client, _ = api_client
    response = client.patch(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}",
        json={"illustration_skill": "missing-skill"},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "illustration skill" in response.json()["detail"].lower()
    current = client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}",
        headers=auth_headers,
    )
    assert current.status_code == 200
    assert current.json()["illustration_skill"] == "xiaomao-illustrations"


def test_wechat_mp_character_images_are_persisted_outside_the_container():
    compose_source = Path("docker-compose.yml").read_text()

    assert (
        "./backend/app/storage/character-images:"
        "/app/backend/app/storage/character-images"
    ) in compose_source


def test_content_analysis_accepts_pipe_table_without_markdown_divider():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content

    body = """对比项 | 确认范围 | 质量控制
关注点 | 可交付成果获得客户接受 | 可交付成果的准确性和质量要求
执行方 | 外部干系人检查验收 | 内部质量部门实施
时机 | 一般在阶段末尾 | 不一定在阶段末
关系 | — | 质量控制一般在确认范围前进行"""

    analysis = analyze_content(body)

    assert len(analysis.candidates) == 1
    assert analysis.candidates[0].kind == "table"
    assert analysis.candidates[0].structure[0] == ("对比项", "确认范围", "质量控制")
    assert analysis.candidates[0].structure[-1] == ("关系", "—", "质量控制一般在确认范围前进行")


def test_visual_plan_extracts_comparison_relation_before_image_generation():
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content
    from backend.app.services.wechat_mp_visual_plan_service import build_visual_plan, validate_visual_plan

    body = """| 对比项 | 确认范围 | 质量控制 |
|---|---|---|
| 关注点 | 客户接受 | 准确性和质量 |
| 执行方 | 外部干系人 | 内部质量部门 |
| 时机 | 阶段末 | 不一定在阶段末 |
| 关系 | — | 质量控制在确认范围前进行 |"""
    candidate = analyze_content(body).candidates[0]

    plan = build_visual_plan(candidate)
    report = validate_visual_plan(candidate, plan)

    assert plan["kind"] == "comparison"
    assert plan["columns"] == ["确认范围", "质量控制"]
    assert plan["relations"] == [{"from": "质量控制", "to": "确认范围", "label": "先质检，再验收"}]
    assert report["valid"] is True
    assert report["source_coverage"] is True
    assert report["single_character"] is True


def test_visual_plan_compiler_version_invalidates_legacy_prompt_fingerprints():
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    assert prompt_service._SKILL_VERSION == "v1.2.0"
    assert prompt_service._fingerprint_skill_version("xiaomao-illustrations") == "xiaomao-illustrations:v1.2.0"


def test_regenerate_structural_prompt_persists_visual_plan(db_session, test_user):
    from backend.app.models import WechatMpArticle, WechatMpArticleSection, WechatMpImagePrompt
    from backend.app.services.wechat_mp_image_prompt_service import regenerate_image_prompt

    article = WechatMpArticle(
        user_id=test_user.id,
        title="确认范围",
        markdown_body="""| 对比项 | 确认范围 | 质量控制 |
|---|---|---|
| 关系 | — | 质量控制在确认范围前进行 |""",
        html_body="<p>正文</p>",
        status="images_ready",
        illustration_skill="none",
    )
    db_session.add(article)
    db_session.flush()
    section = WechatMpArticleSection(
        user_id=test_user.id,
        article_id=article.id,
        section_index=0,
        source_excerpt=article.markdown_body,
        source_fingerprint="",
        summary="对比",
    )
    db_session.add(section)
    db_session.flush()
    prompt = WechatMpImagePrompt(
        user_id=test_user.id,
        article_id=article.id,
        section_id=section.id,
        skill_name="none",
        prompt="旧提示词",
        editable_prompt="旧提示词",
    )
    db_session.add(prompt)
    db_session.commit()

    # Backfill the stable fingerprint used to locate the current candidate.
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content
    section.source_fingerprint = analyze_content(article.markdown_body).candidates[0].fingerprint
    db_session.commit()
    regenerated = regenerate_image_prompt(db=db_session, prompt=prompt, article=article)

    assert regenerated.visual_plan["kind"] == "comparison"
    assert regenerated.quality_report["valid"] is True


def test_prompt_ignore_signature_matches_same_knowledge_structure_not_generic_topic():
    from backend.app.services.wechat_mp_prompt_ignore_service import build_concept_signature, concept_similarity

    ignored = build_concept_signature("规划→收集→定义→WBS→确认→控制", "flow")
    duplicate = build_concept_signature(
        "范围管理六过程 | 规划 | 收集 | 定义 | WBS | 确认 | 控制",
        "table",
    )
    unrelated = build_concept_signature("规划范围时需要识别风险并制定沟通计划", "semantic")

    assert concept_similarity(ignored, duplicate) >= 0.78
    assert concept_similarity(ignored, unrelated) < 0.78


def test_prompt_ignore_rule_is_user_scoped_and_keeps_generated_asset(db_session, test_user):
    from backend.app.models import User, WechatMpArticle, WechatMpArticleSection, WechatMpAsset, WechatMpImagePrompt
    from backend.app.services.wechat_mp_content_analysis_service import analyze_content
    from backend.app.services.wechat_mp_prompt_ignore_service import (
        filter_ignored_candidates,
        ignore_prompt,
        restore_prompt,
    )

    other_user = User(username="other-wechat-user", password_hash="unused")
    article = WechatMpArticle(
        user_id=test_user.id,
        title="范围管理",
        markdown_body="规划→收集→定义→WBS→确认→控制",
        html_body='<p>正文</p>{{image:prompt-1}}<img src="/api/files/media/history.png" alt="配图" />',
        status="prompts_ready",
    )
    db_session.add_all([other_user, article])
    db_session.flush()
    section = WechatMpArticleSection(
        user_id=test_user.id,
        article_id=article.id,
        section_index=0,
        summary="范围管理六过程",
        source_excerpt="规划→收集→定义→WBS→确认→控制",
    )
    db_session.add(section)
    db_session.flush()
    prompt = WechatMpImagePrompt(
        user_id=test_user.id,
        article_id=article.id,
        section_id=section.id,
        prompt="主角：@小猫生图\n具体画面：规划→收集→定义→WBS→确认→控制",
        editable_prompt="主角：@小猫生图\n具体画面：规划→收集→定义→WBS→确认→控制",
        visual_plan={"kind": "flow"},
        quality_report={"valid": True},
    )
    db_session.add(prompt)
    db_session.flush()
    article.html_body = article.html_body.replace("prompt-1", f"prompt-{prompt.id}")
    asset = WechatMpAsset(
        user_id=test_user.id,
        article_id=article.id,
        prompt_id=prompt.id,
        role="inline_illustration",
        file_path="/tmp/history.png",
        public_url="/api/files/media/history.png",
        prompt=prompt.prompt,
        skill_name="xiaomao-illustrations",
        model_name="test-image",
    )
    db_session.add(asset)
    db_session.commit()

    ignored = ignore_prompt(
        db_session,
        user_id=test_user.id,
        article_id=article.id,
        prompt_id=prompt.id,
        future_similar=True,
    )
    candidate = analyze_content("规划→收集→定义→WBS→确认→控制").candidates
    owner_kept, owner_matches = filter_ignored_candidates(db_session, user_id=test_user.id, candidates=candidate)
    other_kept, other_matches = filter_ignored_candidates(db_session, user_id=other_user.id, candidates=candidate)

    assert ignored.status == "ignored"
    assert f"{{{{image:prompt-{prompt.id}}}}}" not in article.html_body
    assert "/api/files/media/history.png" not in article.html_body
    assert db_session.get(WechatMpAsset, asset.id) is not None
    assert owner_kept == () and owner_matches
    assert other_kept == candidate and other_matches == {}

    restored = restore_prompt(
        db_session,
        user_id=test_user.id,
        article_id=article.id,
        prompt_id=prompt.id,
    )
    assert restored.status == "prompt_ready"
    assert f"{{{{image:prompt-{prompt.id}}}}}" in article.html_body


def test_prompt_ignore_api_exposes_rule_and_restore(api_client, auth_headers):
    from backend.app.models import User, WechatMpArticle, WechatMpArticleSection, WechatMpImagePrompt

    client, session_factory = api_client
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        article = WechatMpArticle(
            user_id=owner.id,
            title="忽略测试",
            markdown_body="规划→收集→定义→确认",
            html_body="<p>正文</p>",
            status="prompts_ready",
        )
        session.add(article)
        session.flush()
        section = WechatMpArticleSection(
            user_id=owner.id,
            article_id=article.id,
            section_index=0,
            summary="流程",
            source_excerpt="规划→收集→定义→确认",
        )
        session.add(section)
        session.flush()
        prompt = WechatMpImagePrompt(
            user_id=owner.id,
            article_id=article.id,
            section_id=section.id,
            prompt="具体画面：规划→收集→定义→确认",
            editable_prompt="具体画面：规划→收集→定义→确认",
            visual_plan={"kind": "flow"},
            quality_report={"valid": True},
        )
        session.add(prompt)
        session.flush()
        article.html_body += f"{{{{image:prompt-{prompt.id}}}}}"
        session.commit()
        article_id = article.id
        prompt_id = prompt.id
    finally:
        session.close()

    ignored = client.post(
        f"/api/platforms/wechat-mp/articles/{article_id}/prompts/{prompt_id}/ignore",
        json={"scope": "future_similar"},
        headers=auth_headers,
    )
    rules = client.get("/api/platforms/wechat-mp/prompt-ignore-rules", headers=auth_headers)
    restored = client.post(
        f"/api/platforms/wechat-mp/articles/{article_id}/prompts/{prompt_id}/restore",
        headers=auth_headers,
    )

    assert ignored.status_code == 200 and ignored.json()["status"] == "ignored"
    assert rules.status_code == 200 and len(rules.json()) == 1
    assert restored.status_code == 200 and restored.json()["status"] == "prompt_ready"

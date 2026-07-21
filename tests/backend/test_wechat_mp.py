import importlib.util
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.user import User


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
            markdown_body="## 问题\n总在计划开始时消耗精力。\n\n## 方法\n先做最小动作。",
            html_body="<h2>问题</h2><p>总在计划开始时消耗精力。</p><h2>方法</h2><p>先做最小动作。</p>",
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

    session = session_factory()
    try:
        account = session.get(WechatMpAccount, response.json()["id"])
        account.token_cache = {"access_token": "cached-token", "expires_at": time.time() + 3600}
        session.commit()
    finally:
        session.close()
    return type("WechatMpAccountFixture", (), {"id": response.json()["id"]})()


@pytest.fixture
def created_wechat_article_with_image(api_client, auth_headers, created_wechat_article, tmp_path):
    _, session_factory = api_client
    from backend.app.models import User, WechatMpAsset

    image_path = tmp_path / "wechat-inline.png"
    image_path.write_bytes(b"fake-image")
    session = session_factory()
    try:
        owner = session.query(User).filter_by(username="wechat-owner").one()
        cover = WechatMpAsset(
            user_id=owner.id,
            article_id=created_wechat_article.id,
            role="cover",
            file_path=str(image_path),
            public_url="/api/files/media/wechat-cover.png",
            prompt="测试封面",
            skill_name="xiaomao-illustrations",
            model_name="test-model",
            status="generated",
        )
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
        session.add(cover)
        session.add(asset)
        session.commit()
        return created_wechat_article
    finally:
        session.close()


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


def test_publish_routes_hide_foreign_article_and_map_api_failure_to_502(api_client, auth_headers, synced_wechat_article, monkeypatch):
    from backend.app.adapters.wechat_mp.api_adapter import WechatMpApiError
    from backend.app.services import wechat_mp_publish_service as publish_service

    class FailingAdapter:
        def submit_publish(self, **kwargs):
            raise WechatMpApiError("wechat publish submit failed", errcode=40001, payload={"errcode": 40001})

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
        "_call_prompt_model",
        lambda **kwargs: {"prompt": "一只小猫开始最小动作", "input_tokens": 12, "output_tokens": 24, "model_name": kwargs["model_name"]},
    )

    def fake_generate(*, prompt, model_name, size):
        assert prompt == "一只小猫开始最小动作"
        assert model_name == "doubao-seedream-4-0-250828"
        assert size == "16:9"
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
    prompts = prompts_response.json()
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
        assert stored.token_cache["access_token"] == "token-value"
        assert stored.token_cache["expires_in"] == 7200
        assert time.time() + 7100 < stored.token_cache["expires_at"] < time.time() + 7200
    finally:
        session.close()


def test_create_wechat_mp_article_generates_markdown_html_and_usage(api_client, auth_headers, monkeypatch):
    from backend.app.models import UsageRecord
    from backend.app.services import wechat_mp_writer_service as writer

    def fake_call(*, topic, source_material, target_reader, tone, model_name):
        return {
            "title": "会偷懒的人，反而更稳定",
            "markdown_body": "## 开头\n正文第一段\n\n## 方法\n正文第二段",
            "digest": "一篇关于稳定输出的文章",
            "cover_brief": "小猫压住一张计划表",
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

    session = session_factory()
    try:
        assert session.query(UsageRecord).filter_by(platform="wechat_mp", step="write_article").count() == 1
    finally:
        session.close()


def test_generate_prompts_defaults_to_xiaomao_skill(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    def fake_prompt_call(*, article_title, section_summary, skill_name, model_name):
        assert skill_name == "xiaomao-illustrations"
        return {
            "prompt": "Generate one 16:9 Chinese article illustration. 小猫 lazily presses a messy note stack.",
            "input_tokens": 50,
            "output_tokens": 80,
            "model_name": model_name,
        }

    monkeypatch.setattr(prompt_service, "_call_prompt_model", fake_prompt_call)
    client, _ = api_client
    response = client.post(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts",
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data[0]["skill_name"] == "xiaomao-illustrations"
    assert "小猫" in data[0]["prompt"]
    assert data[0]["status"] == "prompt_ready"
    assert data[0]["version"] == 1
    assert data[0]["editable_prompt"] == data[0]["prompt"]


def test_generate_prompts_creates_shotlist_and_records_article_usage(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.models import UsageRecord
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    monkeypatch.setattr(
        prompt_service,
        "_call_prompt_model",
        lambda **kwargs: {"prompt": "一只小猫整理便签", "input_tokens": 12, "output_tokens": 24, "model_name": kwargs["model_name"]},
    )
    client, session_factory = api_client
    response = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)

    assert response.status_code == 201
    assert 1 <= len(response.json()) <= 8
    session = session_factory()
    try:
        usages = session.query(UsageRecord).filter_by(step="generate_image_prompt").all()
        assert len(usages) == len(response.json())
        assert all(usage.platform == "wechat_mp" for usage in usages)
        assert all(usage.resource_type == "wechat_mp_article" for usage in usages)
        assert all(usage.resource_id == created_wechat_article.id for usage in usages)
    finally:
        session.close()


def test_generating_prompts_twice_reuses_prompts_and_placeholders(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.models import WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    monkeypatch.setattr(
        prompt_service,
        "_call_prompt_model",
        lambda **kwargs: {"prompt": f"提示词：{kwargs['section_summary']}", "input_tokens": 12, "output_tokens": 24, "model_name": kwargs["model_name"]},
    )
    client, session_factory = api_client

    first = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)
    second = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert [prompt["id"] for prompt in second.json()] == [prompt["id"] for prompt in first.json()]
    html_body = client.get(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}", headers=auth_headers).json()["html_body"]
    assert all(html_body.count(f"{{{{image:prompt-{prompt['id']}}}}}") == 1 for prompt in second.json())
    session = session_factory()
    try:
        assert session.query(WechatMpImagePrompt).filter_by(article_id=created_wechat_article.id).count() == len(first.json())
    finally:
        session.close()


def test_regenerating_embedded_prompt_restores_marker_for_next_image(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.models import WechatMpAsset
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service
    from backend.app.services import wechat_mp_image_service as image_service

    monkeypatch.setattr(
        prompt_service,
        "_call_prompt_model",
        lambda **kwargs: {"prompt": "第一版提示词", "input_tokens": 12, "output_tokens": 24, "model_name": kwargs["model_name"]},
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
    prompt_id = created.json()[0]["id"]

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


def test_generate_prompts_rolls_back_all_records_when_a_later_model_call_fails(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.models import UsageRecord, WechatMpArticleSection, WechatMpImagePrompt
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    calls = 0

    def fake_prompt_call(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("prompt provider failed")
        return {"prompt": "一只小猫整理便签", "input_tokens": 12, "output_tokens": 24, "model_name": kwargs["model_name"]}

    monkeypatch.setattr(prompt_service, "_call_prompt_model", fake_prompt_call)
    client, session_factory = api_client
    response = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)

    assert response.status_code == 502
    session = session_factory()
    try:
        assert session.query(WechatMpArticleSection).filter_by(article_id=created_wechat_article.id).count() == 0
        assert session.query(WechatMpImagePrompt).filter_by(article_id=created_wechat_article.id).count() == 0
        assert session.query(UsageRecord).filter_by(resource_id=created_wechat_article.id, step="generate_image_prompt").count() == 0
    finally:
        session.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": [{"message": {"content": None}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        {"choices": [{"message": {"content": "一只小猫整理便签"}}], "usage": {"prompt_tokens": None, "completion_tokens": 1}},
        {"choices": [{"message": {"content": "一只小猫整理便签"}}], "usage": {"prompt_tokens": 1.75, "completion_tokens": 1}},
    ],
)
def test_generate_prompts_returns_502_for_malformed_prompt_model_output(api_client, auth_headers, created_wechat_article, monkeypatch, payload):
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setenv("WECHAT_MP_PROMPT_BASE_URL", "https://prompt.example")
    monkeypatch.setenv("WECHAT_MP_PROMPT_API_KEY", "test-key")
    monkeypatch.setattr(prompt_service.requests, "post", lambda *args, **kwargs: FakeResponse())
    client, _ = api_client

    response = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)

    assert response.status_code == 502


def test_edit_and_regenerate_prompt_increment_version(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    monkeypatch.setattr(
        prompt_service,
        "_call_prompt_model",
        lambda **kwargs: {"prompt": "第一版提示词", "input_tokens": 12, "output_tokens": 24, "model_name": kwargs["model_name"]},
    )
    client, _ = api_client
    created = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)
    prompt_id = created.json()[0]["id"]
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
    assert edited.json()["editable_prompt"] == "编辑后的提示词"
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
    assert regenerated.json()["prompt"] == "再生成的提示词"
    assert regenerated.json()["editable_prompt"] == "再生成的提示词"
    assert regenerated.json()["version"] == 3
    assert client.get(
        f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}", headers=auth_headers
    ).json()["html_body"].count(marker) == 1


def test_prompt_endpoints_hide_foreign_article_and_prompt(api_client, auth_headers, created_wechat_article, monkeypatch):
    from backend.app.services import wechat_mp_image_prompt_service as prompt_service

    monkeypatch.setattr(
        prompt_service,
        "_call_prompt_model",
        lambda **kwargs: {"prompt": "提示词", "input_tokens": 1, "output_tokens": 1, "model_name": kwargs["model_name"]},
    )
    client, _ = api_client
    created = client.post(f"/api/platforms/wechat-mp/articles/{created_wechat_article.id}/prompts", headers=auth_headers)
    prompt_id = created.json()[0]["id"]
    other = client.post("/api/auth/register", json={"username": "wechat-prompt-other", "password": "secret123"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

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

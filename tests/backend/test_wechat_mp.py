import importlib.util
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
        assert stored.token_cache == {"access_token": "token-value", "expires_in": 7200}
    finally:
        session.close()


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

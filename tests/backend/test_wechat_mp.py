import pytest
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

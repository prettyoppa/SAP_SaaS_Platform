"""get_current_user — 미들웨어 expunge User 재연결."""

from unittest.mock import MagicMock, patch

from app import auth


def test_get_current_user_rebinds_detached_middleware_user():
    request = MagicMock()
    detached = MagicMock()
    detached.id = 42
    request.state.current_user = detached
    db = MagicMock()
    bound = MagicMock()
    bound.id = 42
    bound.is_active = True
    db.get.return_value = bound

    with patch("sqlalchemy.orm.object_session", return_value=None):
        user = auth.get_current_user(request, db)

    assert user is bound
    db.get.assert_called_once()


def test_get_current_user_keeps_same_session_user():
    request = MagicMock()
    db = MagicMock()
    attached = MagicMock()
    attached.id = 7
    request.state.current_user = attached

    with patch("sqlalchemy.orm.object_session", return_value=db):
        user = auth.get_current_user(request, db)

    assert user is attached
    db.get.assert_not_called()

"""phone_blocked_by_other_user — allow_shared_phone bypass."""

from __future__ import annotations

import unittest

from app import models
from app.database import Base, SessionLocal, engine
from app.phone_uniqueness import phone_blocked_by_other_user


class PhoneUniquenessTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_shared_phone_allowed_when_flag_on(self):
        a = models.User(
            email="a@example.com",
            full_name="A",
            hashed_password="x",
            phone_number="+821011111111",
            phone_verified=True,
        )
        b = models.User(
            email="b@example.com",
            full_name="B",
            hashed_password="x",
            allow_shared_phone=True,
        )
        self.db.add_all([a, b])
        self.db.commit()
        self.db.refresh(b)
        self.assertFalse(phone_blocked_by_other_user(self.db, "+821011111111", b.id))

    def test_shared_phone_blocked_without_flag(self):
        a = models.User(
            email="c@example.com",
            full_name="C",
            hashed_password="x",
            phone_number="+821022222222",
            phone_verified=True,
        )
        b = models.User(
            email="d@example.com",
            full_name="D",
            hashed_password="x",
            allow_shared_phone=False,
        )
        self.db.add_all([a, b])
        self.db.commit()
        self.db.refresh(b)
        self.assertTrue(phone_blocked_by_other_user(self.db, "+821022222222", b.id))


if __name__ == "__main__":
    unittest.main()

"""Unit tests for pure user-management rules (no DB, no pydantic)."""
from __future__ import annotations

import uuid

from app.services import user_rules


def test_normalize_email_trims_and_lowercases():
    assert user_rules.normalize_email("  Foo@Bar.COM ") == "foo@bar.com"
    assert user_rules.normalize_email("already@lower.com") == "already@lower.com"


def test_password_problems_empty_lists_all_requirements():
    problems = user_rules.password_problems("")
    assert "at least 10 characters" in problems
    assert "at least one letter" in problems
    assert "at least one digit" in problems


def test_password_problems_too_short_only():
    assert user_rules.password_problems("Ab1") == ["at least 10 characters"]


def test_password_problems_missing_digit():
    assert user_rules.password_problems("abcdefghij") == ["at least one digit"]


def test_password_problems_missing_letter():
    assert user_rules.password_problems("1234567890") == ["at least one letter"]


def test_password_problems_valid():
    assert user_rules.password_problems("Password123") == []


def test_role_changes():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    to_add, to_remove = user_rules.role_changes({a, b}, {b, c})
    assert to_add == {c}
    assert to_remove == {a}


def test_invalid_role_ids():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert user_rules.invalid_role_ids({a, b, c}, {a, b}) == {c}
    assert user_rules.invalid_role_ids({a}, {a, b}) == set()


def test_dedupe_preserving_order():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert user_rules.dedupe_preserving_order([a, b, a, c, b]) == [a, b, c]

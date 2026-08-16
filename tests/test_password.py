"""Tests for password hashing."""

from app.auth.password import hash_password, verify_password


def test_hash_is_not_plaintext():
    hashed = hash_password("correct-horse-battery-staple")
    assert hashed != "correct-horse-battery-staple"
    assert hashed.startswith("$argon2")


def test_verify_correct_password():
    hashed = hash_password("s3cret-password")
    assert verify_password("s3cret-password", hashed) is True


def test_verify_wrong_password():
    hashed = hash_password("s3cret-password")
    assert verify_password("wrong-password", hashed) is False


def test_verify_malformed_hash_is_false():
    assert verify_password("anything", "not-a-valid-hash") is False

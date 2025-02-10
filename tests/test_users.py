# tests/test_users.py
import os
import pytest
from local import Base, register_user_local, login_user_local

# Override the database URL for testing
TEST_DB_URL = "sqlite:///test.db"
os.environ["DATABASE_URL"] = TEST_DB_URL

# Reinitialize the test database
from app import engine
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

def test_register_and_login():
    email = "test@example.com"
    password = "strongpassword"
    # Register the user.
    result = register_user_local(email, password)
    assert result is True, "User registration should succeed."

    # Attempt login with an incorrect password.
    result_wrong = login_user_local(email, "wrongpassword")
    assert result_wrong is False, "Login should fail with the wrong password."

    # Login with the correct password.
    result_login = login_user_local(email, password)
    assert result_login is True, "Login should succeed with the correct credentials."

import sys
import os
# Add the project root to sys.path so that "local.py" can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from local import Base, register_user_local, login_user_local

# For testing, override the database URL.
TEST_DB_URL = "sqlite:///test.db"
os.environ["DATABASE_URL"] = TEST_DB_URL

# Import the engine after setting the environment variable.
from local import engine

# Reinitialize the test database.
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

import os

import pytest

# Force testing environment before ANY other modules are imported
os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = "sqlite:///./test.db"


@pytest.fixture(autouse=True, scope="session")
def setup_test_db():
    from src.database import models  # Ensure all models are registered
    from src.database.database import init_db

    init_db()

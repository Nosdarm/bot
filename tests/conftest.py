import sys
import os

# Add the project root directory (one level up from 'tests') to sys.path
# This allows pytest to find modules in the 'bot' directory and 'main.py'
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

print(f"DEBUG: tests/conftest.py loaded. Project root '{project_root}' added to sys.path if not already present.")
print(f"DEBUG: Current sys.path in tests/conftest.py: {sys.path}")

# Also, ensure the root conftest.py (if it was meant to do more) is not completely shadowed
# by trying to load it if necessary, though typically pytest handles discovery from parent directories.
# For now, just adding the path is the key goal.

import pytest

@pytest.fixture(scope="session", autouse=True)
def set_test_environment():
    """
    Sets environment variables for the test session.
    - TESTING_MODE: Informs the application it's running in test mode.
    - TEST_DATABASE_URL: Specifies the database URL for tests (defaults to SQLite in-memory).
    - DATABASE_TYPE: Forces DBService to use a specific adapter type (e.g., "sqlite").
    """
    # print("conftest: set_test_environment fixture activating...")
    os.environ["TESTING_MODE"] = "true"
    # print(f"conftest: TESTING_MODE set to 'true'.")

    # Set TEST_DATABASE_URL default if not already set by the environment
    if "TEST_DATABASE_URL" not in os.environ:
        os.environ["TEST_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
        # print(f"conftest: TEST_DATABASE_URL was not set, defaulted to: {os.environ['TEST_DATABASE_URL']}")
    # else:
        # print(f"conftest: TEST_DATABASE_URL is already set to: {os.environ['TEST_DATABASE_URL']}")

    # Force DBService to use SQLiteAdapter during tests
    original_db_type = os.getenv("DATABASE_TYPE")
    os.environ["DATABASE_TYPE"] = "sqlite"
    # print(f"conftest: DATABASE_TYPE forced to 'sqlite' for testing (original was: '{original_db_type}').")

    yield

    # Teardown: Restore original DATABASE_TYPE if it was set, otherwise remove it.
    if original_db_type is None:
        if "DATABASE_TYPE" in os.environ: # Ensure it was actually set by this fixture
            del os.environ["DATABASE_TYPE"]
            # print("conftest: Restored DATABASE_TYPE by removing it.")
    else:
        os.environ["DATABASE_TYPE"] = original_db_type
        # print(f"conftest: Restored DATABASE_TYPE to its original value: '{original_db_type}'.")

    if "TESTING_MODE" in os.environ:
        del os.environ["TESTING_MODE"]
        # print("conftest: Removed TESTING_MODE environment variable.")
    # print("conftest: set_test_environment fixture teardown complete.")

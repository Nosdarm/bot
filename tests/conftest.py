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

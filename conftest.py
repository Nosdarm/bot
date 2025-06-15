import sys
import os

# Add the project root directory to sys.path
# This allows pytest to find modules in the 'bot' directory and 'main.py'
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, project_root)

print(f"DEBUG: conftest.py loaded. Project root '{project_root}' added to sys.path.")
print(f"DEBUG: Current sys.path: {sys.path}")

import os
import re

def find_project_imports(start_dir):
    """Finds project-internal imports in Python files."""
    project_imports = {}
    for root, _, files in os.walk(start_dir):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                relative_filepath = os.path.relpath(filepath, start_dir)
                # Skip the script file itself
                if relative_filepath == 'map_deps.py':
                    continue

                internal_imports = []
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        for line in f:
                            # Look for 'from . import ...' or 'from project.module import ...'
                            # Adjust the regex based on your project's root package name (e.g., 'bot')
                            match = re.match(r'^\s*from\s+(bot(\.\w+)+)\s+import\s+(\w+|\(|\*).*\s*$', line)
                            if match:
                                module_name = match.group(1)
                                # We only care about imports from within the 'bot' package
                                if module_name.startswith('bot.'):
                                     # Extract the imported part, simplifying for readability
                                     imported_parts = re.findall(r'(\w+)(?:,\s*|\s+as\s+\w+)?', line.split('import')[1])
                                     imported_names = ', '.join(imported_parts).replace('(', '').replace(')', '').replace('*', 'all') # Simplify import names
                                     internal_imports.append(f"from {module_name} import {imported_names}")

                            # Look for 'import project.module' (less common for internal but possible)
                            match_simple = re.match(r'^\s*import\s+(bot(\.\w+)+)(\s+as\s+\w+)?\s*$', line)
                            if match_simple:
                                module_name = match_simple.group(1)
                                if module_name.startswith('bot.'):
                                     internal_imports.append(f"import {module_name}")


                except Exception as e:
                    print(f"Error reading file {relative_filepath}: {e}")
                    continue
                
                if internal_imports:
                     project_imports[relative_filepath] = internal_imports
    return project_imports

if __name__ == "__main__":
    # Assumes the script is run from the project root and your main package is 'bot'
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bot_package_dir = os.path.join(project_root, 'bot') # Adjust if your main package is named differently

    if not os.path.exists(bot_package_dir):
        print(f"Error: Could not find the 'bot' package directory at {bot_package_dir}.")
        print("Please run this script from your project's root directory (where main.py is) or adjust the 'bot_package_dir' variable in the script.")
    else:
        print("Scanning project for internal imports...")
        dependencies = find_project_imports(project_root)

        if dependencies:
            print("\n--- Project Internal Dependencies (Imports) ---")
            # Sort files alphabetically for consistent output
            for filepath in sorted(dependencies.keys()):
                print(f"\nFile: {filepath}")
                for imp in dependencies[filepath]:
                    print(f"  - {imp}")
            print("\n--- End of Dependencies ---")
            print("\nCopy the output above and share it.")
        else:
            print("\nNo internal imports found in the 'bot' package.")

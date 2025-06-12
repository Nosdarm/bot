import json
import os

# Define file paths
locations_file_path = "data/locations.json"
settings_file_path = "data/settings.json"

# Read the content of data/locations.json
try:
    with open(locations_file_path, "r", encoding="utf-8") as f:
        locations_data = json.load(f)
except FileNotFoundError:
    print(f"Error: {locations_file_path} not found.")
    exit(1)
except json.JSONDecodeError:
    print(f"Error: Could not decode JSON from {locations_file_path}.")
    exit(1)

# Read the content of data/settings.json
try:
    with open(settings_file_path, "r", encoding="utf-8") as f:
        settings_data = json.load(f)
except FileNotFoundError:
    print(f"Error: {settings_file_path} not found. Initializing with an empty structure.")
    settings_data = {} # Initialize if not found, or handle as an error
except json.JSONDecodeError:
    print(f"Error: Could not decode JSON from {settings_file_path}. Re-initializing to avoid corruption.")
    settings_data = {} # Re-initialize if corrupted, or handle as an error


# Ensure 'location_templates' exists in settings_data
if 'location_templates' not in settings_data:
    settings_data['location_templates'] = {}

# Iterate through locations_data and transform/add to settings_data
for loc_tpl in locations_data:
    template_id = loc_tpl.get("id")
    if not template_id:
        print(f"Skipping location template due to missing id: {loc_tpl}")
        continue

    # Create the new structure for the template
    new_template_entry = {
        "name_i18n": loc_tpl.get("name_i18n", {}),
        "description_i18n": loc_tpl.get("description_i18n", {}),
        # Transform 'connections' to 'exits'
        "exits": {conn_id: conn_id for conn_id in loc_tpl.get("connections", [])},
    }

    # Add any other top-level keys from loc_tpl that aren't 'id' or 'connections'
    # This part is to ensure any other relevant data from locations.json is preserved.
    for key, value in loc_tpl.items():
        if key not in ["id", "connections", "name_i18n", "description_i18n"]:
            new_template_entry[key] = value

    settings_data['location_templates'][template_id] = new_template_entry

# Ensure the 'data' directory exists before writing
os.makedirs(os.path.dirname(settings_file_path), exist_ok=True)

# Write the modified settings_data back to 'data/settings.json'
try:
    with open(settings_file_path, "w", encoding="utf-8") as f:
        json.dump(settings_data, f, ensure_ascii=False, indent=2)
    print(f"Successfully updated {settings_file_path} with new location templates.")
except Exception as e:
    print(f"Error writing updated {settings_file_path}: {e}")
    # exit(1) # Optionally exit if writing fails
    raise # Re-raise to make the subtask fail if writing fails

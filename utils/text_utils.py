import json
import os

DEFAULT_LANGUAGE = "en"
DATA_DIR = "game_data" # Relative path to the game_data directory

# Memoization caches for loaded data
_location_descriptions_cache = None
_lore_entries_cache = None
_world_map_cache = None

def _load_json_data(filename):
    """Loads JSON data from a file in the DATA_DIR."""
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        # Log this error or handle it as appropriate for your game
        print(f"Error: Data file not found at {path}")
        return None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {path}")
        return None

def get_location_description(location_id: str, player_language: str) -> str:
    """
    Retrieves the description for a given location ID in the player's language.
    Falls back to the default language if the player's language is not available.
    Returns None if the location_id is not found.
    """
    global _location_descriptions_cache
    if _location_descriptions_cache is None:
        _location_descriptions_cache = _load_json_data("locations.descriptions_i18n.json")

    if not _location_descriptions_cache or "locations" not in _location_descriptions_cache:
        return "Error: Location descriptions not loaded."

    for loc in _location_descriptions_cache["locations"]:
        if loc["id"] == location_id:
            if player_language in loc["description_i18n"]:
                return loc["description_i18n"][player_language]
            elif DEFAULT_LANGUAGE in loc["description_i18n"]:
                return loc["description_i18n"][DEFAULT_LANGUAGE]
            else:
                return "Error: No description found for this location in any language."
    return "Error: Location ID not found."

def get_location_name(location_id: str, player_language: str) -> str:
    """
    Retrieves the name for a given location ID in the player's language.
    Falls back to the default language if the player's language is not available.
    Returns None if the location_id is not found.
    """
    global _location_descriptions_cache
    if _location_descriptions_cache is None:
        _location_descriptions_cache = _load_json_data("locations.descriptions_i18n.json")

    if not _location_descriptions_cache or "locations" not in _location_descriptions_cache:
        return "Error: Location names not loaded."

    for loc in _location_descriptions_cache["locations"]:
        if loc["id"] == location_id:
            if player_language in loc["name_i18n"]:
                return loc["name_i18n"][player_language]
            elif DEFAULT_LANGUAGE in loc["name_i18n"]:
                return loc["name_i18n"][DEFAULT_LANGUAGE]
            else:
                return "Error: No name found for this location in any language."
    return "Error: Location ID not found."

def get_lore_text(lore_id: str, player_language: str) -> tuple[str, str] | tuple[str, None]:
    """
    Retrieves the title and text for a given lore ID in the player's language.
    Falls back to the default language if the player's language is not available.
    Returns (title, text) or (error_message, None) if not found.
    """
    global _lore_entries_cache
    if _lore_entries_cache is None:
        _lore_entries_cache = _load_json_data("lore_i18n.json")

    if not _lore_entries_cache or "lore_entries" not in _lore_entries_cache:
        return "Error: Lore entries not loaded.", None

    for entry in _lore_entries_cache["lore_entries"]:
        if entry["id"] == lore_id:
            title = entry["title_i18n"].get(player_language, entry["title_i18n"].get(DEFAULT_LANGUAGE))
            text = entry["text_i18n"].get(player_language, entry["text_i18n"].get(DEFAULT_LANGUAGE))
            if title and text:
                return title, text
            else:
                return "Error: No title or text found for this lore entry in any language.", None
    return "Error: Lore ID not found.", None

def get_connection_description(from_location_id: str, to_location_id: str, player_language: str) -> str:
    """
    Retrieves the description for a connection between two locations in the player's language.
    Falls back to the default language if the player's language is not available.
    Returns an error message string if not found.
    """
    global _world_map_cache
    if _world_map_cache is None:
        _world_map_cache = _load_json_data("world_map.json")

    if not _world_map_cache or "map" not in _world_map_cache:
        return "Error: World map data not loaded."

    for loc_data in _world_map_cache["map"]:
        if loc_data["location_id"] == from_location_id:
            for conn in loc_data.get("connections", []):
                if conn.get("to_location_id") == to_location_id:
                    if player_language in conn["description_i18n"]:
                        return conn["description_i18n"][player_language]
                    elif DEFAULT_LANGUAGE in conn["description_i18n"]:
                        return conn["description_i18n"][DEFAULT_LANGUAGE]
                    else:
                        return "Error: No description for this connection in any language."
            return "Error: Target connection not found from this location."
    return "Error: Origin location ID not found in map."

# Example usage (optional, for testing)
if __name__ == '__main__':
    # Create dummy game_data directory and files for standalone testing
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    test_locations = {
      "locations": [
        {
          "id": "forest_entrance",
          "name_i18n": { "en": "Forest Entrance", "ru": "Вход в лес" },
          "description_i18n": { "en": "A dark entrance.", "ru": "Темный вход."}
        }
      ]
    }
    with open(os.path.join(DATA_DIR, "locations.descriptions_i18n.json"), 'w', encoding='utf-8') as f:
        json.dump(test_locations, f)

    test_lore = {
      "lore_entries": [
        {
          "id": "world_creation",
          "title_i18n": { "en": "Creation", "ru": "Сотворение" },
          "text_i18n": { "en": "In the beginning...", "ru": "В начале..." }
        }
      ]
    }
    with open(os.path.join(DATA_DIR, "lore_i18n.json"), 'w', encoding='utf-8') as f:
        json.dump(test_lore, f)
        
    test_map = {
      "map": [
        {
          "location_id": "forest_entrance",
          "connections": [ { "to_location_id": "clearing", "direction": "north", "description_i18n": { "en": "Path north", "ru": "Путь на север" }}]
        }
      ]
    }
    with open(os.path.join(DATA_DIR, "world_map.json"), 'w', encoding='utf-8') as f:
        json.dump(test_map, f)

    print("---- Location Description ----")
    print("EN:", get_location_description("forest_entrance", "en"))
    print("RU:", get_location_description("forest_entrance", "ru"))
    print("FR (fallback):", get_location_description("forest_entrance", "fr"))
    print("Missing ID:", get_location_description("missing_id", "en"))

    print("\n---- Location Name ----")
    print("EN:", get_location_name("forest_entrance", "en"))
    print("RU:", get_location_name("forest_entrance", "ru"))

    print("\n---- Lore Text ----")
    title, text = get_lore_text("world_creation", "en")
    print(f"EN Title: {title}, Text: {text}")
    title, text = get_lore_text("world_creation", "ru")
    print(f"RU Title: {title}, Text: {text}")
    title, text = get_lore_text("world_creation", "fr") # Fallback
    print(f"FR Title (fallback): {title}, Text: {text}")

    print("\n---- Connection Description ----")
    print("EN:", get_connection_description("forest_entrance", "clearing", "en"))
    print("RU:", get_connection_description("forest_entrance", "clearing", "ru"))

    # Clean up dummy files and directory
    # os.remove(os.path.join(DATA_DIR, "locations.descriptions_i18n.json"))
    # os.remove(os.path.join(DATA_DIR, "lore_i18n.json"))
    # os.remove(os.path.join(DATA_DIR, "world_map.json"))
    # if not os.listdir(DATA_DIR): # Check if directory is empty
    #     os.rmdir(DATA_DIR)

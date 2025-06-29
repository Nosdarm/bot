import json
from bot import rules

def parse_and_validate_ai_response(raw_ai_output_text: str, guild_id: int):
    try:
        parsed_data = json.loads(raw_ai_output_text)
    except json.JSONDecodeError:
        return None, "Invalid JSON"

    # Validate structure
    if not isinstance(parsed_data, dict):
        return None, "Response is not a JSON object"

    # Semantic validation
    game_rules = rules.get_rule(guild_id, "game_rules", {})
    
    # Example validation for a new location
    if "new_location" in parsed_data:
        location_data = parsed_data["new_location"]
        if "name_i18n" not in location_data or "descriptions_i18n" not in location_data:
            return None, "Missing required fields for new location"
            
    # Example validation for a new NPC
    if "new_npc" in parsed_data:
        npc_data = parsed_data["new_npc"]
        if "name_i18n" not in npc_data or "description_i18n" not in npc_data:
            return None, "Missing required fields for new NPC"

    return parsed_data, None

# bot/nlu/player_action_parser.py
import re
from typing import Optional, Tuple, List, Dict, Any

# --- Keyword Dictionaries ---

INTENT_KEYWORDS_EN = {
    "move": ["move", "go", "walk", "head", "proceed", "travel"],
    "look": ["look", "examine", "inspect", "view", "observe", "scan", "check"],
    "attack": ["attack", "fight", "hit", "strike", "assault"],
    "talk": ["talk", "speak", "chat", "ask", "converse"],
    "use_skill": ["use skill", "cast skill", "activate skill"], # More specific to avoid clash with "use item"
    "pickup": ["pickup", "take", "get", "collect", "grab"],
    "use_item": ["use", "apply", "consume", "equip"], # "use" is broad, order of checking might matter
    "search": ["search", "explore", "look for", "find"],
}

INTENT_KEYWORDS_RU = {
    "move": ["иди", "двигайся", "шагай", "ступай", "отправляйся", "переместись", "идти"],
    "look": ["смотри", "осмотри", "глянь", "исследуй", "проверь", "оглядись", "смотреть"],
    "attack": ["атакуй", "дерись", "ударь", "бей", "напади", "атаковать"],
    "talk": ["говори", "поговори", "спроси", "болтай", "общайся", "разговаривай", "спросить"],
    "use_skill": ["используй умение", "примени умение", "активируй умение", "кастуй умение"],
    "pickup": ["подбери", "возьми", "собери", "хватай", "получи", "взять"],
    "use_item": ["используй", "примени", "съешь", "надень", "экипируй", "использовать"], # "используй" is broad
    "search": ["ищи", "обыщи", "исследуй", "найди", "поищи", "искать"],
}

# --- Regular Expression Patterns for Entities ---
# These are simplified and might need refinement.
# Using re.IGNORECASE for flexibility.

# English patterns
PATTERNS_EN = {
    "move_to_location": re.compile(r"(?:move|go|walk|head|travel)\s+(?:to\s+)?(.+)", re.IGNORECASE),
    "move_direction": re.compile(r"(?:move|go|walk|head|travel)\s+(north|south|east|west|up|down|forward|backward|left|right)", re.IGNORECASE),
    "attack_target": re.compile(r"(?:attack|fight|hit|strike)\s+(.+)", re.IGNORECASE),
    "talk_to_npc": re.compile(r"(?:talk|speak|chat|ask)\s+(?:to\s+|with\s+)?(.+)", re.IGNORECASE),
    "pickup_item": re.compile(r"(?:pickup|take|get|collect|grab)\s+(.+)", re.IGNORECASE),
    "use_item_simple": re.compile(r"(?:use|apply|consume|equip)\s+(.+?)(?:\s+on\s+(.+))?$", re.IGNORECASE), # Supports "use item" and "use item on target"
    "use_skill_simple": re.compile(r"(?:use skill|cast skill|activate skill)\s+(.+?)(?:\s+on\s+(.+))?$", re.IGNORECASE),
    "search_location": re.compile(r"(?:search|explore|look for)\s+(?:in|at|around|for\s+)?(.+)", re.IGNORECASE), # "search for item" might be ambiguous with "pickup"
    "look_at_target": re.compile(r"(?:look|examine|inspect|view|observe|scan|check)\s+(?:at\s+)?(.+)", re.IGNORECASE),
}

# Russian patterns
PATTERNS_RU = {
    "move_to_location": re.compile(r"(?:иди|двигайся|переместись|отправляйся)\s+(?:в\s+|на\s+)?(.+)", re.IGNORECASE),
    "move_direction": re.compile(r"(?:иди|двигайся)\s+(север|юг|восток|запад|вверх|вниз|вперед|назад|влево|вправо)", re.IGNORECASE),
    "attack_target": re.compile(r"(?:атакуй|дерись|ударь|бей)\s+(.+)", re.IGNORECASE),
    "talk_to_npc": re.compile(r"(?:говори|поговори|спроси)\s+(?:с\s+)?(.+)", re.IGNORECASE),
    "pickup_item": re.compile(r"(?:подбери|возьми|собери|хватай)\s+(.+)", re.IGNORECASE),
    "use_item_simple": re.compile(r"(?:используй|примени|съешь|надень)\s+(.+?)(?:\s+(?:на|в)\s+(.+))?$", re.IGNORECASE),
    "use_skill_simple": re.compile(r"(?:используй умение|примени умение|активируй умение)\s+(.+?)(?:\s+(?:на|в)\s+(.+))?$", re.IGNORECASE),
    "search_location": re.compile(r"(?:ищи|обыщи|исследуй|поищи)\s+(?:в\s+|на\s+|за\s+)?(.+)", re.IGNORECASE),
    "look_at_target": re.compile(r"(?:смотри|осмотри|глянь|исследуй|проверь)\s+(?:на\s+)?(.+)", re.IGNORECASE),
}

# Helper function to find matching entity from DB list
def _find_matching_db_entity(text_entity_name: str, db_entities: List[Dict[str, Any]], entity_type_name: str) -> Optional[Dict[str, str]]:
    if not db_entities:
        return None
    
    text_entity_name_lower = text_entity_name.lower()
    for db_entity in db_entities:
        # db_entity is of type NLUEntity (TypedDict)
        if db_entity['name'].lower() == text_entity_name_lower:
            return {"type": entity_type_name, "id": db_entity['id'], "name": db_entity['name']}
    return None


async def parse_player_action(text: str, language: str, guild_id: str, game_terms_db: Any = None) -> Optional[Tuple[str, List[Dict[str, str]]]]:
    """
    Parses player input text to identify an intent and extract entities.

    Args:
        text (str): The raw input text from the player.
        language (str): The language of the input text ("en", "ru").
        guild_id (str): The ID of the guild where the action is performed. Used to fetch guild-specific game terms.
        game_terms_db (Any): Instance of NLUDataService or similar for fetching game-specific terms.

    Returns:
        Optional[Tuple[str, List[Dict[str, str]]]]: A tuple containing the intent string
        and a list of extracted entity dictionaries (e.g., {"type": "location_name", "value": "forest"}),
        or None if no intent is recognized.
    """
    text = text.lower().strip()
    if not text:
        return None

    keywords_map = INTENT_KEYWORDS_EN if language == "en" else INTENT_KEYWORDS_RU
    patterns_map = PATTERNS_EN if language == "en" else PATTERNS_RU

    db_game_entities: Dict[str, List[Dict[str, Any]]] = {}
    if game_terms_db:
        try:
            # NLUDataService.get_game_entities is async
            db_game_entities = await game_terms_db.get_game_entities(guild_id=guild_id, language=language)
        except Exception as e:
            print(f"NLU Parser: Error fetching game entities from DB: {e}")
            # Continue without db_entities, or handle error more strictly

    # --- Regex-based matching (more specific patterns first) ---

    # Move to location or direction
    match_move_to_loc = patterns_map["move_to_location"].match(text)
    if match_move_to_loc:
        potential_loc_name = match_move_to_loc.group(1).strip()
        if db_game_entities.get("location"):
            db_loc = _find_matching_db_entity(potential_loc_name, db_game_entities["location"], "location")
            if db_loc:
                return "move", [db_loc]
        # Fallback to raw name if not found in DB or DB not available
        return "move", [{"type": "location_name", "value": potential_loc_name}]

    match_move_direction = patterns_map["move_direction"].match(text)
    if match_move_direction:
        return "move", [{"type": "direction", "value": match_move_direction.group(1).strip()}]

    # Attack target
    match = patterns_map["attack_target"].match(text)
    if match:
        potential_target_name = match.group(1).strip()
        if db_game_entities.get("npc"): # Assuming targets are NPCs for now
            db_npc = _find_matching_db_entity(potential_target_name, db_game_entities["npc"], "npc") # type becomes "npc"
            if db_npc:
                # Standardize to target_name for generic processing later, but add original type and id
                return "attack", [{"type": "target_name", "id": db_npc["id"], "name": db_npc["name"], "original_type": "npc"}]
        # Fallback
        return "attack", [{"type": "target_name", "value": potential_target_name}]

    # Talk to NPC
    match = patterns_map["talk_to_npc"].match(text)
    if match:
        potential_npc_name = match.group(1).strip()
        if db_game_entities.get("npc"):
            db_npc = _find_matching_db_entity(potential_npc_name, db_game_entities["npc"], "npc")
            if db_npc:
                return "talk", [db_npc]
        return "talk", [{"type": "npc_name", "value": potential_npc_name}]

    # Pickup item
    match = patterns_map["pickup_item"].match(text)
    if match:
        potential_item_name = match.group(1).strip()
        if db_game_entities.get("item"):
            db_item = _find_matching_db_entity(potential_item_name, db_game_entities["item"], "item")
            if db_item:
                return "pickup", [db_item]
        return "pickup", [{"type": "item_name", "value": potential_item_name}]

    # Use item [on target]
    match = patterns_map["use_item_simple"].match(text)
    if match:
        item_text_name = match.group(1).strip()
        target_text_name = match.group(2).strip() if match.group(2) else None
        entities = []
        
        # Match item
        item_entity = None
        if db_game_entities.get("item"):
            item_entity = _find_matching_db_entity(item_text_name, db_game_entities["item"], "item")
        
        if item_entity:
            entities.append(item_entity)
        else:
            entities.append({"type": "item_name", "value": item_text_name}) # Fallback for item

        # Match target if exists
        if target_text_name:
            target_entity = None
            npc_data_list = db_game_entities.get("npc") # Get NPC list once
            if npc_data_list:
                target_entity = _find_matching_db_entity(target_text_name, npc_data_list, "npc")

            if target_entity:
                # Standardize to target_name for generic processing, but add original type and id
                entities.append({"type": "target_name", "id": target_entity["id"], "name": target_entity["name"], "original_type": "npc"})
            else:
                entities.append({"type": "target_name", "value": target_text_name}) # Fallback for target
        
        if entities: # Should always have at least item
            return "use_item", entities
        
    # Use skill [on target] - Skills not fetched from DB in this iteration yet, but structure is similar
    match = patterns_map["use_skill_simple"].match(text)
    if match:
        skill_text_name = match.group(1).strip()
        target_text_name = match.group(2).strip() if match.group(2) else None
        entities = []

        # Match skill (if db_game_entities['skill'] was populated)
        skill_entity = None
        if db_game_entities.get("skill"):
            skill_entity = _find_matching_db_entity(skill_text_name, db_game_entities["skill"], "skill")
        
        if skill_entity:
            entities.append(skill_entity)
        else:
            entities.append({"type": "skill_name", "value": skill_text_name}) # Fallback

        if target_text_name:
            target_entity = None
            if db_game_entities.get("npc"): # Assuming targets are NPCs
                target_entity = _find_matching_db_entity(target_text_name, db_game_entities["npc"], "npc")
            
            if target_entity:
                entities.append({"type": "target_name", "id": target_entity["id"], "name": target_entity["name"], "original_type": "npc"})
            else:
                entities.append({"type": "target_name", "value": target_text_name})
        
        if entities:
            return "use_skill", entities

    # Search (generic, could be location or for item)
    match = patterns_map["search_location"].match(text)
    if match:
        potential_search_term = match.group(1).strip()
        # Try to match against locations first
        if db_game_entities.get("location"):
            db_loc = _find_matching_db_entity(potential_search_term, db_game_entities["location"], "location")
            if db_loc: # If it's a known location name
                return "search", [db_loc] # Entity type is "location"
        # Try to match against items
        if db_game_entities.get("item"):
            db_item = _find_matching_db_entity(potential_search_term, db_game_entities["item"], "item")
            if db_item: # If it's a known item name
                 return "search", [db_item] # Entity type is "item"
        # Fallback if not a known location or item
        return "search", [{"type": "search_target", "value": potential_search_term}]


    # Look at target (could be item, NPC, location feature)
    match = patterns_map["look_at_target"].match(text)
    if match:
        potential_target_name = match.group(1).strip()
        # Order of checking matters: NPCs, then Items, then Locations as a broader category
        if db_game_entities.get("npc"):
            db_npc = _find_matching_db_entity(potential_target_name, db_game_entities["npc"], "npc")
            if db_npc:
                return "look", [db_npc]
        if db_game_entities.get("item"):
            db_item = _find_matching_db_entity(potential_target_name, db_game_entities["item"], "item")
            if db_item:
                return "look", [db_item]
        if db_game_entities.get("location"): # Could be a specific feature in a location
            db_loc = _find_matching_db_entity(potential_target_name, db_game_entities["location"], "location")
            if db_loc:
                return "look", [db_loc]
        # Fallback
        return "look", [{"type": "target_name", "value": potential_target_name}]
    
    # --- Keyword-based intent recognition (fallback or for simple commands) ---
    # This part is for commands that might not have complex entities captured by regex above,
    if match:
        return "move", [{"type": "direction", "value": match.group(1).strip()}]

    # Attack target
    match = patterns_map["attack_target"].match(text)
    if match:
        return "attack", [{"type": "target_name", "value": match.group(1).strip()}]

    # Talk to NPC
    match = patterns_map["talk_to_npc"].match(text)
    if match:
        return "talk", [{"type": "npc_name", "value": match.group(1).strip()}]

    # Pickup item
    match = patterns_map["pickup_item"].match(text)
    if match:
        return "pickup", [{"type": "item_name", "value": match.group(1).strip()}]

    # Use item [on target]
    match = patterns_map["use_item_simple"].match(text)
    if match:
        item_name = match.group(1).strip()
        target_name = match.group(2).strip() if match.group(2) else None
        entities = [{"type": "item_name", "value": item_name}]
        if target_name:
            entities.append({"type": "target_name", "value": target_name})
        return "use_item", entities
        
    # Use skill [on target]
    match = patterns_map["use_skill_simple"].match(text)
    if match:
        skill_name = match.group(1).strip()
        target_name = match.group(2).strip() if match.group(2) else None
        entities = [{"type": "skill_name", "value": skill_name}] # Assuming "skill_name" type
        if target_name:
            entities.append({"type": "target_name", "value": target_name})
        return "use_skill", entities

    # Search (generic, could be location or for item)
    match = patterns_map["search_location"].match(text) # "search for item" might be better handled by keyword based or specific regex
    if match:
        # This is very generic. "search the chest" vs "search for clues"
        # For now, assume it's a general area/object being searched.
        return "search", [{"type": "search_target", "value": match.group(1).strip()}]


    # Look at target (could be item, NPC, location feature)
    match = patterns_map["look_at_target"].match(text)
    if match:
        return "look", [{"type": "target_name", "value": match.group(1).strip()}]


    # --- Keyword-based intent recognition (fallback or for simple commands) ---
    # This part is for commands that might not have complex entities captured by regex above,
    # or if regex fails. Order can be important.
    
    # Iterate through intents and their keywords
    # The order of intents in INTENT_KEYWORDS might matter if keywords overlap significantly.
    # For example, "use" is a very common verb.
    
    # A more robust way might be to check based on the length of the keyword match (longer first)
    # or have primary vs secondary keywords.

    # For now, simple iteration.
    # This might misclassify if a "use item" command didn't match regex and "use" is a look keyword.
    # This is why specific regex for "use item" and "use skill" is better.
    
    # Check "look" first as it's often parameterless ("look around")
    for keyword in keywords_map.get("look", []):
        if text == keyword: # Exact match for simple "look"
             return "look", [] # No entity, just general look around

    # Check other intents
    # We need a more careful approach if regex above didn't catch them.
    # For commands like "move" (without args), "inventory", etc.
    
    # Example: if "move" was typed alone, regexes for "move to" or "move direction" would fail.
    # This needs to be handled.

    # General keyword check (less precise, better for commands without arguments)
    # This is a simplified fallback.
    # Consider the order of INTENT_KEYWORDS for keyword matching if there's ambiguity.
    # For example, "use" is in "use_item", but if it's also a keyword for another intent.

    for intent, kws in keywords_map.items():
        for keyword in kws:
            # Check if the text *starts with* the keyword, allowing for simple entities not caught by regex.
            # This is a basic form of entity extraction if no regex matched.
            if text.startswith(keyword):
                # Simplistic entity extraction: the rest of the string
                potential_entity = text[len(keyword):].strip()
                entities = []

                # This is very naive. Regex above is preferred.
                # This part is more for single-word commands or very simple ones.
                if not potential_entity and intent in ["look", "search"]: # Parameterless look/search
                    return intent, []
                
                # Avoid re-classifying if already handled by regex with entities
                # This basic keyword check is primarily for commands that *don't* have entities
                # or very simple ones not caught by specific regex.
                # Example: "inventory" (if it were an intent here), "help", etc.

                # If we reached here, it means the regexes for entities didn't match.
                # So, if `potential_entity` exists, it's an unmatched entity for this keyword.
                # This is too simplistic for most cases.
                # For now, we'll prioritize regex matches above.
                # This keyword loop is mostly for commands that are *just* the keyword.
                if not potential_entity: # Command is just the keyword
                    # Example: "look" (already handled), "attack" (no target specified yet)
                    # This could be ambiguous. "attack" alone might be valid to initiate combat mode.
                    if intent in ["attack", "move"]: # e.g. "attack" to enter combat mode, "move" to see directions
                         return intent, [] # No specific entity from this simple keyword match
                    # Other intents might require entities.

                # Let's make this keyword part primarily for commands that are *just* the keyword itself.
                if text == keyword:
                    if intent in ["look", "search", "attack", "move"]: # Intents that can be parameterless
                        return intent, []
                    # For other intents, they likely need an entity, which regex should have caught.
                    # If not, this basic keyword match isn't enough.
                    
    return None # No intent recognized

if __name__ == '__main__':
    # Basic Test Cases
    test_phrases_en = [
        "go north",
        "move to the forest",
        "look",
        "examine the chest",
        "attack the goblin",
        "fight dragon",
        "talk to Faelan",
        "speak with the merchant",
        "pickup the sword",
        "get healing potion",
        "use healing potion",
        "use sword on goblin",
        "use skill fireball on goblin",
        "activate skill stealth",
        "search the room",
        "explore cave",
        "unknown command",
        "use teleport scroll to the capital", # More complex "use"
        "look at the map",
        "search the old barrel", # Search non-DB entity
        "look at the strange painting", # Look at non-DB entity
        "use unknown_item", # Use non-DB item
        "use skill unknown_skill" # Use non-DB skill
    ]

    test_phrases_ru = [
        "иди на север",
        "переместись в лес",
        "смотри",
        "осмотри сундук",
        "атакуй гоблина",
        "дерись с драконом",
        "поговори с Фаэланом",
        "поговорить с торговцем", # Infinitive form
        "подбери меч",
        "возьми зелье лечения",
        "используй зелье лечения",
        "используй меч на гоблине",
        "используй умение огненный шар на гоблине",
        "активируй умение скрытность",
        "обыщи комнату",
        "исследуй пещеру",
        "неизвестная команда",
        "использовать свиток телепорта в столицу",
        "смотри на карту",
        "обыщи старую бочку", # Search non-DB entity (RU)
        "осмотри странную картину", # Look at non-DB entity (RU)
        "используй неизвестный предмет", # Use non-DB item (RU)
        "используй умение неизвестное умение" # Use non-DB skill (RU)
    ]

    # Basic Test Cases (guild_id will be dummy for these tests, game_terms_db will be None)
    dummy_guild_id = "test_guild"
    # Mock NLUDataService for testing if needed, or pass None to test fallback
    class MockNLUDataService:
        async def get_game_entities(self, guild_id: str, language: str) -> Dict[str, List[Dict[str, Any]]]:
            # Return some dummy data matching NLUEntity structure
            if language == "en":
                return {
                    "location": [{"id": "loc_forest", "name": "Forest", "type": "location", "lang": "en"},
                                 {"id": "loc_cave", "name": "Cave", "type": "location", "lang": "en"}],
                    "npc": [{"id": "npc_goblin", "name": "Goblin", "type": "npc", "lang": "en"},
                            {"id": "npc_faelan", "name": "Faelan", "type": "npc", "lang": "en"}],
                    "item": [{"id": "item_sword", "name": "Sword", "type": "item", "lang": "en"},
                             {"id": "item_potion", "name": "Healing Potion", "type": "item", "lang": "en"}],
                    "skill": [{"id": "skill_fireball", "name": "Fireball", "type": "skill", "lang": "en"}]
                }
            elif language == "ru":
                 return {
                    "location": [{"id": "loc_forest", "name": "Лес", "type": "location", "lang": "ru"},
                                 {"id": "loc_cave", "name": "Пещера", "type": "location", "lang": "ru"}],
                    "npc": [{"id": "npc_goblin", "name": "Гоблин", "type": "npc", "lang": "ru"},
                            {"id": "npc_faelan", "name": "Фаэлан", "type": "npc", "lang": "ru"}],
                    "item": [{"id": "item_sword", "name": "Меч", "type": "item", "lang": "ru"},
                             {"id": "item_potion", "name": "Зелье лечения", "type": "item", "lang": "ru"}],
                    "skill": [{"id": "skill_fireball", "name": "Огненный шар", "type": "skill", "lang": "ru"}]
                }
            return {}

    mock_nlu_db = MockNLUDataService()
    # To test without DB entities, set mock_nlu_db = None

    async def run_tests():
        print("--- English Tests ---")
        for phrase in test_phrases_en:
            result = await parse_player_action(phrase, "en", dummy_guild_id, mock_nlu_db)
            print(f"Input: '{phrase}' -> Parsed: {result}")

        print("\n--- Russian Tests ---")
        for phrase in test_phrases_ru:
            result = await parse_player_action(phrase, "ru", dummy_guild_id, mock_nlu_db)
            print(f"Input: '{phrase}' -> Parsed: {result}")

        # Test specific cases
        print("\n--- Specific Tests ---")
        print(f"Input: 'use Sword' (en) -> Parsed: {await parse_player_action('use Sword', 'en', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'используй Меч' (ru) -> Parsed: {await parse_player_action('используй Меч', 'ru', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'look around' (en) -> Parsed: {await parse_player_action('look around', 'en', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'оглядись' (ru) -> Parsed: {await parse_player_action('оглядись', 'ru', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'attack Goblin' (en) -> Parsed: {await parse_player_action('attack Goblin', 'en', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'атакуй Гоблина' (ru) -> Parsed: {await parse_player_action('атакуй Гоблина', 'ru', dummy_guild_id, mock_nlu_db)}") # Assuming Goblina is not in mock DB
        print(f"Input: 'go to Forest' (en) -> Parsed: {await parse_player_action('go to Forest', 'en', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'иди в Лес' (ru) -> Parsed: {await parse_player_action('иди в Лес', 'ru', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'go' (en) -> Parsed: {await parse_player_action('go', 'en', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'иди' (ru) -> Parsed: {await parse_player_action('иди', 'ru', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'talk to UnknownNPC' (en) -> Parsed: {await parse_player_action('talk to UnknownNPC', 'en', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'pickup NonExistentItem' (en) -> Parsed: {await parse_player_action('pickup NonExistentItem', 'en', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'use Healing Potion on Goblin' (en) -> Parsed: {await parse_player_action('use Healing Potion on Goblin', 'en', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'use skill Fireball on Goblin' (en) -> Parsed: {await parse_player_action('use skill Fireball on Goblin', 'en', dummy_guild_id, mock_nlu_db)}")
        print(f"Input: 'search Forest' (en) -> Parsed: {await parse_player_action('search Forest', 'en', dummy_guild_id, mock_nlu_db)}") # Search a known location
        print(f"Input: 'search for Sword' (en) -> Parsed: {await parse_player_action('search for Sword', 'en', dummy_guild_id, mock_nlu_db)}") # Search a known item
        print(f"Input: 'look at Sword' (en) -> Parsed: {await parse_player_action('look at Sword', 'en', dummy_guild_id, mock_nlu_db)}") # Look at known item


    import asyncio
    asyncio.run(run_tests())



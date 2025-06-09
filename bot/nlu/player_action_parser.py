# bot/nlu/player_action_parser.py
import re
from typing import Optional, Tuple, List, Dict, Any
from bot.game.managers.game_log_manager import GameLogManager

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


async def parse_player_action(
    text: str,
    language: str,
    guild_id: str,
    game_log_manager: Optional[GameLogManager] = None,
    game_terms_db: Any = None
) -> Optional[Tuple[str, List[Dict[str, str]]]]:
    """
    Parses player input text to identify an intent and extract entities.

    Args:
        text (str): The raw input text from the player.
        language (str): The language of the input text ("en", "ru").
        guild_id (str): The ID of the guild where the action is performed.
        game_log_manager (Optional[GameLogManager]): Manager for logging events.
        game_terms_db (Any): Instance of NLUDataService or similar for fetching game-specific terms.

    Returns:
        Optional[Tuple[str, List[Dict[str, str]]]]: A tuple containing the intent string
        and a list of extracted entity dictionaries (e.g., {"type": "location_name", "value": "forest"}),
        or None if no intent is recognized.
    """
    raw_input_text = text  # Store original text for logging
    processed_text = text.lower().strip() # Use this for parsing logic

    intent_result: Optional[str] = None
    entities_result: Optional[List[Dict[str, str]]] = None

    if not processed_text:
        if game_log_manager:
            await game_log_manager.log_event(
                guild_id=guild_id,
                event_type="NLU_RESULT",
                details={
                    "raw_text": raw_input_text,
                    "language": language,
                    "parsed_intent": None,
                    "parsed_entities": None,
                    "recognition_successful": False,
                    "reason": "empty_input"
                },
                player_id=None,
                message_key="log.nlu.empty_input",
                message_params={}
            )
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
    if not intent_result:
        match_move_to_loc = patterns_map["move_to_location"].match(processed_text)
        if match_move_to_loc:
            potential_loc_name = match_move_to_loc.group(1).strip()
            if db_game_entities.get("location"):
                db_loc = _find_matching_db_entity(potential_loc_name, db_game_entities["location"], "location")
                if db_loc:
                    intent_result, entities_result = "move", [db_loc]
            if not intent_result: # Fallback
                intent_result, entities_result = "move", [{"type": "location_name", "value": potential_loc_name}]

    if not intent_result:
        match_move_direction = patterns_map["move_direction"].match(processed_text)
        if match_move_direction:
            intent_result, entities_result = "move", [{"type": "direction", "value": match_move_direction.group(1).strip()}]

    if not intent_result:
        match = patterns_map["attack_target"].match(processed_text)
        if match:
            potential_target_name = match.group(1).strip()
            if db_game_entities.get("npc"):
                db_npc = _find_matching_db_entity(potential_target_name, db_game_entities["npc"], "npc")
                if db_npc:
                    intent_result, entities_result = "attack", [{"type": "target_name", "id": db_npc["id"], "name": db_npc["name"], "original_type": "npc"}]
            if not intent_result: # Fallback
                intent_result, entities_result = "attack", [{"type": "target_name", "value": potential_target_name}]

    if not intent_result:
        match = patterns_map["talk_to_npc"].match(processed_text)
        if match:
            potential_npc_name = match.group(1).strip()
            if db_game_entities.get("npc"):
                db_npc = _find_matching_db_entity(potential_npc_name, db_game_entities["npc"], "npc")
                if db_npc:
                    intent_result, entities_result = "talk", [db_npc]
            if not intent_result: # Fallback
                intent_result, entities_result = "talk", [{"type": "npc_name", "value": potential_npc_name}]

    if not intent_result:
        match = patterns_map["pickup_item"].match(processed_text)
        if match:
            potential_item_name = match.group(1).strip()
            if db_game_entities.get("item"):
                db_item = _find_matching_db_entity(potential_item_name, db_game_entities["item"], "item")
                if db_item:
                    intent_result, entities_result = "pickup", [db_item]
            if not intent_result: # Fallback
                intent_result, entities_result = "pickup", [{"type": "item_name", "value": potential_item_name}]

    if not intent_result:
        match = patterns_map["use_item_simple"].match(processed_text)
        if match:
            item_text_name = match.group(1).strip()
            target_text_name = match.group(2).strip() if match.group(2) else None
            current_entities = []
            item_entity = None
            if db_game_entities.get("item"):
                item_entity = _find_matching_db_entity(item_text_name, db_game_entities["item"], "item")
            current_entities.append(item_entity if item_entity else {"type": "item_name", "value": item_text_name})
            if target_text_name:
                target_entity = None
                if db_game_entities.get("npc"):
                    target_entity = _find_matching_db_entity(target_text_name, db_game_entities["npc"], "npc")
                if target_entity:
                    current_entities.append({"type": "target_name", "id": target_entity["id"], "name": target_entity["name"], "original_type": "npc"})
                else:
                    current_entities.append({"type": "target_name", "value": target_text_name})
            intent_result, entities_result = "use_item", current_entities
            
    if not intent_result:
        match = patterns_map["use_skill_simple"].match(processed_text)
        if match:
            skill_text_name = match.group(1).strip()
            target_text_name = match.group(2).strip() if match.group(2) else None
            current_entities = []
            skill_entity = None
            if db_game_entities.get("skill"):
                skill_entity = _find_matching_db_entity(skill_text_name, db_game_entities["skill"], "skill")
            current_entities.append(skill_entity if skill_entity else {"type": "skill_name", "value": skill_text_name})
            if target_text_name:
                target_entity = None
                if db_game_entities.get("npc"):
                    target_entity = _find_matching_db_entity(target_text_name, db_game_entities["npc"], "npc")
                if target_entity:
                    current_entities.append({"type": "target_name", "id": target_entity["id"], "name": target_entity["name"], "original_type": "npc"})
                else:
                    current_entities.append({"type": "target_name", "value": target_text_name})
            intent_result, entities_result = "use_skill", current_entities

    if not intent_result:
        match = patterns_map["search_location"].match(processed_text)
        if match:
            potential_search_term = match.group(1).strip()
            found_entity = False
            if db_game_entities.get("location"):
                db_loc = _find_matching_db_entity(potential_search_term, db_game_entities["location"], "location")
                if db_loc:
                    intent_result, entities_result = "search", [db_loc]
                    found_entity = True
            if not found_entity and db_game_entities.get("item"):
                db_item = _find_matching_db_entity(potential_search_term, db_game_entities["item"], "item")
                if db_item:
                    intent_result, entities_result = "search", [db_item]
                    found_entity = True
            if not found_entity: # Fallback
                intent_result, entities_result = "search", [{"type": "search_target", "value": potential_search_term}]

    if not intent_result:
        match = patterns_map["look_at_target"].match(processed_text)
        if match:
            potential_target_name = match.group(1).strip()
            found_entity = False
            if db_game_entities.get("npc"):
                db_npc = _find_matching_db_entity(potential_target_name, db_game_entities["npc"], "npc")
                if db_npc:
                    intent_result, entities_result = "look", [db_npc]
                    found_entity = True
            if not found_entity and db_game_entities.get("item"):
                db_item = _find_matching_db_entity(potential_target_name, db_game_entities["item"], "item")
                if db_item:
                    intent_result, entities_result = "look", [db_item]
                    found_entity = True
            if not found_entity and db_game_entities.get("location"):
                db_loc = _find_matching_db_entity(potential_target_name, db_game_entities["location"], "location")
                if db_loc:
                    intent_result, entities_result = "look", [db_loc]
                    found_entity = True
            if not found_entity: # Fallback
                intent_result, entities_result = "look", [{"type": "target_name", "value": potential_target_name}]
    
    # --- Keyword-based intent recognition (fallback for simple commands) ---
    # This section handles cases where specific regex patterns with entities didn't match,
    # typically for commands that are just a single keyword or very simple.
    if not intent_result:
        # Check "look" first as it's often parameterless ("look around")
        for keyword in keywords_map.get("look", []):
            if processed_text == keyword: # Exact match for simple "look"
                intent_result, entities_result = "look", []
                break # Found intent
        
        if not intent_result: # If "look" didn't match
            for intent_kw, kws in keywords_map.items():
                if intent_result: break # Exit outer loop if intent found
                for keyword in kws:
                    if processed_text == keyword: # Command is just the keyword
                        # For intents that can be parameterless
                        if intent_kw in ["look", "search", "attack", "move"]:
                            intent_result, entities_result = intent_kw, []
                            break # Exit inner loop
                        # Other intents might require entities, but regex above should have caught them.
                        # This basic keyword match is primarily for simple, parameterless commands.

    # --- Logging Block ---
    if game_log_manager:
        recognition_successful = bool(intent_result is not None)
        log_details = {
            "raw_text": raw_input_text,
            "processed_text": processed_text, # Log the version used for parsing
            "language": language,
            "parsed_intent": intent_result,
            "parsed_entities": entities_result,
            "recognition_successful": recognition_successful,
            "used_db_entities": bool(game_terms_db is not None and db_game_entities) # Log if DB terms were available
        }
        log_message_params = {
            "intent": intent_result if intent_result else "None", # Ensure string for params
            "entities_count": len(entities_result) if entities_result else 0
        }
        # Ensure this function is called from an async context if game_log_manager is used.
        await game_log_manager.log_event(
            guild_id=guild_id,
            event_type="NLU_RESULT",
            details=log_details,
            player_id=None,
            message_key="log.nlu.result",
            message_params=log_message_params
        )

    if intent_result:
        return intent_result, entities_result
    return None

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



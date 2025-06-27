# bot/nlu/player_action_parser.py
import re
from typing import Optional, List, Dict, Any, TypedDict # Tuple removed, Union added later if needed for return type, Added TypedDict
import spacy
from spacy.matcher import PhraseMatcher # Import PhraseMatcher
# Forward declare NLUDataService if not importing directly at top level for main parser logic
# from bot.services.nlu_data_service import NLUDataService
from bot.game.managers.game_log_manager import GameLogManager

# Standardized Intent Strings
INTENT_MAP = {
    "move": "INTENT_MOVE",
    "look": "INTENT_LOOK",
    "attack": "INTENT_ATTACK",
    "talk": "INTENT_TALK",
    "use_skill": "INTENT_USE_SKILL",
    "pickup": "INTENT_PICKUP",
    "use_item": "INTENT_USE_ITEM",
    "search": "INTENT_SEARCH",
    "open": "INTENT_OPEN",
    "close": "INTENT_CLOSE",
    "drop": "INTENT_DROP",
    # Add other intents as they become supported (e.g., equip, unequip, craft)
}
INTENT_UNKNOWN = "INTENT_UNKNOWN"


# --- SpaCy Model Loading ---
NLP_EN = None
NLP_RU = None

def load_spacy_model_en():
    global NLP_EN
    if NLP_EN is None:
        try:
            NLP_EN = spacy.load('en_core_web_sm')
        except OSError:
            print("Downloading en_core_web_sm model...")
            try:
                spacy.cli.download('en_core_web_sm')
                NLP_EN = spacy.load('en_core_web_sm')
            except Exception as e:
                print(f"Failed to download/load en_core_web_sm: {e}")
                NLP_EN = None
    return NLP_EN

def load_spacy_model_ru():
    global NLP_RU
    if NLP_RU is None:
        try:
            NLP_RU = spacy.load('ru_core_news_sm')
        except OSError:
            print("Downloading ru_core_news_sm model...")
            try:
                spacy.cli.download('ru_core_news_sm')
                NLP_RU = spacy.load('ru_core_news_sm')
            except Exception as e:
                print(f"Failed to download/load ru_core_news_sm: {e}")
                NLP_RU = None
    return NLP_RU

# --- Keyword Dictionaries (can be used by SpaCy logic later or alongside) ---
INTENT_KEYWORDS_EN = {
    "move": ["move", "go", "walk", "head", "proceed", "travel"],
    "look": ["look", "examine", "inspect", "view", "observe", "scan", "check"],
    "attack": ["attack", "fight", "hit", "strike", "assault"],
    "talk": ["talk", "speak", "chat", "ask", "converse"],
    "use_skill": ["use skill", "cast skill", "activate skill"],
    "pickup": ["pickup", "take", "get", "collect", "grab"],
    "use_item": ["use", "apply", "consume", "equip"],
    "search": ["search", "explore", "look for", "find"],
    "open": ["open", "unseal"],
    "close": ["close", "seal"],
    "drop": ["drop", "leave", "discard"],
}

INTENT_KEYWORDS_RU = {
    "move": ["иди", "двигайся", "шагай", "ступай", "отправляйся", "переместись", "идти"],
    "look": ["смотри", "осмотри", "глянь", "исследуй", "проверь", "оглядись", "смотреть"],
    "attack": ["атакуй", "дерись", "ударь", "бей", "напади", "атаковать"],
    "talk": ["говори", "поговори", "спроси", "болтай", "общайся", "разговаривай", "спросить"],
    "use_skill": ["используй умение", "примени умение", "активируй умение", "кастуй умение"],
    "pickup": ["подбери", "возьми", "собери", "хватай", "получи", "взять"],
    "use_item": ["используй", "примени", "съешь", "надень", "экипируй", "использовать"],
    "search": ["ищи", "обыщи", "исследуй", "найди", "поищи", "искать"],
    "open": ["открой", "распечатай"],
    "close": ["закрой", "запечатай"],
    "drop": ["брось", "выброси", "оставь"],
}

# Define TypedDicts for structured action data
class PlayerActionEntity(TypedDict, total=False): # Use total=False if some keys are optional
    id: Optional[str]
    name: str
    type: str
    lang: str
    intent_context: Optional[str] # If this key might exist from NLUDataService

class PlayerActionData(TypedDict):
    intent: Optional[str]
    entities: List[PlayerActionEntity] # Use the more specific entity type
    original_text: str
    processed_tokens: List[Dict[str, str]]
    primary_target_entity: Optional[PlayerActionEntity]


# Old Regex patterns and _find_matching_db_entity are removed as SpaCy PhraseMatcher is primary.

async def parse_player_action(
    text: str,
    language: str,
    guild_id: str,
    game_log_manager: Optional[GameLogManager] = None,
    nlu_data_service: Optional['NLUDataService'] = None
) -> Optional[PlayerActionData]: # Return type changed to PlayerActionData
    raw_input_text = text

    # Initialize with the structure of PlayerActionData
    action_data: PlayerActionData = { # Use PlayerActionData type
        'intent': None,
        'entities': [],
        'original_text': raw_input_text,
        'processed_tokens': [],
        'primary_target_entity': None # Ensure all keys from TypedDict are present
    }

    nlp = None
    if language == "en":
        nlp = load_spacy_model_en()
    elif language == "ru":
        nlp = load_spacy_model_ru()

    if not nlp:
        if game_log_manager:
            await game_log_manager.log_event(guild_id, "NLU_ERROR", {"error": f"SpaCy model not loaded for language: {language}"})
        return None

    doc = nlp(text)
    action_data['processed_tokens'] = [{"text": t.text, "lemma": t.lemma_, "pos": t.pos_} for t in doc]

    # --- 1. Entity Recognition ---
    recognized_entities: List[Dict[str, Any]] = []
    game_entities: Dict[str, List[Dict[str, Any]]] = {}

    if nlu_data_service:
        game_entities = await nlu_data_service.get_game_entities(guild_id, language)

    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    entity_map: Dict[str, Dict[str, Any]] = {}

    for entity_type, entities_list in game_entities.items():
        for entity_data in entities_list:
            patterns = [nlp.make_doc(entity_data['name'])]
            match_id = f"{entity_type.upper()}_{entity_data['id']}"
            matcher.add(match_id, patterns)
            entity_map[match_id] = entity_data

    matches = matcher(doc)
    for match_id, start, end in matches:
        matched_entity_data = entity_map[nlp.vocab.strings[match_id]]
        recognized_entities.append({
            "id": matched_entity_data['id'],
            "name": doc[start:end].text,
            "type": matched_entity_data['type'],
            "lang": matched_entity_data['lang']
        })
    action_data['entities'] = recognized_entities # Keep all initially, action_verb will be filtered

    # --- 2. Intent Classification ---
    # Prioritize Action Verbs from Recognized Entities
    verb_entities_to_remove_indices = []
    for i, entity in enumerate(recognized_entities):
        if entity.get('type') == 'action_verb':
            raw_intent = entity.get('intent_context') # From NLUDataService's GameEntity
            if raw_intent:
                action_data['intent'] = INTENT_MAP.get(raw_intent, INTENT_UNKNOWN)
                verb_entities_to_remove_indices.append(i)
                # For now, use the first action_verb found. Could be extended for priority.
                break

    # Remove action_verb entities from the final entity list
    if verb_entities_to_remove_indices:
        action_data['entities'] = [entity for i, entity in enumerate(recognized_entities) if i not in verb_entities_to_remove_indices]


    # Fallback to Keyword-Based Intent Classification if no intent from action_verb
    if not action_data['intent']:
        lemmatized_tokens = [token.lemma_.lower() for token in doc]
        current_keywords = INTENT_KEYWORDS_EN if language == "en" else INTENT_KEYWORDS_RU

        def has_keyword(lemmas: List[str], intent_key: str) -> bool:
            return any(lemma in current_keywords.get(intent_key, []) for lemma in lemmas)

        # Order matters for fallback: more specific checks first
        if has_keyword(lemmatized_tokens, "use_skill"):
            # Could add check: if any(e['type'] == 'skill' for e in recognized_entities):
            action_data['intent'] = INTENT_MAP.get("use_skill")

        elif has_keyword(lemmatized_tokens, "use_item"): # "use" is a common keyword
            item_entity = next((e for e in recognized_entities if e['type'] == 'item'), None)
            if item_entity:
                action_data['intent'] = INTENT_MAP.get("use_item")
            # If "use" but no item, it might be caught by a more generic "use" action_verb later if defined
            # or remain unclassified by keywords.

        elif has_keyword(lemmatized_tokens, "attack"):
            if any(e['type'] == 'npc' for e in recognized_entities) or any(e['type'] == 'player' for e in recognized_entities): # Allow attacking players too
                action_data['intent'] = INTENT_MAP.get("attack")

        elif has_keyword(lemmatized_tokens, "talk"):
            if any(e['type'] == 'npc' for e in recognized_entities): # Usually talk to NPCs
                action_data['intent'] = INTENT_MAP.get("talk")

        elif has_keyword(lemmatized_tokens, "pickup"):
            if any(e['type'] == 'item' for e in recognized_entities):
                action_data['intent'] = INTENT_MAP.get("pickup")

        elif has_keyword(lemmatized_tokens, "drop"):
             if any(e['type'] == 'item' for e in recognized_entities):
                action_data['intent'] = INTENT_MAP.get("drop")

        elif has_keyword(lemmatized_tokens, "move"):
            action_data['intent'] = INTENT_MAP.get("move")
            # Add direction entities if specific direction words are found
            for token in doc:
                direction_lemma = token.lemma_.lower()
                if direction_lemma in ["north", "south", "east", "west", "up", "down", "север", "юг", "восток", "запад", "вверх", "вниз"]:
                    # Ensure direction entity isn't already added by PhraseMatcher (if directions are in NLUDataService)
                    if not any(e['type'] == 'direction' and e['name'] == direction_lemma for e in action_data['entities']):
                        action_data['entities'].append({"id": None, "name": direction_lemma, "type": "direction", "lang": language, "intent_context": None})
                    break

        elif has_keyword(lemmatized_tokens, "look"):
            action_data['intent'] = INTENT_MAP.get("look")

        elif has_keyword(lemmatized_tokens, "search"):
            action_data['intent'] = INTENT_MAP.get("search")

        elif has_keyword(lemmatized_tokens, "open"):
            action_data['intent'] = INTENT_MAP.get("open")

        elif has_keyword(lemmatized_tokens, "close"):
            action_data['intent'] = INTENT_MAP.get("close")


    # If still no intent, set to UNKNOWN
    if not action_data['intent']:
        action_data['intent'] = INTENT_UNKNOWN

    # --- 3. Identify Primary Target Entity (Simplified) ---
    action_data['primary_target_entity'] = None
    current_intent = action_data['intent']
    # Use action_data['entities'] as it's already filtered from action_verbs
    remaining_entities = action_data['entities']

    if current_intent in [INTENT_MAP.get("attack"), INTENT_MAP.get("talk")]:
        # Prioritize NPC, then Player as targets
        target_types = ["npc", "player"]
        for t_type in target_types:
            potential_targets = [e for e in remaining_entities if e['type'] == t_type]
            if len(potential_targets) == 1:
                action_data['primary_target_entity'] = potential_targets[0]
                break # Found primary target
            elif len(potential_targets) > 1:
                # Ambiguous target, could log or set a special marker
                # For now, primary_target_entity remains None if ambiguous
                print(f"NLU Parser: Ambiguous target for {current_intent}. Options: {potential_targets}") # Replace with logger
                break

    elif current_intent in [INTENT_MAP.get("look"), INTENT_MAP.get("pickup"), INTENT_MAP.get("use_item"), INTENT_MAP.get("open"), INTENT_MAP.get("close"), INTENT_MAP.get("drop")]:
        # Broader set of types for these interactions
        # Order can define priority if multiple types are present (e.g., prefer item over feature if both matched same text)
        target_types = ["item", "location_feature", "npc", "player", "location_tag", "location"]
        found_targets = []
        for t_type in target_types:
            potential_targets = [e for e in remaining_entities if e['type'] == t_type]
            if potential_targets:
                found_targets.extend(potential_targets)
        
        if len(found_targets) == 1:
            action_data['primary_target_entity'] = found_targets[0]
        elif len(found_targets) > 1:
            # Ambiguity: if "look sword" and "sword" is an item and also a feature name.
            # Simple approach: take the first one found based on target_types priority.
            # A more advanced system might use proximity to verb or other heuristics.
            action_data['primary_target_entity'] = found_targets[0]
            print(f"NLU Parser: Ambiguous target for {current_intent}, selected first based on type priority. Options: {found_targets}") # Replace with logger


    elif current_intent == INTENT_MAP.get("move"):
        # For move, the primary target might be a location or a direction.
        # Directions are already in 'entities'. If a location is also there, prefer it.
        location_target = next((e for e in remaining_entities if e['type'] == 'location'), None)
        if location_target:
            action_data['primary_target_entity'] = location_target
        # If no location entity, but there's a direction entity, that's handled by game logic via action_data['entities']

    # --- Logging ---
    if game_log_manager:
        log_details = {
            "raw_text": raw_input_text, "language": language,
            "parsed_intent": action_data['intent'], "parsed_entities": action_data['entities'],
            "processed_tokens": action_data['processed_tokens'],
            "recognition_successful": bool(action_data['intent']),
            "parser_type": "spacy_custom_rules"
        }
        log_message_params = {
            "intent": action_data['intent'] if action_data['intent'] else "None",
            "entities_count": len(action_data['entities'])
        }
        await game_log_manager.log_event(
            guild_id=guild_id, event_type="NLU_RESULT", details=log_details,
            player_id=None, message_key="log.nlu.result_spacy_custom",
            message_params=log_message_params
        )

    if action_data['intent']:
        return action_data
    return None

if __name__ == '__main__':
    from bot.services.nlu_data_service import NLUDataService

    dummy_guild_id = "test_guild"
    nlu_data_service_instance = NLUDataService()

    async def run_tests():
        print("--- English Tests (SpaCy Custom Rules) ---")
        test_phrases_en = [
            "go north", "move to the Forest", "look", "examine the Sword",
            "attack Faelan", "talk to the Mock Guard", "pickup the Healing Potion",
            "use Sword on Faelan", "use skill Fireball on Mock Guard", "search Forest",
            "search for Old Tree in Forest", "use non_existent_item", "gibberish command"
        ]
        for phrase in test_phrases_en:
            result = await parse_player_action(phrase, "en", dummy_guild_id, nlu_data_service=nlu_data_service_instance)
            print(f"\nInput (en): '{phrase}'")
            if result:
                print(f"  Intent: {result['intent']}")
                print(f"  Entities: {result['entities']}")
            else:
                print("  No intent found.")

        print("\n--- Russian Tests (SpaCy Custom Rules) ---")
        test_phrases_ru = [
            "иди на север", "переместись в Лес", "смотри", "осмотри Меч",
            "атакуй Фаэлан", "поговори с Макетный Страж", "подбери Зелье лечения",
            "используй Меч на Фаэлан", "используй умение Огненный шар на Макетный Страж",
            "ищи в Лес", "ищи Старое Дерево в Лес"
        ]
        for phrase in test_phrases_ru:
            result = await parse_player_action(phrase, "ru", dummy_guild_id, nlu_data_service=nlu_data_service_instance)
            print(f"\nInput (ru): '{phrase}'")
            if result:
                print(f"  Intent: {result['intent']}")
                print(f"  Entities: {result['entities']}")
            else:
                print("  No intent found.")

        print("\n--- Testing SpaCy Model Loading (only if models are not already downloaded by a previous run) ---")
        print("Ensuring English model is loaded (may show download if first time):")
        load_spacy_model_en()
        print("Ensuring Russian model is loaded (may show download if first time):")
        load_spacy_model_ru()
        print("Model loading check complete.")

    import asyncio
    asyncio.run(run_tests())

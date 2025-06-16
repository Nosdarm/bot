# bot/nlu/player_action_parser.py
import re
from typing import Optional, List, Dict, Any # Tuple removed, Union added later if needed for return type
import spacy
from spacy.matcher import PhraseMatcher # Import PhraseMatcher
# Forward declare NLUDataService if not importing directly at top level for main parser logic
# from bot.services.nlu_data_service import NLUDataService
from bot.game.managers.game_log_manager import GameLogManager


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
}

# Keywords for intra-location interactions
# Using phrases as keys, mapped to intent. Longer phrases should be ordered first if there's ambiguity.
INTERACTION_KEYWORDS_EN = {
    "look at": "examine_object",
    "examine": "examine_object",
    "inspect": "examine_object",
    "pick up": "take_item",
    "take": "take_item",
    "get": "take_item", # 'get' is broad, but in "get X", X is likely an item
    "use": "use_item", # Broad, might need context. "use X on Y" is more complex.
    "open": "open_container",
    "search": "search_container_or_area", # Overlaps with general search, context might be needed
    "talk to": "initiate_dialogue",
}

INTERACTION_KEYWORDS_RU = {
    "посмотреть на": "examine_object",
    "осмотреть": "examine_object",
    "исследовать": "examine_object", # Can also be general look/search
    "подобрать": "take_item",
    "взять": "take_item",
    "получить": "take_item", # 'получить' is broad
    "использовать": "use_item",
    "открыть": "open_container",
    "обыскать": "search_container_or_area", # Overlaps
    "поговорить с": "initiate_dialogue",
}


# (Old PATTERNS_EN, PATTERNS_RU, and _find_matching_db_entity can be removed if not used by new logic)
# For now, they are kept as they are not in the direct path of parse_player_action's SpaCy logic.
# If they are confirmed unused after full SpaCy implementation, they can be cleaned up.
PATTERNS_EN = {
    "move_to_location": re.compile(r"(?:move|go|walk|head|travel)\s+(?:to\s+)?(.+)", re.IGNORECASE),
    "move_direction": re.compile(r"(?:move|go|walk|head|travel)\s+(north|south|east|west|up|down|forward|backward|left|right)", re.IGNORECASE),
    "attack_target": re.compile(r"(?:attack|fight|hit|strike)\s+(.+)", re.IGNORECASE),
    # ... (other patterns can be kept or removed as needed)
}
PATTERNS_RU = {
     "move_to_location": re.compile(r"(?:иди|двигайся|переместись|отправляйся)\s+(?:в\s+|на\s+)?(.+)", re.IGNORECASE),
    # ...
}
def _find_matching_db_entity(text_entity_name: str, db_entities: List[Dict[str, Any]], entity_type_name: str) -> Optional[Dict[str, str]]:
    if not db_entities: return None
    text_entity_name_lower = text_entity_name.lower()
    for db_entity in db_entities:
        if db_entity['name'].lower() == text_entity_name_lower:
            return {"type": entity_type_name, "id": db_entity['id'], "name": db_entity['name']}
    return None


async def parse_player_action(
    text: str,
    language: str,
    guild_id: str,
    game_log_manager: Optional[GameLogManager] = None,
    nlu_data_service: Optional['NLUDataService'] = None
) -> Optional[Dict[str, Any]]:
    raw_input_text = text

    action_data: Dict[str, Any] = {
        'intent': None,
        'entities': [],
        'original_text': raw_input_text,
        'processed_tokens': []
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
    action_data['entities'] = recognized_entities

    # --- Old Regex/Keyword logic has been removed ---

    # --- 2. Intent Classification (Rule-Based) ---
    lemmatized_tokens = [token.lemma_.lower() for token in doc]
    current_general_keywords = INTENT_KEYWORDS_EN if language == "en" else INTENT_KEYWORDS_RU
    current_interaction_keywords = INTERACTION_KEYWORDS_EN if language == "en" else INTERACTION_KEYWORDS_RU

    # --- Start: New Interaction Intent Logic ---
    # Prioritize longer, more specific phrases from INTERACTION_KEYWORDS
    # Sort keywords by length descending to match longer phrases first
    # For example, "look at" before "look" if "look" is also an interaction keyword.

    # Normalize raw text for phrase matching
    normalized_raw_text = raw_input_text.lower().strip()

    sorted_interaction_phrases = sorted(current_interaction_keywords.keys(), key=len, reverse=True)

    for phrase in sorted_interaction_phrases:
        if normalized_raw_text.startswith(phrase):
            intent = current_interaction_keywords[phrase]
            action_data['intent'] = intent

            target_name = normalized_raw_text[len(phrase):].strip()

            # Basic article/preposition stripping for target_name if needed (mostly for English)
            if language == "en":
                if target_name.startswith("the "): target_name = target_name[4:]
                elif target_name.startswith("an "): target_name = target_name[3:]
                elif target_name.startswith("a "): target_name = target_name[2:]
                # Could add "to ", "with " etc. if the keyword phrase itself doesn't include them.

            if target_name:
                entity_type = "target_object_name"
                if intent == "initiate_dialogue": # "talk to" implies NPC
                    entity_type = "target_npc_name"

                action_data['entities'].append({
                    "id": None, # ID will be resolved by game logic based on name and context
                    "name": target_name,
                    "type": entity_type,
                    "lang": language
                })
            # If an interaction intent is matched, we might decide to return early,
            # or let it fall through to general keyword matching if no target was found.
            # For now, if a phrase matches, we assume this is the primary intent.
            if action_data['intent']:
                break # Found specific interaction intent, stop checking other interaction phrases.
    
    # --- End: New Interaction Intent Logic ---

    # Fallback or additional intent classification using general keywords (mostly single-word verbs)
    # This existing logic will only run if no specific interaction phrase was matched above.
    if not action_data['intent']:
        def has_general_keyword(lemmas: List[str], intent_key: str) -> bool:
            return any(lemma in current_general_keywords.get(intent_key, []) for lemma in lemmas)

        if has_general_keyword(lemmatized_tokens, "use_item") or has_general_keyword(lemmatized_tokens, "use_skill"):
            item_entity = next((e for e in recognized_entities if e['type'] == 'item'), None)
            skill_entity = next((e for e in recognized_entities if e['type'] == 'skill'), None)
            if skill_entity: action_data['intent'] = "use_skill"
            elif item_entity: action_data['intent'] = "use_item"
            # If no specific item/skill entity found, but "use" keyword present, it's ambiguous.
            # The prompt for item generation specified "use" for use_item.

        if not action_data['intent'] and has_general_keyword(lemmatized_tokens, "attack"):
            if any(e['type'] == 'npc' for e in recognized_entities): action_data['intent'] = "attack"

        # "talk to" is handled by INTERACTION_KEYWORDS. If just "talk" (lemma) is found, it might be ambiguous
        # or could be a general "talk" intent without a specific target yet.
        # For now, let's assume "talk" (single word) without a target is not specific enough
        # unless an NPC entity was already recognized by PhraseMatcher.
        if not action_data['intent'] and has_general_keyword(lemmatized_tokens, "talk"):
             if any(e['type'] == 'npc' for e in recognized_entities): action_data['intent'] = "initiate_dialogue" # or just "talk"

        if not action_data['intent'] and has_general_keyword(lemmatized_tokens, "pickup"):
            if any(e['type'] == 'item' for e in recognized_entities): action_data['intent'] = "take_item" # Changed to match interaction key

        if not action_data['intent'] and has_general_keyword(lemmatized_tokens, "move"):
            action_data['intent'] = "move"
            # Attempt to extract a target identifier after the move verb
        # This is a simple approach; more complex NLU would involve dependency parsing.

        move_verb_indices = [i for i, token in enumerate(doc) if token.lemma_.lower() in current_keywords.get("move", [])]

        target_identifier = ""
        if move_verb_indices:
            # Take the text after the first identified move verb
            # This is a simplification. A proper solution might need to find the main verb of the sentence.
            first_move_verb_idx = move_verb_indices[0]

            # Start looking for target from the token after the verb
            target_start_idx = first_move_verb_idx + 1

            # Basic preposition skipping (optional, can be refined)
            # Example: "go to the forest" -> "the forest"
            # Example: "иди в лес" -> "лес"
            prepositions_to_skip_en = ["to", "into", "towards"]
            prepositions_to_skip_ru = ["в", "на", "к", "до"]
            prepositions_to_skip = prepositions_to_skip_en if language == "en" else prepositions_to_skip_ru

            if target_start_idx < len(doc) and doc[target_start_idx].lemma_.lower() in prepositions_to_skip:
                target_start_idx += 1
                # Optional: skip articles like "the", "a", "an" after preposition
                if language == "en" and target_start_idx < len(doc) and doc[target_start_idx].lemma_.lower() in ["the", "a", "an"]:
                    target_start_idx +=1

            if target_start_idx < len(doc):
                # Join the rest of the tokens to form the target identifier
                target_identifier = doc[target_start_idx:].text.strip()

        if target_identifier:
            # Check if any recognized game entity matches the extracted target_identifier
            # This is useful if NLUDataService provided location names that were matched by PhraseMatcher
            # And those location names are part of the target_identifier.
            # For example, if text is "go to Dark Forest" and "Dark Forest" is a recognized entity.

            # For now, we directly use the target_identifier.
            # LocationManager's handle_move_action will resolve if it's a direction, exit name, or location ID/name.
            action_data['entities'].append({
                "id": None, # ID will be resolved by LocationManager if it's a known location
                "name": target_identifier,
                "type": "target_location_identifier", # A generic type for the move target
                "lang": language
            })
        else:
            # If no specific target is extracted after the move verb, it might be an implicit "move forward" or error.
            # For now, if "move" intent is there but no target, we don't add a specific entity.
            # LocationManager might handle this as an error or a default action if applicable.
            pass


    if not action_data['intent'] and has_keyword(lemmatized_tokens, "look"):
        action_data['intent'] = "look"
        
    if not action_data['intent'] and has_keyword(lemmatized_tokens, "search"):
        action_data['intent'] = "search"

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

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
    current_keywords = INTENT_KEYWORDS_EN if language == "en" else INTENT_KEYWORDS_RU

    def has_keyword(lemmas: List[str], intent_key: str) -> bool:
        return any(lemma in current_keywords.get(intent_key, []) for lemma in lemmas)

    if has_keyword(lemmatized_tokens, "use_item") or has_keyword(lemmatized_tokens, "use_skill"):
        item_entity = next((e for e in recognized_entities if e['type'] == 'item'), None)
        skill_entity = next((e for e in recognized_entities if e['type'] == 'skill'), None)
        if skill_entity: action_data['intent'] = "use_skill"
        elif item_entity: action_data['intent'] = "use_item"

    if not action_data['intent'] and has_keyword(lemmatized_tokens, "attack"):
        if any(e['type'] == 'npc' for e in recognized_entities): action_data['intent'] = "attack"
    
    if not action_data['intent'] and has_keyword(lemmatized_tokens, "talk"):
        if any(e['type'] == 'npc' for e in recognized_entities): action_data['intent'] = "talk"

    if not action_data['intent'] and has_keyword(lemmatized_tokens, "pickup"):
        if any(e['type'] == 'item' for e in recognized_entities): action_data['intent'] = "pickup"

    if not action_data['intent'] and has_keyword(lemmatized_tokens, "move"):
        action_data['intent'] = "move"
        for token in doc:
            if token.lemma_.lower() in ["north", "south", "east", "west", "up", "down", "север", "юг", "восток", "запад", "вверх", "вниз"]:
                if not any(e['type'] == 'direction' and e['name'] == token.lemma_.lower() for e in action_data['entities']):
                    action_data['entities'].append({"id": None, "name": token.lemma_.lower(), "type": "direction", "lang": language})
                break

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

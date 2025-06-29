import spacy
from spacy.matcher import PhraseMatcher

nlp_en = spacy.load("en_core_web_sm")
# nlp_ru = spacy.load("ru_core_news_sm") # Example for Russian

def parse_player_action(text: str, language: str, guild_id: str, game_log_manager, nlu_data_service):
    if language == "en":
        nlp = nlp_en
    # elif language == "ru":
    #     nlp = nlp_ru
    else:
        game_log_manager.log_event(guild_id, "NLU_ERROR", {"error": f"Unsupported language: {language}"})
        return None

    doc = nlp(text)

    # Extract entities
    # ...

    # Determine intent
    # ...

    return {
        "intent": "UNKNOWN",
        "entities": [],
        "primary_target_entity": None
    }

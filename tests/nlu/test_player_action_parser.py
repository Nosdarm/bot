import pytest

from unittest.mock import AsyncMock, MagicMock, patch, call
import spacy # Import for type hinting if needed, and for spacy.cli.download

# Module to test
from bot.nlu import player_action_parser
from bot.nlu.player_action_parser import INTENT_MAP, INTENT_UNKNOWN

# --- Fixtures ---

@pytest.fixture
def mock_nlu_data_service():
    service = AsyncMock(name="MockNLUDataService")
    service.get_game_entities = AsyncMock(return_value={}) # Default to no entities
    return service

@pytest.fixture
def mock_game_log_manager():
    manager = AsyncMock(name="MockGameLogManager")
    manager.log_event = AsyncMock()
    return manager

# Mock SpaCy models to avoid actual loading/downloading during tests
@pytest.fixture
def mock_spacy_nlp_en():
    nlp_en = MagicMock(name="MockSpacyModelEN")
    # Simple doc mock that returns tokens with text, lemma_, pos_
    def process_text_en(text):
        doc_mock = MagicMock()
        # Crude tokenization for testing purposes
        tokens = []
        for word in text.split():
            token_mock = MagicMock()
            token_mock.text = word
            token_mock.lemma_ = word.lower() # Simplified lemma
            token_mock.pos_ = "NOUN" if word[0].isupper() else "VERB" # Simplified POS
            tokens.append(token_mock)
        doc_mock.__iter__.return_value = iter(tokens) # Make the doc iterable
        doc_mock.vocab = MagicMock() # PhraseMatcher needs vocab
        doc_mock.vocab.strings = MagicMock() # And strings on vocab
        doc_mock.vocab.strings.__getitem__.side_effect = lambda x: x # Simple echo for match_id
        doc_mock.make_doc = lambda t: MagicMock(text=t) # For PhraseMatcher patterns
        return doc_mock
    nlp_en.side_effect = process_text_en # Make the mock callable like nlp(text)
    return nlp_en

@pytest.fixture
def mock_spacy_nlp_ru():
    nlp_ru = MagicMock(name="MockSpacyModelRU")
    def process_text_ru(text): # Similar to English version
        doc_mock = MagicMock()
        tokens = []
        for word in text.split():
            token_mock = MagicMock()
            token_mock.text = word
            token_mock.lemma_ = word.lower()
            token_mock.pos_ = "NOUN" if word[0].isupper() else "VERB"
            tokens.append(token_mock)
        doc_mock.__iter__.return_value = iter(tokens)
        doc_mock.vocab = MagicMock()
        doc_mock.vocab.strings = MagicMock()
        doc_mock.vocab.strings.__getitem__.side_effect = lambda x: x
        doc_mock.make_doc = lambda t: MagicMock(text=t)
        return doc_mock
    nlp_ru.side_effect = process_text_ru
    return nlp_ru

# --- Tests ---

@pytest.mark.asyncio
@patch('bot.nlu.player_action_parser.spacy.load')
async def test_parse_guild_id_usage_for_entities(
    mock_spacy_load: MagicMock,
    mock_nlu_data_service: AsyncMock,
    mock_game_log_manager: AsyncMock,
    mock_spacy_nlp_en: MagicMock # Fixture providing the callable mock
):
    mock_spacy_load.return_value = mock_spacy_nlp_en # spacy.load('en_core_web_sm') returns our mock
    guild_id_test = "test_guild_123"

    await player_action_parser.parse_player_action(
        text="look at the sword",
        language="en",
        guild_id=guild_id_test,
        game_log_manager=mock_game_log_manager,
        nlu_data_service=mock_nlu_data_service
    )

    mock_nlu_data_service.get_game_entities.assert_awaited_once_with(guild_id_test, "en")

@pytest.mark.asyncio
@patch('bot.nlu.player_action_parser.spacy.load')
async def test_parse_with_action_verb_entity(
    mock_spacy_load: MagicMock,
    mock_nlu_data_service: AsyncMock,
    mock_game_log_manager: AsyncMock,
    mock_spacy_nlp_en: MagicMock
):
    mock_spacy_load.return_value = mock_spacy_nlp_en
    guild_id_test = "guild_action_verb"

    # NLUDataService returns an action_verb and another entity
    mock_nlu_data_service.get_game_entities.return_value = {
        "action_verb": [{"id": "verb_attack", "name": "attack", "type": "action_verb", "intent_context": "attack", "lang": "en"}],
        "npc": [{"id": "npc_goblin", "name": "goblin", "type": "npc", "lang": "en"}]
    }
    # PhraseMatcher will find "attack" and "goblin"
    # Mock spacy doc to simulate tokens "attack", "the", "goblin"
    mock_doc_tokens = [MagicMock(text="attack", lemma_="attack", pos_="VERB"), MagicMock(text="the", lemma_="the", pos_="DET"), MagicMock(text="goblin", lemma_="goblin", pos_="NOUN")]
    mock_spacy_nlp_en.return_value.__iter__.return_value = iter(mock_doc_tokens)


    # Simulate PhraseMatcher finding these based on the patterns from get_game_entities
    # The matcher is created inside parse_player_action. We need to ensure it "finds" things.
    # This requires more intricate mocking of PhraseMatcher or using a real one with mocked vocab.
    # For simplicity, let's assume the matcher works and focus on intent classification logic.
    # The current mock_nlp setup provides a basic doc.
    # The PhraseMatcher needs nlp.make_doc for patterns and doc for matching.
    # Patch PhraseMatcher if direct control is needed or ensure mock_nlp.make_doc and doc are compatible.

    # Simplified: Assume "attack" is matched as action_verb and "goblin" as npc by the internal PhraseMatcher
    # This test will rely on the PhraseMatcher being correctly set up by the SUT using the nlp mock.
    # The mock_nlu_data_service.get_game_entities is the key input here.

    # To properly test PhraseMatcher behavior with a mock nlp, PhraseMatcher itself might need to be patched,
    # or the nlp mock needs to be more sophisticated.
    # For this test, we'll assume the PhraseMatcher part correctly identifies entities based on get_game_entities.
    # The key is that 'action_verb' type entity sets the intent.

    with patch('spacy.matcher.PhraseMatcher') as MockPhraseMatcher:
        # Make the PhraseMatcher instance return our desired matches
        mock_matcher_instance = MockPhraseMatcher.return_value
        # match_id, start_token_index, end_token_index
        # Assume "attack" is token 0, "goblin" is token 2
        # The match_id string must be something PhraseMatcher can map back to our entity_map
        mock_matcher_instance.return_value = [
            (mock_spacy_nlp_en("").vocab.strings.add("ACTION_VERB_verb_attack"), 0, 1), # "attack"
            (mock_spacy_nlp_en("").vocab.strings.add("NPC_npc_goblin"), 2, 3)       # "goblin"
        ]


        action_data = await player_action_parser.parse_player_action(
            text="attack the goblin", language="en", guild_id=guild_id_test,
            nlu_data_service=mock_nlu_data_service, game_log_manager=mock_game_log_manager
        )

    assert action_data is not None
    assert action_data['intent'] == INTENT_MAP["attack"]
    # Action_verb should be removed from entities
    assert len(action_data['entities']) == 1
    assert action_data['entities'][0]['id'] == "npc_goblin"
    assert action_data['entities'][0]['type'] == "npc"
    assert action_data['primary_target_entity']['id'] == "npc_goblin"


@pytest.mark.asyncio
@patch('bot.nlu.player_action_parser.spacy.load')
async def test_parse_with_keyword_intent(
    mock_spacy_load: MagicMock,
    mock_nlu_data_service: AsyncMock, # No action_verbs returned
    mock_game_log_manager: AsyncMock,
    mock_spacy_nlp_en: MagicMock
):
    mock_spacy_load.return_value = mock_spacy_nlp_en
    mock_nlu_data_service.get_game_entities.return_value = { # No action_verbs
        "npc": [{"id": "npc_bandit", "name": "bandit", "type": "npc", "lang": "en"}]
    }
    mock_doc_tokens = [MagicMock(text="hit", lemma_="hit", pos_="VERB"), MagicMock(text="the", lemma_="the", pos_="DET"), MagicMock(text="bandit", lemma_="bandit", pos_="NOUN")]
    mock_spacy_nlp_en.return_value.__iter__.return_value = iter(mock_doc_tokens)


    with patch('spacy.matcher.PhraseMatcher') as MockPhraseMatcher:
        mock_matcher_instance = MockPhraseMatcher.return_value
        mock_matcher_instance.return_value = [
            (mock_spacy_nlp_en("").vocab.strings.add("NPC_npc_bandit"), 2, 3) # "bandit"
        ]

        action_data = await player_action_parser.parse_player_action(
            text="hit the bandit", language="en", guild_id="test_guild_kw",
            nlu_data_service=mock_nlu_data_service, game_log_manager=mock_game_log_manager
        )

    assert action_data is not None
    assert action_data['intent'] == INTENT_MAP["attack"] # "hit" is a keyword for "attack"
    assert len(action_data['entities']) == 1
    assert action_data['entities'][0]['id'] == "npc_bandit"
    assert action_data['primary_target_entity']['id'] == "npc_bandit"

@pytest.mark.asyncio
@patch('bot.nlu.player_action_parser.spacy.load')
async def test_parse_unknown_intent(
    mock_spacy_load: MagicMock,
    mock_nlu_data_service: AsyncMock,
    mock_game_log_manager: AsyncMock,
    mock_spacy_nlp_en: MagicMock
):
    mock_spacy_load.return_value = mock_spacy_nlp_en
    mock_nlu_data_service.get_game_entities.return_value = {} # No relevant entities
    mock_doc_tokens = [MagicMock(text="dance", lemma_="dance", pos_="VERB"), MagicMock(text="a", lemma_="a", pos_="DET"), MagicMock(text="jig", lemma_="jig", pos_="NOUN")]
    mock_spacy_nlp_en.return_value.__iter__.return_value = iter(mock_doc_tokens)

    with patch('spacy.matcher.PhraseMatcher') as MockPhraseMatcher:
        MockPhraseMatcher.return_value.return_value = [] # No entities matched

        action_data = await player_action_parser.parse_player_action(
            text="dance a jig", language="en", guild_id="test_guild_unknown",
            nlu_data_service=mock_nlu_data_service, game_log_manager=mock_game_log_manager
        )

    assert action_data is not None
    assert action_data['intent'] == INTENT_UNKNOWN
    assert len(action_data['entities']) == 0
    assert action_data['primary_target_entity'] is None


@pytest.mark.asyncio
@patch('bot.nlu.player_action_parser.spacy.load')
async def test_parse_no_spacy_model(
    mock_spacy_load: MagicMock,
    mock_nlu_data_service: AsyncMock,
    mock_game_log_manager: AsyncMock
):
    mock_spacy_load.return_value = None # Simulate model loading failure

    action_data = await player_action_parser.parse_player_action(
        text="any text", language="nonexistent_lang", guild_id="test_guild_no_model",
        nlu_data_service=mock_nlu_data_service, game_log_manager=mock_game_log_manager
    )

    assert action_data is None
    mock_game_log_manager.log_event.assert_awaited_once_with(
        "test_guild_no_model", "NLU_ERROR", {"error": "SpaCy model not loaded for language: nonexistent_lang"}
    )

print("DEBUG: tests/nlu/test_player_action_parser.py created.")

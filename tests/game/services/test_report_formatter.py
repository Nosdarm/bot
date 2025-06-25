import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Class to test
from bot.game.services.report_formatter import ReportFormatter, I18nUtilsWrapper

# Mocks for managers
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.item_manager import ItemManager

# --- Fixtures ---

@pytest.fixture
def mock_character_manager():
    manager = AsyncMock(spec=CharacterManager)
    manager.get_character = AsyncMock()
    return manager

@pytest.fixture
def mock_npc_manager():
    manager = AsyncMock(spec=NpcManager)
    manager.get_npc = AsyncMock()
    return manager

@pytest.fixture
def mock_item_manager():
    manager = AsyncMock(spec=ItemManager)
    manager.get_item_template_by_id = AsyncMock()
    return manager

@pytest.fixture
def mock_i18n_utils_module():
    module = MagicMock()
    module.get_localized_string = MagicMock(side_effect=lambda key, lang, **kwargs: f"i18n[{lang}]:{key} ({kwargs})" if kwargs else f"i18n[{lang}]:{key}")
    return module

@pytest.fixture
def report_formatter(
    mock_character_manager: CharacterManager,
    mock_npc_manager: NpcManager,
    mock_item_manager: ItemManager,
    mock_i18n_utils_module: MagicMock
) -> ReportFormatter:
    return ReportFormatter(
        character_manager=mock_character_manager,
        npc_manager=mock_npc_manager,
        item_manager=mock_item_manager,
        i18n_module=mock_i18n_utils_module
    )

# --- Tests for ReportFormatter._get_entity_name ---

@pytest.mark.asyncio
async def test_get_entity_name_player_found(report_formatter: ReportFormatter, mock_character_manager: AsyncMock):
    guild_id = "g1"
    player_id = "p1"
    mock_player = MagicMock()
    mock_player.name_i18n = {"en": "Test Player", "ru": "Тестовый Игрок"}
    mock_character_manager.get_character.return_value = mock_player

    name_en = await report_formatter._get_entity_name(player_id, "PLAYER", "en", guild_id)
    name_ru = await report_formatter._get_entity_name(player_id, "PLAYER", "ru", guild_id)

    assert name_en == "Test Player"
    assert name_ru == "Тестовый Игрок"
    mock_character_manager.get_character.assert_any_call(guild_id, player_id)

@pytest.mark.asyncio
async def test_get_entity_name_npc_not_found(report_formatter: ReportFormatter, mock_npc_manager: AsyncMock):
    guild_id = "g1"
    npc_id = "npc_unknown"
    mock_npc_manager.get_npc.return_value = None

    name = await report_formatter._get_entity_name(npc_id, "NPC", "en", guild_id)
    assert name == npc_id # Should return ID as fallback
    mock_npc_manager.get_npc.assert_awaited_once_with(guild_id, npc_id)

@pytest.mark.asyncio
async def test_get_entity_name_no_guild_id(report_formatter: ReportFormatter, caplog):
    player_id = "p1"
    # No guild_id passed
    name = await report_formatter._get_entity_name(player_id, "PLAYER", "en", None)
    assert name == player_id # Fallback to ID
    assert "Warning: _get_entity_name called without guild_id" in caplog.text

# --- Tests for ReportFormatter.format_story_log_entry ---

@pytest.mark.asyncio
async def test_format_log_entry_basic(report_formatter: ReportFormatter, mock_i18n_utils_module: MagicMock):
    guild_id = "guild_log_test"
    log_entry = {
        "guild_id": guild_id,
        "description_key": "event.player.move", # e.g., "i18n[en]:event.player.move ({'source_name': 'Player1', 'target_name': 'Tavern'})"
        "description_params_json": json.dumps({"param_source_id": "p1", "param_source_type": "PLAYER", "param_target_id": "loc_tavern", "param_target_type": "LOCATION"}),
        "details": json.dumps({}) # No AI narrative for this test
    }
    # Mock _get_entity_name behavior
    async def get_name_side_effect(entity_id, entity_type, lang, gid):
        if entity_id == "p1" and entity_type == "PLAYER": return "PlayerOne"
        if entity_id == "loc_tavern" and entity_type == "LOCATION": return "The Cozy Tavern" # Assume LOCATION type is handled
        return entity_id
    report_formatter._get_entity_name = AsyncMock(side_effect=get_name_side_effect)

    # Mock i18n.get_localized_string to return a specific format
    mock_i18n_utils_module.get_localized_string.side_effect = lambda key, lang, **kwargs: f"Formatted: {key} with {kwargs['source_name']} to {kwargs['target_name']} in {lang}"

    formatted_str = await report_formatter.format_story_log_entry(log_entry, "en")

    report_formatter._get_entity_name.assert_any_call("p1", "PLAYER", "en", guild_id)
    # Assuming LOCATION type would be handled by _get_entity_name with a LocationManager mock
    # For this test, we are directly mocking the output of _get_entity_name.
    # If LocationManager was used, we'd mock that instead for "loc_tavern".
    # The current _get_entity_name doesn't handle "LOCATION" type explicitly, needs ItemManager for "ITEM".
    # Let's assume for this test, "LOCATION" type is handled or params_for_i18n uses IDs directly if name not found.
    # The current code for params_for_i18n uses source_name/target_name directly.

    mock_i18n_utils_module.get_localized_string.assert_called_once_with(
        "event.player.move", "en",
        source_name="PlayerOne", target_name="The Cozy Tavern" # Expected based on mocked _get_entity_name
    )
    assert formatted_str == "Formatted: event.player.move with PlayerOne to The Cozy Tavern in en"

@pytest.mark.asyncio
async def test_format_log_entry_with_ai_narrative(report_formatter: ReportFormatter, mock_i18n_utils_module: MagicMock):
    guild_id = "guild_narrative"
    log_entry = {
        "guild_id": guild_id,
        "description_key": "event.combat.hit",
        "description_params_json": json.dumps({"param_source_id": "p1", "param_source_type": "PLAYER", "param_target_id": "npc1", "param_target_type": "NPC", "param_damage": 10}),
        "details": json.dumps({"ai_narrative_en": "The sword flashes, connecting soundly!", "ai_narrative_ru": "Меч сверкнул, попав точно!"})
    }
    report_formatter._get_entity_name = AsyncMock(side_effect=lambda eid, etype, lang, gid: f"{etype}_{eid}_{lang}")
    mock_i18n_utils_module.get_localized_string.return_value = "Player p1_en hits NPC npc1_en for 10 damage."

    formatted_str_en = await report_formatter.format_story_log_entry(log_entry, "en")
    assert formatted_str_en == "Player p1_en hits NPC npc1_en for 10 damage. The sword flashes, connecting soundly!"

    formatted_str_ru = await report_formatter.format_story_log_entry(log_entry, "ru")
    assert formatted_str_ru == "Player p1_ru hits NPC npc1_ru for 10 damage. Меч сверкнул, попав точно!" # Assuming get_localized_string also uses 'ru'

@pytest.mark.asyncio
async def test_format_log_entry_uses_default_lang_for_narrative_fallback(report_formatter: ReportFormatter, mock_i18n_utils_module: MagicMock):
    guild_id = "guild_narrative_fallback"
    log_entry = {
        "guild_id": guild_id,
        "description_key": "event.generic",
        "description_params_json": json.dumps({}),
        "details": json.dumps({"ai_narrative_en": "English narrative only."}) # Only EN narrative
    }
    report_formatter._get_entity_name = AsyncMock(return_value="Entity")
    mock_i18n_utils_module.get_localized_string.return_value = "Generic event happened."
    report_formatter.i18n.default_lang = "en" # Ensure default_lang is 'en'

    # Request "ru", should fallback to "en" for narrative
    formatted_str_ru = await report_formatter.format_story_log_entry(log_entry, "ru")
    assert formatted_str_ru == "Generic event happened. English narrative only."

# --- Tests for ReportFormatter.generate_turn_report ---
@pytest.mark.asyncio
async def test_generate_turn_report_multiple_entries(report_formatter: ReportFormatter):
    guild_id = "guild_turn_report"
    lang = "en"
    log_entries = [
        {"guild_id": guild_id, "description_key": "key1", "description_params_json": json.dumps({"p":1}), "details": json.dumps({"ai_narrative_en": "Nar1"})},
        {"description_key": "key2", "description_params_json": json.dumps({"p":2}), "details": json.dumps({"ai_narrative_en": "Nar2"})} # Missing guild_id intentionally
    ]

    # Mock format_story_log_entry to check its inputs and provide varied outputs
    async def format_entry_side_effect(entry, lang_code):
        key = entry.get("description_key")
        narrative = json.loads(entry.get("details","{}")).get(f"ai_narrative_{lang_code}", "")
        return f"Formatted {key} in {lang_code}. {narrative}"

    report_formatter.format_story_log_entry = AsyncMock(side_effect=format_entry_side_effect)

    report = await report_formatter.generate_turn_report(guild_id, lang, log_entries)

    assert report_formatter.format_story_log_entry.call_count == 2
    # Check that guild_id was added to the second entry
    second_call_args = report_formatter.format_story_log_entry.call_args_list[1].args[0] # First arg of second call
    assert second_call_args.get("guild_id") == guild_id

    expected_report = "Formatted key1 in en. Nar1\nFormatted key2 in en. Nar2"
    assert report == expected_report

@pytest.mark.asyncio
async def test_generate_turn_report_no_entries(report_formatter: ReportFormatter, mock_i18n_utils_module: MagicMock):
    guild_id = "guild_empty_report"
    lang = "en"
    mock_i18n_utils_module.get_localized_string.return_value = "Nothing happened this turn."

    report = await report_formatter.generate_turn_report(guild_id, lang, [])

    assert report == "Nothing happened this turn."
    mock_i18n_utils_module.get_localized_string.assert_called_once_with("report.nothing_happened", lang)

print("DEBUG: tests/game/services/test_report_formatter.py created.")

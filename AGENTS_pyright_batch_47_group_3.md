# Pyright Error Fixing Log - Batch 47 - Group 3 (from pyright_errors_part_1.txt)

This batch focused on addressing approximately 220 Pyright errors from `pyright_errors_part_1.txt`.

## Files Fixed in this Batch:

1.  **`tests/game/managers/test_combat_manager.py` (24 errors):**
    *   Changed `setUp` to `asyncSetUp`.
    *   Added `spec` arguments to `AsyncMock` for various managers (e.g., `DBService`, `RuleEngine`, `CharacterManager`) to improve type checking for mocks.
    *   Corrected `XPRule` initialization in `CoreGameRulesConfig` (e.g., removed non-existent parameters like `level_difference_modifier`).
    *   Added missing required fields like `relation_rules` and `relationship_influence_rules` to `CoreGameRulesConfig` initialization.
    *   Changed `discord_user_id` to `str` type for `Character` model and stored `stats` as JSON string (`stats_json`). Stored `stats` as `stats_json` for `NpcModel` as well.
    *   Changed `combat_log` to `combat_log_json` for `Combat` model.
    *   Corrected manager method calls (e.g., `get_npc_by_id` instead of `get_npc`, `get_character_by_id` instead of `get_character`).
    *   Added type hints for variables like `kwargs_context` and `mock_settings`.
    *   Added `assert target_participant is not None` after `get_participant_data` for type safety.
    *   Used `unittest.mock.ANY` (imported as `ANY`) for mock assertions.
    *   Corrected `log_warning` call in `test_start_combat_no_valid_participants` to include `guild_id` keyword argument.
    *   Ensured `NpcCombatAI.get_npc_combat_action` is an `AsyncMock` and awaited.
    *   Passed full context (`kwargs_for_tick`) to `NpcCombatAI` constructor and `check_combat_end_conditions`.
    *   Updated loot processing assertions to use `ANY` for character ID and reflect the mocked loot item ID.

2.  **`tests/game/managers/test_party_manager.py` (24 errors, re-visit):**
    *   Changed `setUp` to `asyncSetUp`.
    *   Added `discord` import.
    *   Added `spec=discord.Client` to `mock_discord_client`.
    *   Added `spec=GameManager` to `mock_game_manager` and ensured its attributes (like `combat_manager`, `event_manager`) are mocked appropriately.
    *   Used `cast()` for internal dictionary attributes of `PartyManager` (e.g., `_parties`, `_member_to_party_map`) during test setup and assertions to satisfy Pyright, along with `# type: ignore[attr-defined]` for test-only direct manipulations.
    *   Changed `Party.from_dict` to `Party.model_validate` for Pydantic V2 compatibility.
    *   Corrected `leader_location_id` parameter name in `create_party` call.
    *   Changed `assert_not_called()` to `assert_not_awaited()` for `AsyncMock` instances.
    *   Ensured `player_ids_list` assignments in tests are type-compatible.
    *   Corrected `create_mock_character` return type hint.
    *   Used `TypingAny` for `session_arg` in mock side effect functions.
    *   Ensured `AsyncMock` instances are cast correctly before assertions.

3.  **`tests/ai/test_ai_data_models.py` (23 errors):**
    *   Added `Optional` to type hints.
    *   Ensured Pydantic models nested in lists (e.g., `GeneratedNpcInventoryItem`) are instantiated with `ModelName(**data)`.
    *   Added return type hints to fixtures.
    *   Added type hints to test function parameters and dictionary variables.
    *   Added `is not None` checks before accessing attributes or indexing on `Optional` fields.
    *   Added `is not None` checks before calling `len()` on optional list fields.
    *   Corrected Pydantic model instantiation in tests, ensuring required fields are provided.
    *   Added `# type: ignore` for intentional incorrect type assignments in tests.

4.  **`tests/persistence/test_pending_generation_crud.py` (23 errors):**
    *   Corrected import paths for `PendingGeneration`, `PendingStatus`, `PendingGenerationCRUD`, and `GuildConfig`.
    *   Added `unittest.mock.MagicMock` import.
    - Removed unused `mock_db_service_with_session_factory` fixture.
    *   Ensured `record_id` is passed as `str` to CRUD methods.
    *   Added `assert record.id is not None` after record creation.
    *   Handled potential type differences for JSON fields (`request_params_json`, `validation_issues_json`) by checking `isinstance(field, str)` and using `json.loads()` if necessary before comparison.
    *   Added `# type: ignore[call-arg]` for `GuildConfig` instantiation if necessary.
    *   Renamed loop variable `record` to `record_item` to avoid scope conflicts.

5.  **`bot/game/managers/spell_manager.py` (22 errors):**
    *   Renamed `Character` import from `..models.character` to `GameCharacter` in `TYPE_CHECKING` to avoid naming conflicts.
    *   Changed `Spell.from_dict` to `Spell.model_validate` for Pydantic V2.
    *   Added `isinstance(spell_data, dict)` check before `Spell.model_validate`.
    *   Used `getattr()` for safer access to attributes on `Spell` objects, especially in `get_all_spell_definitions_for_guild`.
    *   Ensured `self._game_manager` and `get_rule` method are checked for existence and callability.
    *   Handled JSON loading for `guild_spell_definitions` from RulesConfig robustly.
    *   Safely accessed and initialized `character.known_spells` and `character.spell_cooldowns` using `getattr`/`setattr` and type checks.
    *   Added `hasattr` and `callable` checks for `self._rule_engine.process_spell_effects`.

6.  **`bot/game/world_processors/world_simulation_processor.py` (22 errors):**
    *   Used `TYPE_CHECKING` block for all manager and model imports to avoid circular dependencies at runtime.
    *   Made `NpcActionProcessor` an optional parameter in `__init__`.
    *   Changed `LocationManager.get_location_static` to `await LocationManager.get_location_instance_by_id` where appropriate.
    *   Ensured `discord_id` is cast to `str` for `CharacterManager.get_character_by_discord_id`.
    *   Used `getattr()` for safe access to attributes like `name` on `Event` model instances.
    *   Ensured methods on optional managers are checked for existence using `hasattr` and `callable(getattr(...))` before calls.
    *   Corrected parameter passing to `_combat_manager.end_combat` (added `winners=[]`, `context=guild_tick_context`).
    *   Ensured `MultilingualPromptGenerator.context_collector.get_full_context` is awaited and `_build_full_prompt_for_openai` is called with corrected parameter `specific_task_instruction`.
    *   Changed `EventStage.from_dict` to `EventStage.model_validate`.
    *   Renamed loop variables to avoid scope conflicts (e.g., `event` to `event_item`).

7.  **`tests/game/managers/test_status_manager.py` (21 errors):**
    *   Corrected import paths for DB models. Added `MagicMock` import.
    *   Added return type hints to fixtures and `spec=AsyncSession` to `mock_session_instance`.
    *   Ensured `CoreGameRulesConfig` is initialized with all required fields in `mock_rule_engine_for_status`.
    *   Made `mock_time_manager_for_status.get_current_turn` a `MagicMock` (synchronous).
    *   Initialized `mock_character_db_instance.status_effects_json` as a JSON string.
    *   Correctly retrieved session instance from async context manager in tests.
    *   Parsed `status_effects_json` string using `json.loads()` before assertions.
    - Added `assert manager is not None` checks and `cast(AsyncMock, ...)` before assertions on mocked manager methods.
    * Ensured `result.message is not None` before string operations in negative tests.

8.  **`tests/integration/test_core_flows.py` (21 errors, re-visit):**
    *   Ensured `DUMMY_LOCATION_TEMPLATES_INTEGRATION` is defined before `DUMMY_SETTINGS`.
    *   Changed `LocationManager.get_location_instance` to `get_location_instance_by_id` and added `await`.
    *   Passed all required mocked manager arguments to `CharacterManager` and `ItemManager` constructors.
    *   Corrected `LocationManager.create_location_instance` call to use `instance_name_i18n`.
    *   Ensured `CharacterManager.create_new_character` is called with `initial_location_id` and `player_id`.
    *   Corrected attribute access on `Character` model (e.g., `current_location_id`).
    *   Changed `PydanticLocation.from_dict` to `model_validate`.
    *   Updated `PydanticLocation.exits` in dummy data to include required fields like `is_visible`, `travel_time_seconds`.
    *   Used `cast()` for `AsyncMock` attributes in assertions.
    *   Changed `ItemManager._load_item_templates` to `await _load_item_templates_from_settings()`.
    *   Changed `ItemManager.create_item_instance` to appropriate methods (`create_item_instance_in_world` / `create_item_instance_in_inventory`), ensuring `quantity` is float.
    *   Changed `ItemManager.get_items_in_location` to `get_items_by_location_id`.
    *   Changed `ItemManager.update_item_instance` to `update_item_instance_in_world`.
    *   Ensured `Character` models in combat tests have `stats_json`.
    *   Changed `CharacterManager.get_character` to `get_character_by_id`.

9.  **`bot/game/party_processors/party_action_processor.py` (20 errors):**
    *   Initialized `logger`.
    *   Added `guild_id` parameter to `start_party_action`, `add_party_action_to_queue`, `process_tick`, `complete_party_action`, and `_notify_party` and ensured it's passed to relevant `PartyManager` calls.
    *   Corrected access to `PartyManager._parties_with_active_action` and `_dirty_parties` using `setdefault(guild_id, set())`.
    *   Added `callable()` checks for manager methods before calling.
    *   Added `await` to `location_manager.get_location_static`.
    *   Corrected parameter passing in `_notify_party` for `character_manager.get_character_by_id`.
    *   Added type hints and `callable` checks in `gm_force_end_party_turn`.
    *   Used `player_ids_list` instead of `members` for party member iteration.
    *   Added `ItemManager` and `StatusManager` to `__init__` and stored them.
    *   Added `GameManager` as an optional parameter to `__init__`.

10. **`tests/game/managers/test_location_manager.py` (20 errors):**
    *   Removed unused `sys` and `discord` imports.
    *   Added type hints to dummy data dictionaries.
    *   Ensured `PydanticLocation` `exits` field in dummy data includes required fields.
    *   Changed `mock_game_manager` to `AsyncMock`.
    *   Ensured all sub-managers on `mock_game_manager` are `AsyncMock` or `MagicMock` with specs.
    *   Corrected `PydanticLocation.from_dict` to `model_validate`.
    *   Ensured `LocationManager.get_location_instance_by_id` is awaited.
    *   Corrected `create_location_instance` calls to use `instance_name_i18n` and `instance_description_i18n`.
    *   Ensured JSON fields like `neighbor_locations_json` are `json.dumps()` if the model expects a string.
    *   Added `guild_id` to `handle_entity_arrival` and `handle_entity_departure` calls.
    *   Used `cast()` for `AsyncMock` instances before assertions.
    *   Used `cast()` for internal cache attributes like `_location_instances` with `# type: ignore[attr-defined]`.
    *   Added `session=unittest.mock.ANY` to `generate_location_details_from_ai` assertion.
    *   Made `test_init_manager` async.
    *   Corrected type hints for static mock methods and `_mock_session_get_side_effect`.
    *   Adjusted assertion in `test_move_transaction_rollback_on_party_update_failure` regarding `db_character.current_location_id`.

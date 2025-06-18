# Crafting and Gathering: Action Integration Plan

This document outlines the plan for integrating new player actions for crafting items and gathering resources into the game's action processing system.

## 1. Identified Modules for Action Processing (Reconfirmed)

*   **Command Parsing:**
    *   `bot/game/command_handlers/`: New command definitions will reside here, potentially in a new `crafting_commands.py` or `gathering_commands.py`, or be added to existing files like `action_commands.py` or `interaction_commands.py`.
*   **Action Storage & Management:**
    *   `bot/game/managers/character_manager.py`: Manages `Character` objects, which will store the `current_action_json` or manage an action queue for these new action types.
*   **Action Execution & Rule Engine Invocation:**
    *   `bot/game/character_processors/character_action_processor.py`: This remains the primary candidate module for handling actions initiated by player characters. It will recognize the new action types and call the appropriate `RuleEngine` methods.
*   **Rule Logic:**
    *   `bot/game/rules/rule_engine.py`: Contains the newly added `resolve_gathering_attempt` and `resolve_crafting_attempt` methods.
*   **Supporting Managers:**
    *   `bot/game/managers/location_manager.py`: To fetch PoI data (for resource nodes) and update their state (e.g., depletion).
    *   `bot/game/managers/item_manager.py` (and potentially `InventoryManager`): To manage item creation (gathered/crafted items) and consumption (ingredients).
    *   A potential new `CraftingManager` or similar service might be needed to fetch and manage `CraftingRecipe` data if it's not directly handled by `RuleEngine` or `ItemManager`.

## 2. Defined Action Structures (JSON)

The following JSON structures will represent the new actions, typically stored in `Character.current_action_json` or a similar field/queue.

*   **Gather Action:**
    ```json
    {
      "type": "gather_resource_attempt",
      "character_id": "char_id_performing_action",
      "guild_id": "guild_id_of_character",
      "target_poi_id": "poi_id_of_resource_node", // From Location.points_of_interest_json
      "location_id": "current_location_id_of_character_and_poi"
    }
    ```

*   **Craft Action:**
    ```json
    {
      "type": "craft_item_attempt",
      "character_id": "char_id_performing_action",
      "guild_id": "guild_id_of_character",
      "recipe_id": "recipe_id_from_crafting_recipes_definitions", // Refers to a defined CraftingRecipe
      "quantity": 1 // Number of times to attempt the craft, defaults to 1
    }
    ```

## 3. Conceptual Command Parsing

New slash commands will facilitate these actions:

*   **`/gather <target_resource_node_name_in_poi>`**
    *   The command handler in `bot/game/command_handlers/` will:
        1.  Identify the player character and their current `location_id`.
        2.  Query `LocationManager` to get the `points_of_interest_json` for the current location.
        3.  Attempt to match `<target_resource_node_name_in_poi>` against the `name_i18n` of "resource_node" type PoIs in the location.
        4.  If a valid PoI is found, extract its `id` as `target_poi_id`.
        5.  Construct the `gather_resource_attempt` action JSON.
        6.  Use `CharacterManager` to assign this action to the character.
    *   Example: `/gather "Iron Vein"`

*   **`/craft <recipe_name_or_id> [quantity]`**
    *   The command handler will:
        1.  Identify the player character.
        2.  Resolve `<recipe_name_or_id>` to a valid `recipe_id`. This resolution might involve:
            *   Looking up a global list of recipes (e.g., managed by a `CraftingManager` or stored in `RuleConfig`).
            *   Checking if the character has "learned" or "unlocked" the recipe (future enhancement, might involve `Character.known_recipes_json`).
        3.  Parse the optional `[quantity]`, defaulting to 1.
        4.  Construct the `craft_item_attempt` action JSON.
        5.  Use `CharacterManager` to assign this action.
    *   Example: `/craft "Iron Sword"` or `/craft "recipe_iron_sword_001" 2`

## 4. Integration Points in Action Processor

The `bot/game/character_processors/character_action_processor.py` will be extended:

*   Add new `elif` blocks for `action['type'] == 'gather_resource_attempt'` and `action['type'] == 'craft_item_attempt'`.

    **Processing `gather_resource_attempt`:**
    1.  **Fetch Data:**
        *   Get `Character` object (or at least `character_skills` and `character_inventory`) using `CharacterManager` (or if already available).
        *   Get `Location` object using `LocationManager` for `action['location_id']`.
        *   Extract the specific `poi_data` for `action['target_poi_id']` from the location's `points_of_interest_json`. Ensure it's a "resource_node".
    2.  **Call RuleEngine:**
        *   `detailed_check_result = await self.rule_engine.resolve_gathering_attempt(character_id=action['character_id'], guild_id=action['guild_id'], poi_data=poi_data, character_skills=character.skills_data_json, character_inventory=character_inventory_list_of_dicts, **action)`
    3.  **Process Result:**
        *   If `detailed_check_result.success` is true:
            *   Use `InventoryManager` (or `ItemManager`) to add `detailed_check_result.custom_outcomes['yielded_items']` to the character's inventory.
            *   Call a method on `LocationManager` (e.g., `await location_manager.update_poi_state(location_id, poi_id, {"is_depleted": True, "last_gathered_timestamp": time.time()})`) to mark the node as depleted and set timestamp.
        *   Send appropriate feedback to the player based on `detailed_check_result.message_key` and other details.

    **Processing `craft_item_attempt`:**
    1.  **Fetch Data:**
        *   Get `Character` object (or `character_skills`, `character_inventory`).
        *   Get `recipe_data` for `action['recipe_id']`. This might come from:
            *   A new `CraftingManager.get_recipe(recipe_id)`.
            *   `self.rule_engine._rules_data.get('crafting_recipes', {}).get(recipe_id)`.
        *   Get `current_location_data` (object or dict with `tags` and `properties.station_type`) using `LocationManager` for the character's current location.
    2.  **Call RuleEngine:**
        *   `detailed_check_result = await self.rule_engine.resolve_crafting_attempt(character_id=action['character_id'], guild_id=action['guild_id'], recipe_data=recipe_data, character_skills=character.skills_data_json, character_inventory=character_inventory_list_of_dicts, current_location_data=location_data_for_rules, quantity=action.get('quantity',1), **action)`
    3.  **Process Result:**
        *   If `detailed_check_result.success` is true:
            *   Use `InventoryManager` to remove `detailed_check_result.custom_outcomes['consumed_items']` from inventory.
            *   Use `InventoryManager` to add `detailed_check_result.custom_outcomes['crafted_item']` to inventory.
            *   Potentially grant XP or update character stats/progress.
        *   Send feedback to player based on `detailed_check_result.message_key`.

*   **Clear Action:** In both cases, after processing, use `CharacterManager` to clear the action.

## 5. Summary of Anticipated Changes

*   **`bot/game/command_handlers/` (New or existing files):**
    *   Add new slash command handlers for `/gather` and `/craft`.
    *   Implement logic to parse arguments, resolve entity/recipe IDs, construct action JSONs, and queue them via `CharacterManager`.
*   **`bot/game/character_processors/character_action_processor.py`:**
    *   Modify the main action processing method to include `elif` conditions for `gather_resource_attempt` and `craft_item_attempt`.
    *   Implement logic to fetch all necessary data (character skills/inventory, PoI data, recipe data, location data).
    *   Call the corresponding `RuleEngine.resolve_gathering_attempt()` or `RuleEngine.resolve_crafting_attempt()`.
    *   Implement logic to handle the `DetailedCheckResult`: update inventories, PoI states, grant XP (future), and generate player feedback.
*   **`bot/game/managers/location_manager.py`:**
    *   May need a new helper method like `async def update_poi_state(self, guild_id: str, location_id: str, poi_id: str, new_state_data: Dict[str, Any])` to modify parts of a PoI's JSON (e.g., set `is_depleted`, `last_gathered_timestamp`).
*   **`bot/game/managers/item_manager.py` / `bot/game/managers/inventory_manager.py`:**
    *   Ensure methods are robust for adding/removing items by template ID and quantity, potentially handling stacks. `InventoryManager` is more likely for character inventory manipulation.
*   **New `bot/game/managers/crafting_manager.py` (Potentially):**
    *   Could be introduced to manage loading, storing, and retrieving `CraftingRecipe` definitions if they are complex or numerous. Alternatively, recipes might be part of `RuleConfig` or managed by `ItemManager` if recipes are themselves items.
*   **`bot/game/models/character.py`:**
    *   `skills_data_json` already updated conceptually.
    *   `current_action_json` or similar field assumed to be adaptable.
*   **`bot/game/models/location.py`:**
    *   `points_of_interest_json` structure already updated conceptually for resource nodes.

This plan provides a roadmap for implementing crafting and gathering actions. Subsequent tasks will focus on the specific coding of these components.

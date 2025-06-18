# GM "God Mode Lite" APIs

This document outlines the design for a suite of "God Mode Lite" APIs intended for Game Masters (GMs) to directly manipulate game state. These APIs are an expansion of Task 47 (Master Commands) and are primarily designed for potential use with a future GM dashboard/UI, though they could also underpin advanced Discord commands.

## 1. Guiding Principles

*   **Guild-Scoped:** All actions are strictly scoped to a `guild_id`.
*   **Permission Controlled:** Access to these APIs must be restricted to users with GM privileges for the respective guild.
*   **Logged:** All actions taken via these APIs must be logged for audit purposes (e.g., via `GameLogManager`).
*   **Manager-Driven:** APIs should primarily act as an interface layer, calling methods on existing or new service managers (`CharacterManager`, `NpcManager`, `LocationManager`, etc.) to perform the actual game state modifications.
*   **Atomicity:** Operations should strive for atomicity where feasible, especially if they involve multiple data updates.

## 2. API Endpoint Structure

A consistent base path will be used: `/api/master/{guild_id}/`

### 2.1 Character Manipulation APIs

Base Path: `/api/master/{guild_id}/character/{character_id}/`

*   **Set/Adjust Stats:**
    *   `POST set_stats`
    *   Request Body: `{"stats": {"hp": 100, "max_hp": 120, "strength": 18, "gold": 500, "xp": 2500}, "level_up_if_needed": true}`
    *   Response: `{"success": true, "updated_stats": {...}}` or `{"success": false, "error": "..."}`
    *   Backend: `CharacterManager.update_character_stats(character_id, stats_dict, level_up_if_needed)`
*   **Add Item to Inventory:**
    *   `POST inventory/add`
    *   Request Body: `{"item_template_id": "potion_healing_greater", "quantity": 5}`
    *   Response: `{"success": true, "item_added": {"item_id": "new_item_instance_id", ...}, "new_inventory_state": [...]}`
    *   Backend: `InventoryManager.add_item_to_character_inventory(character_id, item_template_id, quantity)`
*   **Remove Item from Inventory:**
    *   `POST inventory/remove`
    *   Request Body: `{"item_instance_id": "existing_item_id", "quantity": 1}` OR `{"item_template_id": "potion_healing_greater", "quantity": 1}`
    *   Response: `{"success": true, "new_inventory_state": [...]}`
    *   Backend: `InventoryManager.remove_item_from_character_inventory(...)`
*   **Equip Item:**
    *   `POST equipment/equip`
    *   Request Body: `{"item_instance_id": "item_id_from_inventory", "slot": "main_hand"}`
    *   Response: `{"success": true, "updated_equipment_slots": {...}}`
    *   Backend: `EquipmentManager.equip_item(character_id, item_instance_id, slot)`
*   **Unequip Item:**
    *   `POST equipment/unequip`
    *   Request Body: `{"slot": "main_hand"}`
    *   Response: `{"success": true, "updated_equipment_slots": {...}}`
    *   Backend: `EquipmentManager.unequip_item(character_id, slot)`
*   **Apply Status Effect:**
    *   `POST status_effects/apply`
    *   Request Body: `{"status_effect_id": "blessed_buff", "duration_seconds": 3600, "magnitude": Optional[float]}`
    *   Response: `{"success": true, "applied_effect_details": {...}}`
    *   Backend: `StatusManager.apply_status_effect(target_type="Character", target_id=character_id, status_effect_id, duration, magnitude)`
*   **Remove Status Effect:**
    *   `POST status_effects/remove`
    *   Request Body: `{"status_effect_instance_id": "active_effect_id_on_char"}` OR `{"status_effect_id": "blessed_buff"}`
    *   Response: `{"success": true}`
    *   Backend: `StatusManager.remove_status_effect(target_type="Character", target_id=character_id, effect_id_or_instance_id)`
*   **Teleport Character:**
    *   `POST teleport`
    *   Request Body: `{"location_id": "new_target_loc_id", "coordinates_json": Optional[{"x":1, "y":2}]}`
    *   Response: `{"success": true, "new_location_id": "...", "new_coordinates": "..."}`
    *   Backend: `CharacterManager.teleport_character(character_id, location_id, coordinates_json)`
*   **Learn Skill/Spell/Ability:**
    *   `POST knowledge/learn`
    *   Request Body: `{"type": "skill/spell/ability", "knowledge_id": "mining/fireball/power_attack"}`
    *   Response: `{"success": true}`
    *   Backend: `SkillManager/SpellManager/AbilityManager.learn(character_id, knowledge_id)` (or a unified `KnowledgeManager`)
*   **Forget Skill/Spell/Ability:**
    *   `POST knowledge/forget`
    *   Request Body: `{"type": "skill/spell/ability", "knowledge_id": "..."}`
    *   Response: `{"success": true}`
    *   Backend: `SkillManager/SpellManager/AbilityManager.forget(character_id, knowledge_id)`
*   **Modify Quest:**
    *   `POST quests/update`
    *   Request Body: `{"quest_id": "epic_quest_1", "action": "grant/complete_step/remove/fail", "step_id": Optional["step_2"], "assign_to_party": Optional[bool]}`
    *   Response: `{"success": true, "updated_quest_log": [...]}`
    *   Backend: `QuestManager.update_quest_for_character_or_party(...)`

### 2.2 NPC Manipulation APIs

Base Path: `/api/master/{guild_id}/npc/`

*   **Set/Adjust NPC Stats:** (Similar to character `set_stats`)
    *   `POST {npc_id}/set_stats`
    *   Request Body: `{"stats": {"hp": 50, "max_hp": 50}}`
    *   Backend: `NpcManager.update_npc_stats(npc_id, stats_dict)`
*   **Add/Remove Item from NPC Inventory:** (Similar to character inventory)
    *   `POST {npc_id}/inventory/add`
    *   `POST {npc_id}/inventory/remove`
    *   Backend: `InventoryManager.add_item_to_npc_inventory(...)`, `InventoryManager.remove_item_from_npc_inventory(...)`
*   **Apply/Remove Status Effect on NPC:** (Similar to character status)
    *   `POST {npc_id}/status_effects/apply`
    *   `POST {npc_id}/status_effects/remove`
    *   Backend: `StatusManager.apply_status_effect(target_type="NPC", ...)`
*   **Teleport NPC:** (Similar to character teleport)
    *   `POST {npc_id}/teleport`
    *   Backend: `NpcManager.teleport_npc(npc_id, location_id, coordinates_json)`
*   **Change NPC Behavior/State:**
    *   `POST {npc_id}/set_behavior`
    *   Request Body: `{"add_tags": Optional[List[str]], "remove_tags": Optional[List[str]], "set_faction_id": Optional[str], "hostility_flags": Optional[Dict[str, bool]]}` (e.g. `{"hostility_flags": {"player_characters": true}}`)
    *   Response: `{"success": true, "updated_behavior": {...}}`
    *   Backend: `NpcManager.update_npc_behavior(npc_id, add_tags, remove_tags, faction_id, hostility_flags)`
*   **Spawn NPC:**
    *   `POST spawn`
    *   Request Body: `{"npc_template_id": "goblin_scout", "location_id": "forest_clearing_loc", "quantity": 3, "coordinates_json": Optional[{"x":1,"y":1}]}`
    *   Response: `{"success": true, "spawned_npcs": [{"id": "npc_123", ...}, ...]}`
    *   Backend: `NpcManager.spawn_npc_in_location(npc_template_id, location_id, quantity, coordinates_json)`
*   **Despawn NPC:**
    *   `POST {npc_id}/despawn`
    *   Request Body: `{}`
    *   Response: `{"success": true}`
    *   Backend: `NpcManager.despawn_npc(npc_id)`

### 2.3 Location Manipulation APIs

Base Path: `/api/master/{guild_id}/location/{location_id}/`

*   **Modify State Variables:**
    *   `POST state_variables/set`
    *   Request Body: `{"variable_name": "secret_passage_discovered", "value": true}`
    *   Response: `{"success": true, "updated_state_variables": {...}}`
    *   Backend: `LocationManager.update_location_state_variable(location_id, variable_name, value)`
*   **Set PoI Lock State:**
    *   `POST poi/{poi_id}/set_lock`
    *   Request Body: `{"is_locked": false, "new_dc": Optional[int]}`
    *   Response: `{"success": true, "updated_poi_data": {...}}`
    *   Backend: `LocationManager.update_poi_state(location_id, poi_id, {"lock_details": {"is_locked": false, ...}})`
*   **Set PoI Trap State:**
    *   `POST poi/{poi_id}/set_trap`
    *   Request Body: `{"is_active": false, "new_disarm_dc": Optional[int]}`
    *   Response: `{"success": true, "updated_poi_data": {...}}`
    *   Backend: `LocationManager.update_poi_state(location_id, poi_id, {"trap_details": {"is_active": false, ...}})`
*   **Add/Remove Item from Location/PoI Container:**
    *   `POST inventory/add` OR `POST poi/{poi_id}/container/add`
    *   Request Body: `{"item_template_id": "ancient_scroll", "quantity": 1}`
    *   Response: `{"success": true, "updated_container_inventory": [...]}`
    *   Backend: `InventoryManager.add_item_to_location_or_poi_container(...)`
*   **Spawn Item at Location (loose item):**
    *   `POST item/spawn`
    *   Request Body: `{"item_template_id": "gold_coins", "quantity": 100, "coordinates_json": Optional[{"x":1,"y":1}]}`
    *   Response: `{"success": true, "spawned_item_instance": {...}}`
    *   Backend: `ItemManager.spawn_item_in_location(location_id, item_template_id, quantity, coordinates_json)`

### 2.4 World State Manipulation APIs

Base Path: `/api/master/{guild_id}/world_state/`

*   **Set/Unset Global World Flags:**
    *   `POST flags/set`
    *   Request Body: `{"flag_name": "main_quest_phase_2_started", "value": true}` (value can be boolean, string, number)
    *   Response: `{"success": true, "updated_flags": {...}}`
    *   Backend: `WorldStateManager.set_custom_flag(guild_id, flag_name, value)`

### 2.5 Event Manipulation APIs

Base Path: `/api/master/{guild_id}/event/`

*   **Manually Trigger Event Template:**
    *   `POST trigger`
    *   Request Body: `{"event_template_id": "bandit_ambush_event", "location_id": "crossroads_loc", "target_character_ids": Optional[List[str]], "execution_params": Optional[Dict]}`
    *   Response: `{"success": true, "event_instance_id": "active_event_id_123"}`
    *   Backend: `EventManager.create_event_from_template(event_template_id, location_id, guild_id, execution_params, target_character_ids)`
*   **Advance/End Active Event:**
    *   `POST {event_instance_id}/update_status`
    *   Request Body: `{"action": "advance_stage", "target_stage_id": Optional["stage_3"]}` OR `{"action": "end_event", "outcome": "gm_forced_completion"}`
    *   Response: `{"success": true, "updated_event_status": {...}}`
    *   Backend: `EventManager.advance_event_stage(...)` or `EventManager.end_event(...)`

### 2.6 RuleConfig Management APIs (from Task 47)

Base Path: `/api/master/{guild_id}/rules/`

*   **View Rules:**
    *   `GET view` OR `GET view/{rule_key_prefix}`
    *   Response: `{"success": true, "rules_data": {...}}`
    *   Backend: `RuleConfigManager.get_rules(key_prefix)`
*   **Edit Rule:**
    *   `POST edit`
    *   Request Body: `{"rule_key": "economy.base_sell_price_multiplier", "new_value": 0.8}`
    *   Response: `{"success": true, "updated_rule": {"key": "...", "value": "..."}}`
    *   Backend: `RuleConfigManager.set_rule(rule_key, new_value)`

## 3. Backend Logic Summary

*   Each API endpoint will be implemented in the web server layer (e.g., FastAPI, Flask).
*   Authentication and Authorization: Verify the caller is a GM for the specified `guild_id`.
*   Request Validation: Use Pydantic models or similar for validating request bodies.
*   Service Layer: Call appropriate methods on existing or new service managers (`CharacterManager`, `NpcManager`, `LocationManager`, `ItemManager`, `InventoryManager`, `StatusManager`, `QuestManager`, `EventManager`, `WorldStateManager`, `RuleConfigManager`). These managers encapsulate the core game logic and database interactions.
*   Database Interaction: Managers will handle all database reads and writes, ideally using an ORM like SQLAlchemy.
*   Logging: All GM-initiated actions through these APIs must be logged via `GameLogManager` with a specific event type like `gm_api_action` and details of the action, parameters, and GM ID.

This document provides a blueprint for the "God Mode Lite" APIs. Actual implementation will require creating these endpoints and ensuring the underlying manager methods are robust and support these operations.

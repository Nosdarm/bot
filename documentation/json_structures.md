# JSON Structures for Game Mechanics

## Character.skills_data_json
*(Structure defined previously)*

## Location.points_of_interest_json
*(Structure defined previously, including PoI Types: `trap` and `resource_node`)*

## CraftingRecipe.other_requirements_json
*(Structure defined previously)*

## Location.event_triggers

The `event_triggers` field in the `Location` model is a JSONB field, typically an array of event trigger objects. These define conditions under which specific events or actions are initiated within the location.

**Individual Event Trigger Object Structure:**
*   `trigger_id: str`
*   `trigger_condition: Dict[str, Any]` (Examples: `on_player_action`, `on_world_state_change`, `on_time_of_day`, `random_chance_periodic`, `on_npc_state_change`, `on_item_used_in_location`)
*   `event_template_id: Optional[str]`
*   `actions_on_trigger: Optional[List[Dict[str, Any]]]>`
    *   **Refined/New Action Types for NPC Initiation:**
        *   `{"type": "spawn_npc", "npc_template_id": "...", "quantity": "...", ...}` (Existing)
        *   `{"type": "display_message_i18n", "message_key": "...", ...}` (Existing)
        *   `{"type": "change_location_state", "state_variable_name": "...", ...}` (Existing)
        *   `{"type": "grant_item_to_player", "item_template_id": "...", ...}` (Existing)
        *   `{"type": "update_poi_state", "target_poi_id": "...", ...}` (Existing)
        *   **`{"type": "npc_initiate_dialogue", "target_npc_id_or_tag": "unique_npc_id_or_role_tag", "dialogue_tree_id": "dialogue_id_to_start", "triggering_player_is_target": true, "max_range_from_player": Optional[int]}`**: An NPC (or the first one matching tag) attempts to start a dialogue with a player (often the one triggering the event, or one nearby). `max_range_from_player` could be used if the NPC needs to be close.
        *   **`{"type": "npc_change_behavior", "target_npc_id_or_tag": "unique_npc_id_or_role_tag", "add_tags": Optional[List[str]], "remove_tags": Optional[List[str]], "set_faction_reputation": Optional[Dict[str,Any]], "duration_seconds": Optional[int]}`**: Adds/removes `behavior_tags` or `state_tags` from an NPC, or changes their faction reputation temporarily or permanently. `set_faction_reputation` could be `{"faction_id": "player_faction", "change": -10, "absolute_value": 25}`.
        *   **`{"type": "npc_move_to_interact", "target_npc_id_or_tag": "npc_id_to_move", "destination_poi_id": Optional[str], "destination_player_target": Optional[bool], "activity_on_arrival": "e.g., initiate_dialogue_suspicious_player", "max_travel_duration_seconds": Optional[int]}`**: An NPC moves to a specific PoI or towards the triggering player, then performs an activity. `destination_player_target: true` means move towards the player who triggered the event.
        *   `{"type": "npc_set_hostility", "target_npc_id_or_tag": "npc_id", "hostile_to_player_character": true, "hostile_to_faction_id": Optional[str]}`: Makes specified NPC(s) hostile to the triggering player or a faction.
*   `one_time_only: bool`
*   `cooldown_seconds: Optional[int]`
*   `execution_params: Optional[Dict[str, Any]]`
*   `is_active: bool`
*   `last_triggered_timestamp: Optional[float]`

*(Full structure for event_triggers including examples was defined previously and can be referenced if needed. This section highlights refinements to `actions_on_trigger`.)*


## NPC.schedule_json
*(Structure defined previously)*


## NPC.behavior_tags

The `behavior_tags` field in the `NPC` model is a JSONB field storing a list of strings. These tags help define an NPC's default reactions, proactive behaviors, or how they are perceived by other systems (e.g., AI generation, faction logic). Some tags can be parsed by the `WorldSimulationProcessor` or `CharacterActionProcessor` to trigger NPC-initiated actions based on proximity to players or specific game conditions.

**Tag Patterns for Proactive Behavior:**

Tags are strings, often using colons (`:`) to separate parts for clarity and parsing. The system will iterate through these tags and check their conditions when relevant (e.g., player nearby, specific game state).

*   **Dialogue Initiation:**
    *   `"PROACTIVE_DIALOGUE:QUEST_AVAILABLE:<quest_id>"`: NPC attempts to initiate dialogue if a nearby player is eligible for the specified `quest_id` (e.g., meets prerequisites and hasn't completed it). Requires `QuestManager` check.
    *   `"PROACTIVE_DIALOGUE:QUEST_REMINDER:<quest_id>:<quest_step_id>"`: NPC reminds player about an active quest step.
    *   `"PROACTIVE_DIALOGUE:CONDITION:<condition_key>:<dialogue_tree_id>"`: NPC initiates a specific `dialogue_tree_id` if a `condition_key` (checked via `RuleEngine.check_conditions` against player or world state) is met. Example: `PROACTIVE_DIALOGUE:CONDITION:player_is_wearing_specific_armor:armor_admirer_dialogue`.
    *   `"PROACTIVE_DIALOGUE:FIRST_ENCOUNTER:<dialogue_tree_id>"`: NPC uses this dialogue tree upon first meaningful interaction with a player. (Requires tracking "met player" status).
    *   `"PROACTIVE_DIALOGUE:FACTION_GREETING:<faction_id>:<dialogue_tree_id>"`: Specific greeting if player belongs to `<faction_id>`.
    *   `"PROACTIVE_DIALOGUE:RANDOM_CHATTER:<chatter_group_id>:<cooldown_seconds>"`: NPC occasionally says a line from a chatter group.

*   **Warnings & Alerts:**
    *   `"PROACTIVE_WARNING:AREA_RESTRICTED:<area_id_or_name>:<dialogue_tree_id_or_message_key>"`: NPC warns player if they are in/near a restricted area associated with the NPC. `area_id_or_name` might refer to a sub-zone or PoI.
    *   `"PROACTIVE_ALERT:COMBAT_NEARBY:<radius_meters>"`: NPC becomes alert or calls for help if combat starts nearby.

*   **Hostility Triggers:**
    *   `"PROACTIVE_HOSTILITY:FACTION_HATE:<enemy_faction_id>"`: NPC becomes hostile if a nearby player is identified as belonging to the `<enemy_faction_id>`. Requires `RelationshipManager` or faction data on character.
    *   `"PROACTIVE_HOSTILITY:ITEM_DETECTED:<forbidden_item_template_id>:<detection_skill_check_dc_optional>"`: NPC becomes hostile if a nearby player is detected carrying a `<forbidden_item_template_id>`. May involve a skill check (NPC perception vs player stealth/concealment).
    *   `"PROACTIVE_HOSTILITY:TRESPASSING:<area_id_or_name>"`: NPC becomes hostile if player is found in a forbidden area they guard.
    *   `"PROACTIVE_HOSTILITY:ON_SIGHT"`: NPC is immediately hostile to all player characters.

*   **Item Interactions:**
    *   `"PROACTIVE_INTERACTION:ITEM_REQUEST:<item_template_id_needed>:<dialogue_tree_id_for_request>"`: NPC actively asks nearby players for a specific item.
    *   `"PROACTIVE_INTERACTION:ITEM_TRADE_OFFER:<item_template_id_to_give>:<item_template_id_to_receive_optional>:<dialogue_tree_id>"`: NPC offers to trade an item.

*   **Ambient Behaviors & States:**
    *   `"STATE:GUARDING:<poi_id_or_area_name>"`: Indicates NPC is actively guarding a point or area. Used by schedule or other systems.
    *   `"STATE:WORKING_AT_STATION:<station_type_or_poi_id>"`: Indicates NPC is working.
    *   `"BEHAVIOR:NERVOUS"` or `"BEHAVIOR:CURIOUS"`: Can influence AI dialogue generation or minor, non-scripted actions.
    *   `"ROLE:MERCHANT"`, `"ROLE:GUARD"`, `"ROLE:BLACKSMITH"`: General role tags, useful for AI, schedule defaults, and generic interactions.

**Example `behavior_tags` list for an NPC:**
```json
[
  "ROLE:GUARD",
  "STATE:GUARDING:main_gate_poi",
  "PROACTIVE_DIALOGUE:FIRST_ENCOUNTER:guard_first_greeting_dialogue",
  "PROACTIVE_WARNING:AREA_RESTRICTED:restricted_barracks_area:guard_barracks_warning_dialogue",
  "PROACTIVE_HOSTILITY:FACTION_HATE:reavers_faction",
  "PROACTIVE_HOSTILITY:ITEM_DETECTED:stolen_kings_amulet:18"
]
```

Processing these tags involves checking conditions related to nearby players, game state, and the NPC's own state, then triggering corresponding actions like dialogue, combat, or simple messages.
This documentation outlines the conceptual structure for these JSON fields.
```

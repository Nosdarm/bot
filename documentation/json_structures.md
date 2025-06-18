# JSON Structures for Game Mechanics

## Character.skills_data_json
*(Structure defined previously)*

## Location.points_of_interest_json
*(Structure defined previously, including PoI Types: `trap` and `resource_node`)*

## CraftingRecipe.other_requirements_json
*(Structure defined previously)*

## Location.event_triggers
*(Structure defined previously, with refined `actions_on_trigger`)*

## NPC.schedule_json
*(Structure defined previously)*

## NPC.behavior_tags
*(Structure defined previously)*

## Party Model Fields

This section describes notable JSONB fields within the `Party` model (`bot/database/models.py`).

### Party.player_ids_json

*   **Type:** JSONB
*   **Description:** This field stores a list of `Character.id` strings, representing the character members of the party. It does *not* store `Player.id`s.
*   **Managed By:** `PartyManager` will be responsible for adding and removing character IDs from this list.
*   **Example:**
    ```json
    [
      "char_uuid_alpha_123",
      "char_uuid_bravo_456",
      "char_uuid_charlie_789"
    ]
    ```

*(Other Party model JSON fields like `state_variables` can be documented here as needed in the future.)*

This documentation outlines the conceptual structure for these JSON fields.
```

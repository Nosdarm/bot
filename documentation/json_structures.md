# JSON Structures for Game Mechanics

## Character.skills_data_json

The `skills_data_json` field in the `Character` model will store various skill levels for the character. This is a JSONB field where keys are skill IDs (strings) and values are integers representing the character's proficiency in that skill.

**Stealth-Related Skills:**
*   `stealth`: Integer. Represents the character's proficiency in moving unseen and unheard.
*   `pickpocket`: Integer. Represents the character's skill in stealing items from NPCs.
*   `lockpicking`: Integer. Represents the character's ability to open locked doors/containers.
*   `disarm_traps`: Integer. Represents the character's skill in neutralizing traps.

**Crafting and Gathering Skills:**
*   `mining`: Integer. Skill level for extracting ores and minerals from deposits.
*   `herbalism`: Integer. Skill level for collecting plants, fungi, and other natural ingredients.
*   `skinning`: Integer. Skill level for obtaining hides, leathers, and other specific parts from creature carcasses. (Note: Actual items obtained might also depend on combat loot tables or creature definitions).
*   `blacksmithing`: Integer. Skill level for crafting metal items like weapons, armor, and tools.
*   `alchemy`: Integer. Skill level for brewing potions, concoctions, and other magical or chemical substances.
*   `leatherworking`: Integer. Skill level for crafting leather armor, bags, and other goods from hides and leathers.
*   `inscription`: Integer. Skill level for creating scrolls, glyphs, maps, or other written magical or informative items.
*   `tailoring`: Integer. Skill level for crafting cloth armor, bags, cloaks, and other garments. (Added as a common crafting skill)
*   `jewelcrafting`: Integer. Skill level for crafting rings, amulets, and other adornments, often involving gems and precious metals. (Added as a common crafting skill)
*   `woodworking`: Integer. Skill level for crafting bows, staves, furniture, and other wooden items. (Added as a common crafting skill)


These keys will exist alongside other skill definitions (e.g., combat skills, social skills) within the `skills_data_json` object.

**Example `skills_data_json`:**
```json
{
  "strength": 10, // This is an attribute, skills are separate
  "dexterity": 15, // This is an attribute
  "stealth": 12,
  "pickpocket": 8,
  "lockpicking": 10,
  "disarm_traps": 11,
  "mining": 15,
  "herbalism": 10,
  "skinning": 12,
  "blacksmithing": 8,
  "alchemy": 14,
  "leatherworking": 7,
  "inscription": 5,
  "tailoring": 9,
  "jewelcrafting": 6,
  "woodworking": 11,
  "persuasion": 7,
  "insight": 9
  // ... other skills or attributes as decided by game design
}
```
*(Clarified that attributes like strength/dexterity are typically separate from the skills dictionary, though the JSON structure itself can hold any key-value pair)*

## Location.points_of_interest_json

The `points_of_interest_json` field in the `Location` model describes various interactive elements within a location. This is a JSONB field, typically an array of PoI objects.

### PoI Type: `trap`
*(Structure defined previously)*

### PoI Type: `resource_node`
*(Structure defined previously)*


## CraftingRecipe.other_requirements_json

The `other_requirements_json` field in the `CraftingRecipe` model specifies environmental or tool prerequisites.
*(Structure defined previously)*


## Location.event_triggers

The `event_triggers` field in the `Location` model is a JSONB field, typically an array of event trigger objects. These define conditions under which specific events or actions are initiated within the location.
*(Structure defined previously, see example in earlier version of this file if needed)*


## NPC.schedule_json

The `schedule_json` field in the `NPC` model is a JSONB field that defines an NPC's typical activities and movements based on game time and world events.
*(Note: Adding this field to `bot/database/models.py` for the `NPC` class will require a new database migration via Alembic.)*

**Top-Level Keys:**

*   `default_activity: Optional[str]`: An activity key (e.g., "wander_general_area", "guard_post_main_gate", "sleep_in_barracks") that the NPC defaults to if no other schedule entry matches the current time/conditions.
*   `default_location_id: Optional[str]`: The `location_id` where the NPC performs their `default_activity`, or where they should attempt to return if idle or no specific schedule matches.
*   `daily_schedule: Optional[List[Dict[str, Any]]]>`: A list of scheduled activities that repeat daily. Entries are processed in order; the first one matching the current time is typically chosen.
    *   **Each entry:**
        *   `time: str`: The in-game time for this activity to start, formatted as "HH:MM" (24-hour format).
        *   `location_id: str`: The `location_id` where this activity takes place.
        *   `activity_key: str`: An identifier for the activity (e.g., "work_at_shop", "patrol_market_district", "eat_at_tavern", "sleep"). This key might be used by an `NpcActionProcessor` to determine specific behaviors or sub-actions.
        *   `duration_minutes: Optional[int]`: Approximate duration for this activity. If present, the NPC might try to continue this activity until this duration passes or the next scheduled item begins. (Optional: a simpler system might just switch at the next `time` entry).
*   `weekly_schedule: Optional[Dict[str, List[Dict[str, Any]]]]`: A dictionary where keys are day names (e.g., "Monday", "Tuesday", ..., "Sunday", or game-specific day names like "Fireday", "Earthday"). The values are lists of daily schedule entries, following the same structure as `daily_schedule` entries. This schedule takes precedence over `daily_schedule` for the specified day.
*   `special_event_overrides: Optional[List[Dict[str, Any]]]>`: A list of high-priority schedule overrides that are active when certain world conditions are met. These take precedence over weekly and daily schedules.
    *   **Each entry:**
        *   `condition_world_flag: str`: The name of a global world state flag (e.g., "kings_birthday_festival_active", "city_under_siege").
        *   `expected_value: Any` (Optional, defaults to `true`): The value the flag must have for this override to be active.
        *   `location_id: str`: The `location_id` for the override activity.
        *   `activity_key: str`: The activity the NPC should perform.
        *   `priority: Optional[int]` (Optional, defaults to 0): Higher numbers mean higher priority if multiple special events are active.

**Example `schedule_json`:**
```json
{
  "default_activity": "patrol_town_square",
  "default_location_id": "town_square_loc",
  "daily_schedule": [
    {
      "time": "07:00",
      "location_id": "barracks_loc",
      "activity_key": "wake_up_and_drill",
      "duration_minutes": 60
    },
    {
      "time": "08:00",
      "location_id": "mess_hall_loc",
      "activity_key": "breakfast",
      "duration_minutes": 30
    },
    {
      "time": "09:00",
      "location_id": "main_gate_loc",
      "activity_key": "guard_duty_main_gate",
      "duration_minutes": 240
    },
    {
      "time": "13:00",
      "location_id": "market_loc",
      "activity_key": "lunch_and_socialize",
      "duration_minutes": 60
    },
    {
      "time": "14:00",
      "location_id": "main_gate_loc",
      "activity_key": "guard_duty_main_gate",
      "duration_minutes": 240
    },
    {
      "time": "18:00",
      "location_id": "tavern_loc",
      "activity_key": "dinner_and_relax",
      "duration_minutes": 120
    },
    {
      "time": "22:00",
      "location_id": "barracks_loc",
      "activity_key": "sleep",
      "duration_minutes": 420
    }
  ],
  "weekly_schedule": {
    "Godsday": [ // Game-specific day name
      {
        "time": "10:00",
        "location_id": "temple_loc",
        "activity_key": "temple_service_attendance",
        "duration_minutes": 120
      },
      { // Overrides the 09:00-13:00 and 14:00-18:00 guard duty on Godsday
        "time": "12:00",
        "location_id": "town_square_loc",
        "activity_key": "public_sermon_or_rest",
        "duration_minutes": 180
      }
      // Other parts of the day might fall back to daily_schedule if not specified here
    ]
  },
  "special_event_overrides": [
    {
      "condition_world_flag": "harvest_festival_active",
      "expected_value": true,
      "location_id": "festival_grounds_loc",
      "activity_key": "participate_harvest_festival_games",
      "priority": 10
    },
    {
      "condition_world_flag": "dragon_attack_imminent",
      "location_id": "city_walls_loc",
      "activity_key": "man_the_battlements",
      "priority": 100 // Very high priority
    }
  ]
}
```

This documentation outlines the conceptual structure for these JSON fields to support NPC scheduling.
```

*(Self-correction: Removed redundant PoI type definitions and CraftingRecipe definitions as they were already present and correct from the previous read. Focused on appending the new NPC.schedule_json section correctly.)*

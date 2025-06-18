# Static World Data and Lore Loading Strategy

This document outlines the strategy for loading static world data, specifically focusing on locations and lore entries, upon guild initialization and during campaign setup.

## 1. Static Location Loading

The loading of static (pre-defined) locations into a new guild follows a two-stage process:

*   **A. Initial Minimal Set (`bot/game/guild_initializer.py`):**
    *   When a new guild is initialized (e.g., when the bot joins a new server or a GM runs an initialization command), the `guild_initializer.py` script is responsible for creating essential baseline records for the guild.
    *   This includes creating a minimal set of fundamental locations, such as a default starting location (e.g., "village_square," "crossroads"). These are typically hardcoded or read from a very basic template within the initializer to ensure the game world is minimally functional even before a full campaign is loaded.
    *   These locations are directly persisted to the database during the guild initialization transaction.

*   **B. Comprehensive Campaign Set (`bot/game/services/campaign_loader.py`):**
    *   The `CampaignLoader` service, particularly its `load_and_populate_locations` method (called by `populate_all_game_data`), is responsible for loading a more extensive set of static locations defined for a specific campaign.
    *   This data is typically read from a JSON file (e.g., `data/locations.json` or a campaign-specific file like `data/campaigns/default_campaign/locations.json`).
    *   The `CampaignLoader` processes this file and creates `Location` records in the database for the guild. This process usually happens when a GM explicitly loads or applies a campaign to their guild.
    *   This allows for different sets of static locations depending on the chosen campaign.

This two-stage approach ensures that a guild has essential locations upon creation, and a richer set of locations once a campaign is applied.

## 2. Lore Storage and Loading Strategy

For managing lore entries (in-game books, historical notes, cultural information, etc.), the following strategy will be adopted for the MVP:

*   **A. Storage Mechanism:**
    *   Lore entries will be stored directly within the `WorldState.custom_flags` JSONB field of the `WorldState` table for each guild.
    *   A specific top-level key, such as `"embedded_lore_entries"`, will be used within `custom_flags`. The value associated with this key will be a list of lore objects.
    *   This approach avoids creating a separate `LoreEntries` table for the MVP, simplifying the database schema while still allowing for structured lore data.

*   **B. Lore Entry JSON Structure:**
    *   Each individual lore object stored in the `"embedded_lore_entries"` list will adhere to the following JSON structure:
        ```json
        {
          "key": "unique_lore_key_string", // e.g., "history_of_eldoria_vol1", "basics_of_alchemy"
          "title_i18n": {
            "en": "History of Eldoria, Vol. 1",
            "ru": "История Элдории, Том 1"
          },
          "text_i18n": {
            "en": "Long ago, in the mists of time, Eldoria was but a whisper...",
            "ru": "Давным-давно, во мгле времен, Элдория была лишь шепотом..."
          },
          "category_i18n": { // Helps in organizing and filtering lore
            "en": "History",
            "ru": "История"
          },
          "unlock_conditions": [ // Optional: Conditions for this lore to be discoverable/readable by players
            // e.g., {"type": "quest_completed", "quest_id": "ancient_tome_quest"}
            // e.g., {"type": "player_skill_level", "skill_id": "lore_academics", "level": 10}
          ],
          "discovered_by_default": true // If false, needs to be unlocked via gameplay
        }
        ```

*   **C. Initial Lore Population:**

    *   **1. `guild_initializer.py` (Fundamental/Global Lore):**
        *   During the creation of a new `WorldState` record for a guild, `guild_initializer.py` can be modified to add a small set of fundamental, globally applicable lore entries.
        *   These would be lore items that are common knowledge or essential starting information in any campaign.
        *   Example: A lore entry explaining the basic pantheon or the world's creation myth if it's universal.
        *   This involves directly constructing the lore JSON objects and adding them to the `custom_flags["embedded_lore_entries"]` list before the initial `WorldState` is saved.

    *   **2. `campaign_loader.py` (Campaign-Specific Lore):**
        *   The `CampaignLoader` service will be primarily responsible for populating campaign-specific lore.
        *   The `load_campaign_data_from_source` method (or a similar method that parses the campaign JSON file, e.g., `data/campaigns/default_campaign.json`) will be modified to look for a top-level key named `"lore_entries"`.
        *   This `"lore_entries"` key in the campaign JSON file should contain a list of lore objects following the structure defined above.
        *   During the `populate_all_game_data` process (or a new dedicated method like `populate_lore_data`), the `CampaignLoader` will:
            1.  Fetch the existing `WorldState` for the guild.
            2.  Retrieve the current `embedded_lore_entries` list from `custom_flags`.
            3.  Merge the lore entries from the campaign file into this list. Care should be taken to avoid duplicates if `guild_initializer` and `campaign_loader` might provide overlapping "global" lore (e.g., by checking `key` uniqueness). For MVP, campaign lore might simply append or overwrite. A safer approach is to add if key doesn't exist.
            4.  Save the updated `WorldState` (with the merged lore list in `custom_flags`) back to the database. This should happen within the same transaction as other campaign data population.

*   **D. `LoreManager` Responsibility:**
    *   The `LoreManager` (Task 33) will be the primary service for other game systems (e.g., UI, player commands for reading lore, event scripts) to access and query lore entries.
    *   Its primary method for fetching lore will involve:
        1.  Getting the `WorldState` object for the current guild (likely via `WorldStateManager` or `GameManager`).
        2.  Accessing `world_state.custom_flags.get("embedded_lore_entries", [])`.
        3.  Providing functionalities to filter or retrieve specific lore entries from this list based on `key`, `category_i18n`, or player discovery status (if `unlock_conditions` and `discovered_by_default` are implemented).
    *   The `LoreManager` will not directly write lore for now; writing is handled by `guild_initializer` and `campaign_loader`. Future GM tools might allow direct lore editing via `LoreManager`.

## 3. Summary of Modifications

*   **`bot/game/guild_initializer.py`**:
    *   Minor modification to potentially add a few globally essential lore entries to `WorldState.custom_flags.embedded_lore_entries` during initial `WorldState` creation.
*   **`bot/game/services/campaign_loader.py`**:
    *   Modify `load_campaign_data_from_source` (or equivalent campaign file parsing logic) to read a `"lore_entries"` list from the campaign JSON data.
    *   Modify `populate_all_game_data` (or add a new method) to fetch the current `WorldState`, merge these new lore entries into `custom_flags.embedded_lore_entries`, and save the updated `WorldState`.
*   **`bot/database/models.py` (`WorldState` model):**
    *   No schema change needed as `custom_flags` (JSONB) is already present and suitable for this flexible storage.
*   **`bot/game/managers/lore_manager.py`**:
    *   Will need to be implemented to read lore from `WorldState.custom_flags.embedded_lore_entries` and provide access/query methods.

This strategy leverages the existing `WorldState.custom_flags` field for MVP lore storage, minimizing immediate schema changes while providing a structured way to load and access lore. The `CampaignLoader` becomes the main vehicle for populating rich, campaign-specific lore.

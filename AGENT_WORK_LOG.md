## Project Understanding

**Date:** 30 июня 2025 г.

This document summarizes my current understanding of the Kvelin GM Bot project based on a comprehensive review of the codebase.

### Core Architecture

The project is a sophisticated, multi-guild Discord bot for AI-driven text-based RPGs. The architecture is well-structured and modular, with a clear separation of concerns:

*   **`main.py` & `bot/bot_core.py`**: The main entry point and core of the Discord bot. It handles bot initialization, event handling (on_ready, on_guild_join, etc.), and command loading. It instantiates the `GameManager` and other core services.
*   **`bot/game/game_manager.py`**: The central hub for all game logic. It initializes and holds references to all the various game managers (character, location, combat, etc.) and services. It acts as a facade, providing a single point of entry for the bot commands to interact with the game world.
*   **`bot/database/`**: The data persistence layer. It uses SQLAlchemy for the ORM and defines all the database models in `models.py`. The `crud_utils.py` provides generic, guild-aware functions for interacting with the database. The `postgres_adapter.py` and `sqlite_adapter.py` provide a layer of abstraction over the database drivers. Specific CRUD operations for various entities are found in `inventory_crud.py`, `item_crud.py`, `pending_generation_crud.py`, `rpg_character_crud.py`, and `user_settings_crud.py`.
*   **`bot/services/`**: Contains various services that provide functionality to the rest of the application, such as the `DBService`, `OpenAIService`, and `NLUDataService`.
*   **`bot/ai/`**: This directory contains all the AI-related logic, including prompt generation, response parsing, and content generation management.
*   **`bot/game/`**: This is the largest and most complex part of the application, containing all the game logic. It's further subdivided into managers, processors, and command handlers.
*   **`bot/cogs/` & `bot/command_modules/`**: These directories contain the bot's commands, organized into cogs for better management.

### Data Flow

1.  A user interacts with the bot by sending a command (e.g., `/move`).
2.  The command is received by the Discord bot in `main.py` or `bot_core.py`.
3.  The command handler in the appropriate cog (e.g., `exploration_cmds.py`) is called.
4.  The command handler calls a method on the `GameManager`.
5.  The `GameManager` delegates the request to the appropriate manager (e.g., `CharacterManager`).
6.  The manager interacts with the database via the `DBService` and `crud_utils.py` or specific CRUD modules (e.g., `item_crud.py`) to read or write data.
7.  The manager may also interact with other managers or services to perform its task (e.g., the `CombatManager` might use the `RuleEngine` to calculate damage, or AI generators might use `OpenAIService`).
8.  The result of the operation is returned up the call stack to the command handler, which then sends a response to the user.

### Key Modules and Their Responsibilities

*   **`bot/ai/`**:
    *   `prompt_context_collector.py`: Gathers all the necessary context from the game state to build a prompt for the AI.
    *   `multilingual_prompt_generator.py`: Generates the final prompt for the AI, including multilingual support.
    *   `ai_response_validator.py`: Validates the AI's response to ensure it conforms to the game's rules and data structures.
    *   `generation_manager.py`: Manages the entire AI content generation pipeline, from requesting content to processing the approved response.
    *   `ai_data_models.py`: Defines Pydantic models for structuring and validating AI-generated data (quests, NPCs, locations, items, etc.) and the `GenerationContext`.
    *   `ai_economy_generator.py`: Handles AI generation of economic entities like items, shops, and loot tables.
    *   `event_ai_generator.py`: Uses AI to generate detailed game events.
*   **`bot/database/`**:
    *   `models.py`: Defines the entire database schema using SQLAlchemy ORM.
    *   `crud_utils.py`: Provides generic, guild-aware functions for creating, reading, updating, and deleting entities.
    *   `postgres_adapter.py` & `sqlite_adapter.py`: Provide a layer of abstraction over the database drivers.
    *   `inventory_crud.py`: CRUD for character inventory items.
    *   `item_crud.py`: CRUD for item templates.
    *   `pending_generation_crud.py`: CRUD for AI-generated content awaiting moderation.
    *   `rpg_character_crud.py`: Basic CRUD for `RPGCharacter` (potential overlap with `character_related.py`).
    *   `user_settings_crud.py`: CRUD for user-specific settings.
*   **`bot/api/`**:
    *   `dependencies.py`: Sets up and provides database session dependencies for FastAPI.
    *   `main.py`: Main entry point for the FastAPI application, defines API structure, middleware, error handling, and includes various routers.
    *   `routers/`: Contains FastAPI routers for different game domains:
        *   `guild.py`: Guild initialization.
        *   `player.py`: Player CRUD operations.
        *   `character.py`: Character CRUD and XP/stats management.
        *   `rule_config.py`: Game rule configuration.
        *   `ability.py`: Ability CRUD.
        *   `game_log.py`: Game event logging.
        *   `action.py`: Character actions (ability activation, movement).
        *   `location.py`: Location CRUD.
        *   `map.py`: Map generation.
        *   `combat.py`: Combat encounter management.
        *   `rpg_character_api.py`: Additional RPG character CRUD (potential overlap).
        *   `item_router.py`: Item template CRUD.
        *   `inventory_router.py`: Character inventory management.
        *   `quest_router.py`: Quest event handling, AI quest generation, quest listing.
        *   `master.py`: Comprehensive "God Mode" tools for GMs/admins (conflict resolution, entity editing, event launching, rule setting, simulations, monitoring, AI content moderation).
*   **`bot/cogs/` & `bot/command_modules/`**:
    *   `master_commands.py`: Discord commands for GM map connection management.
    *   `action_cmds.py`: Discord commands for player actions (`interact`, `fight`, `talk`, `end_turn`) and GM party turn ending.
    *   `character_cmds.py`: Discord commands for character development (`spend_xp`) and viewing stats (`stats`).
    *   `exploration_cmds.py`: Discord commands for exploration (`look`, `move`, `check`, `whereami`).
    *   `game_setup_cmds.py`: Discord commands for player/character creation (`start_new_character`, `start`).
    *   `general_cmds.py`: General utility Discord commands (`ping`).
    *   `gm_app_cmds.py`: Extensive Discord "Master" commands for GMs/admins, mirroring many of the `master.py` API router functionalities (e.g., `gm_simulate`, `resolve_conflict`, `master_edit_npc/character/item`, `master_create_item`, `master_launch_event`, `master_set_rule`, `run_simulation`, `view_simulation_report`, `master_view_npcs/log/player_stats/map`, `review_ai/approve_ai/reject_ai/edit_ai`).
    *   `guild_config_cmds.py`: Discord commands for guild-specific bot configuration (`set_game_channel`, `set_bot_language`, `set_master_role`, etc.).
    *   `inventory_cmds.py`: Discord commands for inventory management (`inventory`, `pickup`, `equip`, `unequip`, `drop`, `use`).
    *   `party_cmds.py`: Discord commands for party management (`create`, `disband`, `join`, `leave`, `view`).
    *   `quest_cmds.py`: Discord commands for displaying active quests (`quests`).
    *   `settings_cmds.py`: Discord commands for personal player settings (`view`, `set language/timezone`).
    *   `utility_cmds.py`: Discord commands for undoing actions (`undo_action`, `undo`).
    *   `world_state_cmds.py`: Discord "Master" commands for managing custom world state flags (`set_flag`, `remove_flag`, `view_flags`).
*   **`bot/game/` (initial files):**
    *   `__init__.py`: Package `__init__` for `bot.game`, exporting core classes and exceptions.
    *   `ability_handler.py`: Placeholder for ability activation and status application logic.
    *   `action_processor.py`: Placeholder for turn processing and intra-location action handling.
*   **`bot/game/ai/` (initial files):**
    *   `__init__.py`: Package `__init__` for `bot.game.ai`, exporting AI-related classes.

### My Commitment Going Forward

I now have a much more comprehensive understanding of the project's architecture and existing functionality. I will leverage this knowledge to:

*   **Avoid redundant work**: I will thoroughly investigate the existing codebase before implementing any new features to ensure I'm not re-implementing something that already exists.
*   **Make more informed decisions**: My understanding of the project's architecture will allow me to make better decisions about where to add new functionality and how to integrate it with the existing code.
*   **Be more efficient**: By leveraging the existing framework and conventions, I will be able to develop new features more quickly and with fewer errors.

I am confident that this comprehensive review will allow me to be a much more effective contributor to this project.
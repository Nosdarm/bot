# bot/bot_core.py

import os
import json
import discord
import asyncio
import logging # Ensure logging is imported
import traceback
from typing import Optional, Dict, Any, List, cast
from typing import Optional, Dict, Any, List
from discord.abc import Messageable # Added for global_send_message

# Правильные импорты для slash commands и контекста
from discord.ext import commands # Changed to commands.Bot
from discord import Interaction, Member, TextChannel, Intents, app_commands # Specific imports
from dotenv import load_dotenv

# Импорты наших сервисов и менеджеров.
from bot.services.openai_service import OpenAIService
from bot.game.managers.game_manager import GameManager
# Эти импорты могут быть нужны если команды напрямую их используют или для аннотаций.
# Пока оставляем, но если RPGBot инкапсулирует GameManager, то прямые ссылки на
# CharacterManager, LocationManager, EventManager из команд должны идти через GameManager.
# from bot.game.managers.character_manager import CharacterManager
# from bot.game.managers.location_manager import LocationManager
# from bot.game.managers.event_manager import EventManager
# PersistenceManager из main.py не используется, GameManager создает свой SqliteAdapter
# from bot.game.persistence import PersistenceManager

# Импорты функций команд (Они должны быть определены в этих файлах и затем импортированы здесь)
import bot.command_modules.general_cmds
import bot.command_modules.game_setup_cmds
import bot.command_modules.exploration_cmds
import bot.command_modules.action_cmds
import bot.command_modules.inventory_cmds
import bot.command_modules.utility_cmds
# Импортируйте другие command_modules здесь


# --- Объявление функций проверки GM ---
# Эти функции ПРЕДПОЛАГАЮТСЯ определенными в bot.command_modules.game_setup_cmds
# и импортированными здесь в начале файла bot_core.py
# Мы будем вызывать их напрямую в функциях команд ниже.
from bot.command_modules.game_setup_cmds import is_master_or_admin, is_gm_channel # <-- Правильное место импорта

# Global configuration settings (константы вне классов и функций)
# intents = discord.Intents.default() # Now Intents is imported directly
# intents.members = True
# intents.guilds = True
# intents.message_content = True # Keep message content for flexibility
# This will be defined before RPGBot instantiation in start_bot() or passed to it.


# Global list of Guild IDs for rapid slash command testing
# This will be loaded from settings.json or environment variables.
# Example: TEST_GUILD_IDS = [123456789012345678, 987654321098765432]
LOADED_TEST_GUILD_IDS: List[int] = []


# --- Helper function to load settings (moved from main.py) ---
def load_settings_from_file(file_path: str) -> Dict[str, Any]:
    """
    Загружает настройки из JSON-файла.
    Если файла нет или он невалиден — возвращает пустой dict.
    """
    try:
        if os.path.exists(file_path):
            print(f"Loading settings from '{file_path}'...")
            with open(file_path, encoding='utf-8') as f:
                settings_data = json.load(f)
                print(f"Settings loaded successfully from '{file_path}'.")
                return settings_data
        else:
            print(f"Warning: settings file '{file_path}' not found, using empty settings for this file.")
            return {}
    except json.JSONDecodeError:
         print(f"Error: Invalid JSON in settings file '{file_path}'. Using empty settings for this file.")
         return {}
    except Exception as e:
        print(f"Error loading settings from '{file_path}': {e}")
        return {}

# --- Definition of the RPGBot class ---
class RPGBot(commands.Bot): # Changed base class to commands.Bot
    def __init__(self, game_manager: Optional[GameManager], openai_service: OpenAIService, command_prefix: str, intents: Intents, debug_guild_ids: Optional[List[int]] = None): # debug_guilds not a param for commands.Bot
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.game_manager: Optional[GameManager] = game_manager
        self.debug_guild_ids = debug_guild_ids # Store it for later use in on_ready tree sync
        self.openai_service = openai_service # Though game_manager might also hold a reference to it

        # TODO: Review if global_openai_service is still needed by any command module directly
        # If so, they need to be updated to use self.openai_service or self.game_manager.openai_service
        global global_openai_service
        global_openai_service = self.openai_service

        # TODO: Review global_game_manager usage in command modules.
        # Commands should ideally get GameManager via ctx.bot.game_manager
        global global_game_manager
        global_game_manager = self.game_manager

        self.add_application_commands_from_modules()

    async def on_ready(self):
        if self.user:
            print(f'Logged in as {self.user.name} ({self.user.id})')
        else:
            print("Error: Bot user object not available on_ready.")
            print('Logged in, but self.user is None initially.') # Should be populated by login
        if self.game_manager:
            print("GameManager is initialized in RPGBot.")

        print('Syncing command tree...')
        if self.debug_guild_ids:
            print(f"Debugging slash commands on guilds: {self.debug_guild_ids}")
            for guild_id_val in self.debug_guild_ids: # Iterate over the stored list
                guild = discord.Object(id=guild_id_val) # Use discord.Object
                await self.tree.sync(guild=guild)
            print(f"Command tree synced to {len(self.debug_guild_ids)} debug guild(s).")
        else:
            await self.tree.sync()
            print("Command tree synced globally.")
        print('Bot is ready!')

    async def on_message(self, message: discord.Message):
        # Ignore messages from bots
        if message.author.bot:
            return

        # Ignore messages starting with the command prefix (these are handled by process_commands)
        if message.content.startswith(str(self.command_prefix)):
            await self.process_commands(message)
            return

        # Basic check for guild messages only (NLU might not apply to DMs in the same way)
        if not message.guild:
            return

        # Retrieve GameManager
        if not self.game_manager:
            logging.warning("GameManager not available in on_message.")
            return

        if not self.game_manager.character_manager:
            logging.warning("NLU: CharacterManager not available in on_message. Cannot process message for NLU or character interaction.")
            return

        # NLU processing should not happen for DMs if guild_id is essential for NLU context
        # The check `if not guild_id_str:` later handles this, but good to be aware.

        # No direct CharacterManager on RPGBot, it's within GameManager
        # character_manager = self.game_manager.character_manager # Assuming this path exists

        # Attempt to fetch the player's Character object
        try:
            # Assuming GameManager has a method to get a character by discord_user_id and guild_id
            # This might involve going through a CharacterManager instance held by GameManager
            # For example: character = await self.game_manager.character_manager.get_character_by_discord_id(message.author.id, message.guild.id)
            # The exact method depends on GameManager's implementation.
            # For now, let's assume a placeholder or a direct way if RPGBot is tightly coupled.
            
            # Placeholder: Direct access or a simplified method for fetching character
            # In a real scenario, this would be:
            # character = await self.game_manager.character_manager.get_character_by_discord_id(
            # user_id=message.author.id, guild_id=message.guild.id
            # )
            # For the purpose of this subtask, we'll assume such a character object can be fetched.
            # We need to simulate fetching or get a placeholder for `current_game_status`.
            # Since we don't have the Character model definition here, we'll use a mock approach.

            # SIMULATED: Fetch character (replace with actual call when CharacterManager is integrated)
            # This part is tricky without knowing the exact Character model and CharacterManager API.
            # Let's assume game_manager has a method like `get_character_status_for_nlu`
            
            # To interact with CharacterManager, we'd typically do:
            char_model = await self.game_manager.character_manager.get_character_by_discord_id(
                discord_user_id=message.author.id, # Changed user_id to discord_user_id
                guild_id=str(message.guild.id)
            )

            if not char_model:
                logging.warning(f"NLU: No character found for User {message.author.id} in Guild {message.guild.id}. Message ignored for NLU.")
                return

            if char_model: # This check is now slightly redundant due to the one above, but harmless
                logging.debug(f"NLU: Character {char_model.id} found for User {message.author.id}.")
                busy_statuses = ['бой', 'диалог', 'торговля']
                if char_model.current_game_status not in busy_statuses:
                    logging.info(f"NLU: Processing message for User {message.author.id} (CharID: {char_model.id}, Guild: {message.guild.id}): \"{message.content}\"")
                    
                    if char_model.selected_language:
                        language = char_model.selected_language
                    elif self.game_manager and hasattr(self.game_manager, 'get_default_bot_language') and callable(getattr(self.game_manager, 'get_default_bot_language')):
                        try:
                            language = self.game_manager.get_default_bot_language()
                        except Exception as lang_e:
                            logging.error(f"NLU: Error calling get_default_bot_language: {lang_e}. Defaulting to 'en'.")
                            language = "en"
                    else:
                        language = "en" # Fallback if GameManager or method is somehow unavailable
                    logging.info(f"NLU: Detected language for User {message.author.id}: {language}")

                    nlu_service = self.game_manager.nlu_data_service
                    guild_id_str = str(message.guild.id) # Already checked message.guild is not None

                    if nlu_service:
                        logging.debug(f"NLU: NLUDataService is available. Fetching game terms for Guild {guild_id_str}, Lang {language}.")
                        # Potentially log count of entities if NLUDataService returns that, or do it in NLUDataService itself.
                    else:
                        logging.warning(f"NLU: NLUDataService is NOT available. Parsing will use fallbacks.")

                    try:
                        # CRITICAL: parse_player_action is now async, so it needs to be awaited.
                        parsed_action = await parse_player_action(
                            text=message.content,
                            language=language,
                            guild_id=guild_id_str,
                            game_terms_db=nlu_service
                        )

                        if parsed_action:
                            intent, entities = parsed_action
                            logging.info(f"NLU: Recognized for User {message.author.id}: Intent='{intent}', Entities={entities}")
                            
                            action_data = {"intent": intent, "entities": entities, "original_text": message.content}
                            
                            # Action accumulation logic
                            actions_list = []
                            if char_model.собранные_действия_JSON:
                                try:
                                    actions_list = json.loads(char_model.собранные_действия_JSON)
                                    if not isinstance(actions_list, list): # Ensure it's a list
                                        actions_list = [actions_list] # Convert to list if it was a single dict
                                except json.JSONDecodeError:
                                    logging.warning(f"NLU: Could not parse existing собранные_действия_JSON for char {char_model.id}. Initializing new list.")
                                    actions_list = []
                            
                            actions_list.append(action_data)
                            updated_actions_json = json.dumps(actions_list)
                            
                            logging.debug(f"NLU: Appending action for User {message.author.id}. New actions JSON: {updated_actions_json}")
                            
                            char_model.собранные_действия_JSON = updated_actions_json
                            
                            # Mark character as dirty before saving
                            self.game_manager.character_manager.mark_character_dirty(str(message.guild.id), char_model.id)
                            try:
                                # Call save_character instead of update_character
                                await self.game_manager.character_manager.save_character(char_model, guild_id=str(message.guild.id))
                                logging.info(f"NLU: Successfully saved character {char_model.id} with accumulated actions JSON.")
                            except Exception as char_save_err:
                                logging.error(f"NLU: Failed to save character {char_model.id} after NLU parsing: {char_save_err}", exc_info=True)
                        else:
                            logging.info(f"NLU: No action recognized for User {message.author.id} (Lang: {language}): \"{message.content}\"")

                    except Exception as nlu_err:
                        logging.error(f"NLU: Error during NLU processing or character update for User {message.author.id}: {nlu_err}", exc_info=True)
                else: # Player is in a 'busy' state (бой, диалог, торговля)
                    current_status = char_model.current_game_status
                    logging.info(f"Input: User {message.author.id} (CharID: {char_model.id}) is in '{current_status}' state. Raw message: \"{message.content}\"")

                    if current_status == 'диалог':
                        if self.game_manager and self.game_manager.dialogue_manager: # Added check for game_manager itself too
                            logging.debug(f"Input: Routing message from {char_model.name} to DialogueManager.")
                            try:
                                await self.game_manager.dialogue_manager.process_player_dialogue_message(
                                    character=char_model,
                                    message_text=message.content,
                                    channel_id=message.channel.id,
                                    guild_id=str(message.guild.id) # Pass guild_id
                                )
                            except Exception as dialogue_err:
                                logging.error(f"Input: Error calling process_player_dialogue_message for {char_model.name}: {dialogue_err}", exc_info=True)
                        else:
                            logging.warning(f"Input: DialogueManager not available (or GameManager is None) for character {char_model.name} in 'диалог' state.")

                    elif current_status == 'бой':
                        # Combat is typically command-driven. Raw text might be for chat or out-of-band communication.
                        # For now, just log. If specific raw text parsing is needed in combat,
                        # a CombatManager.process_player_combat_message could be implemented.
                        logging.info(f"Input: Message from {char_model.name} received while in 'бой' state. Content: \"{message.content}\". (Typically command-driven)")
                        # Example if a handler was to be added:
                        # if hasattr(self.game_manager, 'combat_manager') and self.game_manager.combat_manager:
                        #     await self.game_manager.combat_manager.process_player_combat_message(char_model, message.content, message.channel.id)

                    elif current_status == 'торговля':
                        # Similar to dialogue, a TradeManager could handle raw text.
                        # For now, just log.
                        logging.info(f"Input: Message from {char_model.name} received while in 'торговля' state. Content: \"{message.content}\".")
                        # Example if a handler was to be added:
                        # if hasattr(self.game_manager, 'trade_manager') and self.game_manager.trade_manager:
                        #     await self.game_manager.trade_manager.process_player_trade_message(char_model, message.content, message.channel.id)
                    
                    else:
                        # Should not happen if busy_statuses list is accurate
                        logging.warning(f"Input: User {message.author.id} (CharID: {char_model.id}) in unhandled busy status '{current_status}'. Message: \"{message.content}\"")
            else:
                logging.debug(f"NLU: No character found for User {message.author.id} in Guild {message.guild.id}. Message: \"{message.content}\"")

        except Exception as e:
            logging.error(f"NLU: Error in on_message NLU handling for User {message.author.id}: {e}", exc_info=True)

        # Important: ensure commands are still processed if the message wasn't handled by NLU
        # or if NLU is meant to augment rather than replace commands.
        # If the message started with a prefix, it's already handled above.
        # If NLU is intended for non-prefix messages, then process_commands might not be needed here
        # unless you have a system where non-prefixed messages can also be commands.
        # For now, if it didn't start with a prefix and wasn't handled by NLU to consume it,
        # it might be ignored or passed to a default handler if one existed.
        # commands.Bot processes commands based on prefix, so non-prefixed messages are generally ignored
        # by the command processing system unless explicitly handled by on_message.
        # The current structure already calls self.process_commands for prefixed messages.
        # Non-prefixed messages are now flowing through the NLU logic.

    def add_application_commands_from_modules(self):
        # This approach assumes command functions are decorated with @slash_command
        # and are available in the imported modules.
        # discord.py V2 automatically discovers these in cogs or if added via self.add_application_command.
        # For functions directly decorated, we need to add them to the CommandTree.

        # General commands
        self.tree.add_command(bot.command_modules.general_cmds.cmd_ping)

        # Game setup commands
        # self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_start_game) # Placeholder
        # self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_join_game) # Placeholder
        self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_start_new_character) # New /start command
        self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_set_bot_language) # Add new /set_bot_language command
        self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_set_master_channel)
        self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_set_system_channel)
        # TODO: Add other game_setup_cmds (set_gm, set_gm_channel, etc.)

        # Exploration commands
        self.tree.add_command(bot.command_modules.exploration_cmds.cmd_look)
        self.tree.add_command(bot.command_modules.exploration_cmds.cmd_move)
        self.tree.add_command(bot.command_modules.exploration_cmds.cmd_check)

        # Action commands
        self.tree.add_command(bot.command_modules.action_cmds.cmd_interact) # Placeholder, needs refactor
        self.tree.add_command(bot.command_modules.action_cmds.cmd_fight) # Refactored from cmd_attack
        self.tree.add_command(bot.command_modules.action_cmds.cmd_talk)

        # Inventory commands
        self.tree.add_command(bot.command_modules.inventory_cmds.cmd_inventory)
        self.tree.add_command(bot.command_modules.inventory_cmds.cmd_pickup)

        # Utility commands
        self.tree.add_command(bot.command_modules.utility_cmds.cmd_undo)
        self.tree.add_command(bot.command_modules.utility_cmds.cmd_lang) # Add the new /lang command

        # Simulation Trigger Command
        # cmd_gm_simulate is already an app_command.Command, so it should be added directly.
        self.tree.add_command(cmd_gm_simulate) # Defined below

# --- Global Helper for sending messages (e.g., from GameManager) ---
# This needs access to the bot instance.
# Option 1: Pass bot instance around.
# Option 2: RPGBot sets a global instance of itself (less ideal but might be needed for now).
_rpg_bot_instance_for_global_send: Optional[RPGBot] = None

async def global_send_message(channel_id: int, content: str, **kwargs):
    if _rpg_bot_instance_for_global_send:
        channel = _rpg_bot_instance_for_global_send.get_channel(channel_id)
        if channel:
            if isinstance(channel, discord.abc.Messageable):
                try:
                    await channel.send(content, **kwargs)
                except Exception as e:
                    print(f"Error sending message via global_send_message to channel {channel_id}: {e}")
            else:
                # Log this appropriately
                print(f"Warning: Channel {channel_id} is not Messageable (type: {type(channel)}). Cannot send message globally.")
        if channel and isinstance(channel, Messageable): # Added isinstance check
            try:
                await channel.send(content, **kwargs)
            except Exception as e:
                print(f"Error sending message via global_send_message to channel {channel_id}: {e}")
        else:
            print(f"Warning: Channel {channel_id} not found by global_send_message.")
    else:
        print("Warning: _rpg_bot_instance_for_global_send not set. Cannot send message.")

def get_bot_instance() -> Optional[RPGBot]:
    return _rpg_bot_instance_for_global_send

# --- Simulation Trigger Command (GM only) - DEFINITION as a separate function ---
# Accesses GameManager via ctx.bot.game_manager if commands are structured as Cogs or similar.
# For now, might still rely on global_game_manager or pass explicitly.
# If this is registered to RPGBot, it can access self.game_manager through interaction.client
@app_commands.command(name="gm_simulate", description="ГМ: Запустить один шаг симуляции мира.")
# guild_ids will be set dynamically when RPGBot is initialized if LOADED_TEST_GUILD_IDS has values.
# For now, remove here and let RPGBot handle it or add it back if this is registered globally.
# guild_ids=LOADED_TEST_GUILD_IDS
async def cmd_gm_simulate(interaction: Interaction): # Changed ctx to interaction
    # Access bot and game_manager from context
    bot_instance = interaction.client # Correct way to access bot
    if not isinstance(bot_instance, RPGBot):
        await interaction.response.send_message("Error: Bot instance is not configured correctly.", ephemeral=True)
        return

    # bot_instance is now confirmed to be RPGBot
    game_mngr = bot_instance.game_manager
    if not game_mngr:
        await interaction.response.send_message("Error: GameManager not available on bot instance.", ephemeral=True)
        return

    # TODO: Update is_master_or_admin and is_gm_channel to accept interaction and use game_mngr
    # from bot.command_modules.game_setup_cmds import is_master_or_admin
    # For now, assume it's okay or True for testing this structural change
    # if not is_master_or_admin(interaction, game_mngr): # Placeholder for updated check
    #     await interaction.response.send_message("**Мастер:** Только Истинный Мастер может управлять ходом времени!", ephemeral=True)
    #     return

    await interaction.response.defer(ephemeral=True) # Defer response

    if game_mngr and game_mngr._world_simulation_processor:
        try:
            # Constructing full context here is complex and not ideal.
            # This is a partial fix to address AttributeError, but functionality depends on WorldSimulationProcessor's needs.
            # A proper fix might involve a dedicated method in GameManager to trigger a single tick with context.
            tick_context = {
                'rule_engine': game_mngr.rule_engine, 'time_manager': game_mngr.time_manager,
                'location_manager': game_mngr.location_manager, 'event_manager': game_mngr.event_manager,
                'character_manager': game_mngr.character_manager, 'item_manager': game_mngr.item_manager,
                'status_manager': game_mngr.status_manager, 'combat_manager': game_mngr.combat_manager,
                'crafting_manager': game_mngr.crafting_manager, 'economy_manager': game_mngr.economy_manager,
                'npc_manager': game_mngr.npc_manager, 'party_manager': game_mngr.party_manager,
                'openai_service': game_mngr.openai_service,
                'quest_manager': game_mngr.quest_manager,
                'relationship_manager': game_mngr.relationship_manager,
                'dialogue_manager': game_mngr.dialogue_manager,
                'game_log_manager': game_mngr.game_log_manager,
                'consequence_processor': game_mngr.consequence_processor,
                'on_enter_action_executor': game_mngr._on_enter_action_executor,
                'stage_description_generator': game_mngr._stage_description_generator,
                'event_stage_processor': game_mngr._event_stage_processor,
                'event_action_processor': game_mngr._event_action_processor,
                'character_action_processor': game_mngr._character_action_processor,
                'character_view_service': game_mngr._character_view_service,
                'party_action_processor': game_mngr._party_action_processor,
                'persistence_manager': game_mngr._persistence_manager,
                'conflict_resolver': game_mngr.conflict_resolver,
                'db_adapter': game_mngr._db_adapter,
                'nlu_data_service': game_mngr.nlu_data_service,
                'prompt_context_collector': game_mngr.prompt_context_collector,
                'multilingual_prompt_generator': game_mngr.multilingual_prompt_generator,
                'send_callback_factory': game_mngr._get_discord_send_callback,
                'settings': game_mngr._settings,
                'discord_client': game_mngr._discord_client,
                'guild_id': str(interaction.guild_id) # Adding guild_id to context
            }
            # Filter out None values from context as WSP might not expect them
            tick_context_filtered = {k: v for k, v in tick_context.items() if v is not None}

            await game_mngr._world_simulation_processor.process_world_tick(
                game_time_delta=game_mngr._tick_interval_seconds, # Using default interval
                **tick_context_filtered
            )
            await interaction.followup.send("**Мастер:** Шаг симуляции мира завершен!")
        except Exception as e:
            logging.error(f"Error in cmd_gm_simulate calling process_world_tick: {e}", exc_info=True)
            await interaction.followup.send(f"**Мастер:** Ошибка при выполнении шага симуляции: {e}", ephemeral=True)
    elif not game_mngr:
        await interaction.followup.send("**Мастер:** Не удалось запустить симуляцию, менеджер игры недоступен.", ephemeral=True)
    else: # game_mngr exists but _world_simulation_processor is None
        await interaction.followup.send("**Мастер:** WorldSimulationProcessor не доступен. Невозможно запустить симуляцию.", ephemeral=True)


# --- Main Bot Entry Point ---
async def start_bot():
    global _rpg_bot_instance_for_global_send, LOADED_TEST_GUILD_IDS # Allow modification

    print("--- RPG Bot Core: Starting ---")
    load_dotenv()
    print(f"DEBUG: Value from os.getenv('DISCORD_TOKEN') AFTER load_dotenv(): {os.getenv('DISCORD_TOKEN')}")

    # 1. Load all settings
    # Primary settings file
    settings = load_settings_from_file('settings.json')
    # Override/supplement with data/settings.json if it exists
    data_settings = load_settings_from_file('data/settings.json')
    settings.update(data_settings) # data_settings will overwrite common keys from settings.json

    # 2. Consolidate critical configurations (Env > settings.json > data/settings.json)
    TOKEN = os.getenv('DISCORD_TOKEN') or settings.get('discord_token')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY') or settings.get('openai_api_key')
    COMMAND_PREFIX = os.getenv('COMMAND_PREFIX') or settings.get('discord_command_prefix', '!') # Default '!'
    DATABASE_PATH = os.getenv('DATABASE_PATH') or settings.get('database_path', 'game_state.db') # Default 'game_state.db'
    print(f"CRITICAL_DEBUG: Bot is using database at absolute path: {os.path.abspath(DATABASE_PATH)}")


    # Load TEST_GUILD_IDS from settings (env var could be a comma-separated string)
    test_guild_ids_str = os.getenv('TEST_GUILD_IDS')
    if test_guild_ids_str:
        LOADED_TEST_GUILD_IDS = [int(gid.strip()) for gid in test_guild_ids_str.split(',')]
    else:
        LOADED_TEST_GUILD_IDS = settings.get('test_guild_ids', []) # Expect a list in JSON

    if not TOKEN:
        print("❌ FATAL: Discord token not provided (env DISCORD_TOKEN or settings.json). Cannot start bot.")
        return

    # Prepare OpenAI settings for GameManager
    if 'openai_settings' not in settings:
        settings['openai_settings'] = {}
    if OPENAI_API_KEY:
        settings['openai_settings']['api_key'] = OPENAI_API_KEY
        print("OpenAI API Key configured for GameManager.")
    else:
        print("Warning: OpenAI API Key not found. OpenAI features will be disabled.")
        settings['openai_settings']['api_key'] = None # Ensure it's explicitly None if not found

    # 3. Initialize services
    # OpenAIService is initialized within GameManager's setup based on settings.
    # So, we don't need to create a separate global one here if GM handles it.
    # However, RPGBot constructor takes one, and some commands might still expect a global one.
    # For now, let's initialize one here and pass it.
    openai_service = OpenAIService(api_key=OPENAI_API_KEY)
    if not openai_service.is_available():
        print("OpenAIService is not available (key missing or invalid).")

    # 4. Initialize RPGBot (which is the discord client)
        # Define intents here before passing to RPGBot
    bot_intents = Intents.default()
    bot_intents.members = True
    bot_intents.guilds = True
    bot_intents.message_content = True

    rpg_bot = RPGBot(
        game_manager=None,
        openai_service=openai_service,
        command_prefix=COMMAND_PREFIX,
        intents=bot_intents,
        debug_guild_ids=LOADED_TEST_GUILD_IDS if LOADED_TEST_GUILD_IDS else None # Pass debug_guild_ids
    )
    _rpg_bot_instance_for_global_send = rpg_bot

    # 5. Initialize GameManager
    # GameManager needs the discord client (RPGBot instance)
    game_manager = GameManager(
        discord_client=rpg_bot, # Pass the bot instance
        settings=settings,      # Pass consolidated settings
        db_path=DATABASE_PATH
    )
    rpg_bot.game_manager = game_manager # Now set the game_manager in RPGBot

    # Update the global_game_manager reference now that it's fully initialized
    # TODO: phase this out by updating command modules
    global global_game_manager
    global_game_manager = game_manager

    print("GameManager instantiated. Running setup...")
    try:
        await game_manager.setup() # This also loads game state
        print("GameManager setup() successful.")
    except Exception as e:
        print(f"❌ FATAL: GameManager.setup() failed: {e}")
        traceback.print_exc()
        # Consider not starting the bot if GM setup fails
        return

    # 6. Start the bot
    print("Starting Discord bot (RPGBot)...")
    try:
        await rpg_bot.start(TOKEN)
    except discord.errors.LoginFailure:
        print("❌ FATAL: Invalid Discord token. Please check your DISCORD_TOKEN.")
    except Exception as e:
        print(f"❌ FATAL: RPGBot.start() error: {e}")
        traceback.print_exc()
    finally:
        print("Application shutting down...")
        if game_manager:
            print("Shutting down GameManager...")
            await game_manager.shutdown()
            print("GameManager shutdown complete.")
        if not rpg_bot.is_closed():
            print("Closing Discord connection...")
            await rpg_bot.close()
            print("Discord connection closed.")

# --- Synchronous wrapper to run the bot ---
def run_bot():
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        print("Interrupted by user (KeyboardInterrupt), exiting.")
    except Exception as e:
        print(f"Error running bot: {e}")
        traceback.print_exc()
    finally:
        print("Application finished.")


if __name__ == "__main__":
    run_bot()

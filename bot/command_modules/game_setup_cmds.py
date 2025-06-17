import discord # Added for discord.Role
from discord import Interaction, app_commands, Member, Role # Added Role
from discord.ext import commands
from typing import Optional, TYPE_CHECKING
import logging  # For logging

from bot.game.managers.character_manager import CharacterAlreadyExistsError

if TYPE_CHECKING:
    from bot.bot_core import RPGBot  # For type hinting self.bot
    from bot.game.managers.game_manager import GameManager
    from bot.database.models import Player, Location # Added
    from bot.services.db_service import DBService # Added
    from bot.game.managers.location_manager import LocationManager # Added
    import uuid # Added

# Helper functions - will become methods or static methods in the Cog
# These functions are used by commands in this Cog.


async def is_master_or_admin_check(interaction: Interaction) -> bool:
    """Checks if the user is a bot admin or has the 'Master' role in the guild."""
    # Access bot instance from interaction.client
    bot_instance = interaction.client  # type: RPGBot
    if (not hasattr(bot_instance, 'game_manager') or  # Break before or
            bot_instance.game_manager is None):
        logging.warning(
            "is_master_or_admin_check: GameManager not found on bot instance."
        )
        return False  # Or raise an error

    game_mngr: "GameManager" = bot_instance.game_manager

    # Ensure settings are loaded in GameManager
    if not game_mngr._settings:  # Accessing protected member, GM
        logging.warning(
            "is_master_or_admin_check: Settings not loaded in GameManager."
        )
        return False

    bot_admin_ids = [
        str(id_val) for id_val in game_mngr._settings.get('bot_admins', [])
    ]
    if str(interaction.user.id) in bot_admin_ids:
        return True

    if not interaction.guild:  # Should not happen for guild commands but good check
        return False

    master_role_id = game_mngr.get_master_role_id(
        str(
            interaction.guild_id
        )  # Wrap str() argument
    )
    if master_role_id and isinstance(interaction.user, Member):
        master_role = interaction.guild.get_role(int(master_role_id))
        if master_role and master_role in interaction.user.roles:
            return True
    return False


async def is_gm_channel_check(interaction: Interaction) -> bool:
    """Checks if the command is used in the designated GM channel for the guild."""
    bot_instance = interaction.client  # type: RPGBot
    if (not hasattr(bot_instance, 'game_manager') or  # Break before or
            bot_instance.game_manager is None):
        logging.warning(
            "is_gm_channel_check: GameManager not found on bot instance."
        )
        return False

    game_mngr: "GameManager" = bot_instance.game_manager
    if not interaction.guild_id:
        return False

    gm_channel_id = game_mngr.get_gm_channel_id(str(interaction.guild_id))
    return gm_channel_id == interaction.channel_id


class GameSetupCog(commands.Cog, name="Game Setup"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    async def is_master_or_admin(self, interaction: Interaction) -> bool:
        return await is_master_or_admin_check(interaction)

    async def is_gm_channel(self, interaction: Interaction) -> bool:
        return await is_gm_channel_check(interaction)

    @app_commands.command(
        name="start_new_character",
        description="Начать игру новым персонажем в текущем канале Discord."
    )
    @app_commands.describe(
        character_name="Имя вашего нового персонажа.",
        player_language=(
            "Язык, на котором вы будете играть (например, 'ru' или 'en')."
        )
    )
    async def cmd_start_new_character(
        self,
        interaction: Interaction,
        character_name: str,
        player_language: Optional[str] = None
    ):
        logging.info(f"Command /start_new_character received from {interaction.user.name} ({interaction.user.id}) with arguments: character_name={character_name}, player_language={player_language}")
        if not interaction.guild:
            await interaction.response.send_message(
                "Эту команду можно использовать только на сервере.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        bot_instance = self.bot  # type: RPGBot
        if not hasattr(bot_instance, 'game_manager') or \
           bot_instance.game_manager is None:
            await interaction.followup.send(
                "GameManager is not available. "
                "Please try again later or contact an admin.",
                ephemeral=True
            )
            return
        game_mngr: "GameManager" = bot_instance.game_manager

        try:
            effective_language = (
                player_language or game_mngr.get_default_bot_language()
            )
            # The method signature for start_new_character_session in
            # GameManager is (self, user_id: int, guild_id: str,
            # character_name: str)
            # It does not take discord_user_name, channel_id,
            # selected_language directly like this.
            # This call needs to be updated based on the actual signature
            # implemented in GameManager.
            # For now, assuming the subtask to implement
            # start_new_character_session will define its signature.
            # Based on the provided signature for
            # GameManager.start_new_character_session:
            # (self, user_id: int, guild_id: str, character_name: str)
            # -> Optional["Character"]
            # The call here needs adjustment. The current subtask is to fix
            # game_setup_cmds.py access,
            # and then implement the method in GameManager.
            # The success, message tuple return is also not matching.
            # Let's adjust the call to the specified signature and handle the
            # Character return.
            new_character = await game_mngr.start_new_character_session(
                user_id=interaction.user.id,
                guild_id=str(interaction.guild_id),
                character_name=character_name
                # selected_language and discord_user_name would need to be
                # handled differently, e.g. by setting language on the
                # character object afterwards if create_character doesn't take
                # it.
            )

            if new_character:
                logging.info(f"Command /start_new_character processed for {interaction.user.name} ({interaction.user.id}). Character created: {bool(new_character)}")
                # If selected_language was provided and Character model has
                # selected_language field
                if (player_language and  # Break before and
                        hasattr(new_character, 'selected_language')):
                    if (game_mngr.character_manager and  # Break before and
                            hasattr(game_mngr.character_manager, 'save_character_field')):
                        await game_mngr.character_manager.save_character_field(
                            guild_id=str(interaction.guild_id),
                            character_id=new_character.id,
                            field_name='selected_language',
                            value=player_language
                        )
                        # Optionally update the in-memory object too
                        new_character.selected_language = player_language

                char_name_display = getattr(
                    new_character, 'name', character_name
                )  # Fallback to input name
                if hasattr(new_character, 'name_i18n') and \
                   isinstance(new_character.name_i18n, dict):
                    char_name_display = new_character.name_i18n.get(
                        effective_language, char_name_display
                    )

                await interaction.followup.send(
                    f"Персонаж '{char_name_display}' успешно создан! "
                    f"Язык: {effective_language}.",
                    ephemeral=True
                )
            else:
                logging.warning(f"Command /start_new_character failed for {interaction.user.name} ({interaction.user.id}). Reason: Failed to create character.")
                # This 'else' handles cases where start_new_character_session returns None
                # for reasons other than CharacterAlreadyExistsError (e.g., other exceptions caught in GameManager,
                # or if create_character itself returned None for a non-exception reason like a name check).
                logging.warning(f"Command /start_new_character failed for {interaction.user.name} ({interaction.user.id}). Reason: Failed to create character (GameManager returned None).")
                await interaction.followup.send(
                    f"Не удалось создать персонажа '{character_name}'.", # Generic failure
                    ephemeral=True
                )
        except CharacterAlreadyExistsError:
            logging.info(f"User {interaction.user.name} ({interaction.user.id}) tried to create character '{character_name}' in guild {interaction.guild_id} but one already exists.")
            await interaction.followup.send(
                "У вас уже есть персонаж в этой игре. Вы не можете создать еще одного.",
                ephemeral=True
            )
        except Exception as e:
            logging.error(f"Command /start_new_character encountered an unexpected exception for {interaction.user.name} ({interaction.user.id}). Exception: {e}", exc_info=True)
            await interaction.followup.send(
                f"Произошла непредвиденная ошибка при создании персонажа: {e}", # Unexpected error
                ephemeral=True
            )

    @app_commands.command(
        name="set_bot_language",
        description=(
            "Установить язык бота для этой гильдии (только для Мастера)."
        )
    )
    @app_commands.describe(language_code="Код языка (например, 'ru', 'en').")
    async def cmd_set_bot_language(
        self, interaction: Interaction, language_code: str
    ):
        if not await self.is_master_or_admin(interaction):
            await interaction.response.send_message(
                "Только Мастер или администратор может менять язык бота.",
                ephemeral=True
            )
            return

        bot_instance = self.bot  # type: RPGBot
        if not hasattr(bot_instance, 'game_manager') or \
           bot_instance.game_manager is None:
            await interaction.response.send_message(
                "GameManager is not available. "
                "Please try again later or contact an admin.",
                ephemeral=True
            )
            return
        game_mngr: "GameManager" = bot_instance.game_manager

        success = await game_mngr.set_default_bot_language(
            language_code, str(interaction.guild_id)
        )
        if success:
            await interaction.response.send_message(
                f"Язык бота для этой гильдии установлен на '{language_code}'.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Не удалось установить язык бота. Проверьте логи.",
                ephemeral=True
            )

    @app_commands.command(
        name="set_master_channel",
        description=(
            "Установить этот канал как канал Мастера (только для Мастера)."
        )
    )
    async def cmd_set_master_channel(self, interaction: Interaction):
        if not await self.is_master_or_admin(interaction):
            await interaction.response.send_message(
                "Только Мастер может назначить этот канал.", ephemeral=True
            )
            return
        if not interaction.guild_id or not interaction.channel_id:
            await interaction.response.send_message(
                "Эта команда должна быть использована в канале сервера.",
                ephemeral=True
            )
            return

        bot_instance = self.bot  # type: RPGBot
        if not hasattr(bot_instance, 'game_manager') or \
           bot_instance.game_manager is None:
            await interaction.response.send_message(
                "GameManager is not available. "
                "Please try again later or contact an admin.",
                ephemeral=True
            )
            return
        game_mngr: "GameManager" = bot_instance.game_manager

        if game_mngr.db_service:
            await game_mngr.db_service.set_guild_setting(
                str(interaction.guild_id),
                'master_notification_channel_id',
                str(interaction.channel_id)
            )
            await interaction.response.send_message(
                f"Канал <#{interaction.channel_id}> назначен как "
                "канал Мастера для этой гильдии.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Не удалось сохранить настройку канала Мастера "
                "(DB service unavailable).",
                ephemeral=True
            )

    @app_commands.command(
        name="set_system_channel",
        description=(
            "Установить этот канал как системный канал (только для Мастера)."
        )
    )
    async def cmd_set_system_channel(self, interaction: Interaction):
        if not await self.is_master_or_admin(interaction):
            await interaction.response.send_message(
                "Только Мастер может назначить этот канал.", ephemeral=True
            )
            return
        if not interaction.guild_id or not interaction.channel_id:
            await interaction.response.send_message(
                "Эта команда должна быть использована в канале сервера.",
                ephemeral=True
            )
            return

        bot_instance = self.bot  # type: RPGBot
        if not hasattr(bot_instance, 'game_manager') or \
           bot_instance.game_manager is None:
            await interaction.response.send_message(
                "GameManager is not available. "
                "Please try again later or contact an admin.",
                ephemeral=True
            )
            return
        game_mngr: "GameManager" = bot_instance.game_manager

        if game_mngr.db_service:
            await game_mngr.db_service.set_guild_setting(
                str(interaction.guild_id),
                'system_notification_channel_id',
                str(interaction.channel_id)
            )
            await interaction.response.send_message(
                f"Канал <#{interaction.channel_id}> назначен как "
                "системный для этой гильдии.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Не удалось сохранить настройку системного канала "
                "(DB service unavailable).",
                ephemeral=True
            )

    @app_commands.command(
        name="set_master_role",
        description="Установить роль Мастера для этой гильдии (только для Мастера/Администратора)."
    )
    @app_commands.describe(role="Роль Discord, которая будет назначена как роль Мастера.")
    async def cmd_set_master_role(self, interaction: Interaction, role: discord.Role):
        logging.info(f"Command /set_master_role received from {interaction.user.name} ({interaction.user.id}) with role: {role.name} ({role.id})")
        if not await self.is_master_or_admin(interaction):
            await interaction.response.send_message(
                "Только Мастер или администратор может назначать роль Мастера.",
                ephemeral=True
            )
            logging.warning(f"User {interaction.user.name} ({interaction.user.id}) attempted to use /set_master_role without permissions in guild {interaction.guild_id}.")
            return

        if not interaction.guild_id:
            await interaction.response.send_message(
                "Эта команда должна быть использована на сервере.",
                ephemeral=True
            )
            return

        bot_instance = self.bot  # type: RPGBot
        if not hasattr(bot_instance, 'game_manager') or \
           bot_instance.game_manager is None or \
           not hasattr(bot_instance.game_manager, 'db_service') or \
           bot_instance.game_manager.db_service is None:
            await interaction.response.send_message(
                "GameManager или DBService не доступен. Пожалуйста, попробуйте позже или свяжитесь с администратором.",
                ephemeral=True
            )
            logging.error(f"GameManager or DBService not available for /set_master_role in guild {interaction.guild_id}.")
            return

        game_mngr: "GameManager" = bot_instance.game_manager

        try:
            success = await game_mngr.db_service.set_guild_setting(
                str(interaction.guild_id),
                'master_role_id',
                str(role.id)
            )
            if success:
                await interaction.response.send_message(
                    f"Роль '{role.name}' была успешно назначена как роль Мастера для этой гильдии.",
                    ephemeral=True
                )
                logging.info(f"Master role set to '{role.name}' ({role.id}) for guild {interaction.guild_id} by {interaction.user.name}.")
            else:
                await interaction.response.send_message(
                    "Не удалось сохранить настройку роли Мастера. Проверьте логи для деталей.",
                    ephemeral=True
                )
                logging.error(f"Failed to set master role (DBService.set_guild_setting returned False) for guild {interaction.guild_id} by {interaction.user.name}.")
        except Exception as e:
            await interaction.response.send_message(
                f"Произошла ошибка при установке роли Мастера: {e}",
                ephemeral=True
            )
            logging.error(f"Exception occurred in /set_master_role for guild {interaction.guild_id} by {interaction.user.name}: {e}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GameSetupCog(bot))  # type: ignore
    print("GameSetupCog loaded.")

    @app_commands.command(name="start", description="Начать новое приключение и создать вашего персонажа.")
    async def cmd_start(self, interaction: Interaction):
        logging.info(f"Command /start received from {interaction.user.name} ({interaction.user.id}) in guild {interaction.guild.id if interaction.guild else 'DM'}")
        if not interaction.guild:
            await interaction.response.send_message("Эту команду можно использовать только на сервере.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        game_mngr: "GameManager" = self.bot.game_manager
        if not game_mngr:
            logging.error(f"/start command by {interaction.user.name} ({interaction.user.id}): GameManager not found.")
            await interaction.followup.send("Менеджер игры недоступен. Пожалуйста, попробуйте позже или свяжитесь с администратором.", ephemeral=True)
            return

        db_service: "DBService" = game_mngr.db_service
        if not db_service:
            logging.error(f"/start command by {interaction.user.name} ({interaction.user.id}): DBService not found.")
            await interaction.followup.send("Сервис базы данных недоступен. Пожалуйста, попробуйте позже или свяжитесь с администратором.", ephemeral=True)
            return

        loc_mngr: "LocationManager" = game_mngr.location_manager
        if not loc_mngr:
            logging.error(f"/start command by {interaction.user.name} ({interaction.user.id}): LocationManager not found.")
            await interaction.followup.send("Менеджер локаций недоступен. Пожалуйста, попробуйте позже или свяжитесь с администратором.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild.id)
        discord_id_str = str(interaction.user.id)

        try:
            # Check for existing Player
            existing_player_data = await db_service.get_entity_by_conditions(
                table_name='players',
                conditions={'discord_id': discord_id_str, 'guild_id': guild_id_str},
                model_class=Player,
                single_entity=True
            )

            if existing_player_data:
                logging.info(f"/start command by {discord_id_str} in guild {guild_id_str}: Player already exists.")
                await interaction.followup.send("У вас уже есть персонаж на этом сервере!", ephemeral=True)
                return

            # Determine Starting Location
            # Assumption: "village_square" is a known static_id for the starting location.
            # This might need to be fetched from rules or a fixed configuration if it changes.
            starting_location: Optional[Location] = await loc_mngr.get_location_by_static_id(guild_id_str, "village_square")
            if not starting_location:
                logging.error(f"/start command for guild {guild_id_str}: Starting location with static_id 'village_square' not found.")
                await interaction.followup.send("Не удалось найти стартовую локацию. Обратитесь к администратору.", ephemeral=True)
                return

            starting_location_id = starting_location.id

            # Determine Languages
            guild_main_lang = await game_mngr.get_rule(guild_id_str, 'default_language', 'en')
            player_selected_lang = guild_main_lang

            # Prepare Player Data
            player_name = interaction.user.display_name
            name_i18n_dict = {'en': player_name}
            if guild_main_lang != 'en' and guild_main_lang is not None : # Ensure guild_main_lang is not None
                name_i18n_dict[guild_main_lang] = player_name

            player_id = str(uuid.uuid4())

            player_data = {
                "id": player_id,
                "discord_id": discord_id_str,
                "guild_id": guild_id_str,
                "name_i18n": name_i18n_dict,
                "current_location_id": starting_location_id,
                "selected_language": player_selected_lang,
                "xp": 0,
                "level": 1,
                "unspent_xp": 0,
                "gold": 10, # Starting gold, can be made a rule
                "current_game_status": "active", # Or "new", "tutorial"
                "is_alive": True,
                "is_active": True,
                "stats": {}, # e.g., {"strength": 10, "dexterity": 10, ...} - can be rules-based
                "hp": 100.0, # Default HP, can be rules-based
                "max_health": 100.0, # Default Max HP
                "mp": 50, # Default MP
                "attack": 5, # Default attack
                "defense": 5, # Default defense
                "race": None, # To be set later
                "character_class": None, # To be set later
                "collected_actions_json": {}, # Or [] if it's a list
                "action_queue": {}, # Or []
                "state_variables": {},
                "status_effects": {}, # Or []
                "skills_data_json": {},
                "abilities_data_json": {},
                "spells_data_json": {},
                "flags_json": {},
                "active_quests": {}, # Or []
                "known_spells": {}, # Or []
                "spell_cooldowns": {},
                "inventory": {}, # Or []
                "effective_stats_json": {},
                "party_id": None,
                "current_party_id": None,
                "current_action": None
            }

            # Create Player Entity
            new_player = await db_service.create_entity(model_class=Player, entity_data=player_data)

            if new_player:
                logging.info(f"New player created for {discord_id_str} in guild {guild_id_str}. Player ID: {player_id}")
                # TODO: Use i18n for this message
                welcome_message = (
                    f"Добро пожаловать в приключение, {player_name}!\n"
                    f"Ваш персонаж был успешно создан. Вы начинаете в локации: {starting_location.name_i18n.get(player_selected_lang, starting_location.name_i18n.get('en', 'Неизвестная локация'))}.\n"
                    f"Удачи!"
                )
                await interaction.followup.send(welcome_message, ephemeral=True)
            else:
                logging.error(f"Failed to create player for {discord_id_str} in guild {guild_id_str}.")
                await interaction.followup.send("Произошла ошибка при создании вашего персонажа. Пожалуйста, попробуйте еще раз.", ephemeral=True)

        except Exception as e:
            logging.error(f"Error in /start command for {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send("Произошла непредвиденная ошибка. Пожалуйста, сообщите администратору.", ephemeral=True)

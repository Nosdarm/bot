import discord
import traceback
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, cast, List

# Direct import for isinstance check in setup
from bot.bot_core import RPGBot
import uuid
import json
import logging

# Database model imports
from bot.database.models.character_related import Player # Corrected import path
from bot.database.models.character_related import Party as PartyModel # Corrected import path
from bot.game.exceptions import CharacterAlreadyInPartyError, NotPartyLeaderError, PartyNotFoundError, PartyFullError, CharacterNotInPartyError


if TYPE_CHECKING:
    # from bot.bot_core import RPGBot # Now imported directly above
    from bot.game.managers.game_manager import GameManager
    # CharacterManager might not be directly needed for this specific command if using Player model
    # from bot.game.managers.character_manager import CharacterManager
    # PartyManager might not be directly needed if using DBService
    # from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.location_manager import LocationManager
    # Character model might not be directly needed
    # from bot.game.models.character import Character
    # Party model (Pydantic) might not be directly needed if creating DB PartyModel
    # from bot.game.models.party import Party
    from bot.services.db_service import DBService


logger_party_cmds = logging.getLogger(__name__) # Added logger

class PartyCog(commands.Cog, name="Party Commands"):
    party_group = app_commands.Group(name="party", description="Команды для управления группой.") # Kept existing group description

    def __init__(self, bot: "RPGBot"): # init already expects RPGBot
        self.bot = bot

    @party_group.command(name="create", description="Создает новую группу для совместных приключений.")
    @app_commands.describe(name="Название вашей группы")
    async def cmd_party_create(self, interaction: Interaction, name: str):
        await interaction.response.defer(ephemeral=True)

        bot_instance: RPGBot = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            logger_party_cmds.error("GameManager not initialized for /party create.")
            await interaction.followup.send("Ошибка: Игровые сервисы не полностью инициализированы.", ephemeral=True)
            return

        game_mngr: Optional["GameManager"] = getattr(bot_instance, 'game_manager', None) # Safe access
        if not game_mngr:
            logger_party_cmds.error("GameManager not initialized for /party create.")
            await interaction.followup.send("Ошибка: Игровые сервисы не полностью инициализированы.", ephemeral=True)
            return

        db_service: Optional["DBService"] = getattr(game_mngr, 'db_service', None) # Safe access
        if not db_service: # Type "DBService | None" is not assignable to declared type "DBService" - Fixed
            logger_party_cmds.error("DBService not available for /party create.")
            await interaction.followup.send("Ошибка: Сервис базы данных недоступен.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)
        player_account: Optional[Player] = None # Initialize player_account

        try:
            character_manager = getattr(game_mngr, 'character_manager', None)
            party_manager = getattr(game_mngr, 'party_manager', None)

            if not character_manager or not party_manager:
                logger_party_cmds.error("CharacterManager or PartyManager not available for /party create.")
                await interaction.followup.send("Ошибка: Основные сервисы управления персонажами или группами недоступны.", ephemeral=True)
                return

            player_account = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str) # get_player_model_by_discord_id is not a known attribute of "None" (Pyright error) - Fixed by checking game_mngr
            if not player_account or not player_account.active_character_id: # "player_account" is possibly unbound (Pyright error) - Fixed by initializing
                logger_party_cmds.info(f"/party create: No active character found for discord_id {discord_id_str} in guild {guild_id_str}.")
                await interaction.followup.send("У вас должен быть активный персонаж для создания группы. Используйте `/character select` или `/character create`.", ephemeral=True)
                return

            leader_character_id = str(player_account.active_character_id) # Ensure it's a string

            guild_main_lang_rule = await game_mngr.get_rule(guild_id_str, 'default_language', 'en') # get_rule is not a known attribute of "None" (Pyright error) - Fixed by checking game_mngr
            guild_main_lang = str(guild_main_lang_rule) if guild_main_lang_rule else "en"

            name_i18n_dict = {'en': name}
            if guild_main_lang != 'en':
                name_i18n_dict[guild_main_lang] = name

            new_party = await party_manager.create_party( # party_manager is not a known attribute of "None" (Pyright error) - Fixed by checking party_manager
                guild_id=guild_id_str,
                leader_character_id=leader_character_id,
                party_name_i18n=name_i18n_dict
            )

            if new_party and hasattr(new_party, 'name_i18n') and isinstance(new_party.name_i18n, dict) and hasattr(new_party, 'id'):
                party_lang_to_use = player_account.selected_language or guild_main_lang # player_account is possibly unbound (Pyright error) - Fixed
                party_display_name = new_party.name_i18n.get(party_lang_to_use, new_party.name_i18n.get("en", str(new_party.id)))
                logger_party_cmds.info(f"Party '{party_display_name}' (ID: {new_party.id}) created by character {leader_character_id} (discord {discord_id_str}) in guild {guild_id_str}.")
                await interaction.followup.send(f"Группа '{party_display_name}' (ID: `{new_party.id}`) успешно создана! Вы являетесь лидером.", ephemeral=False)
            else:
                logger_party_cmds.error(f"PartyManager.create_party returned None or invalid party object for leader {leader_character_id}, name '{name}'.")
                await interaction.followup.send("Не удалось создать группу. Возможно, вы уже состоите в группе или произошла другая ошибка.", ephemeral=True)

        except CharacterAlreadyInPartyError:
            active_char_id_log = player_account.active_character_id if player_account else 'N/A' # player_account is possibly unbound (Pyright error) - Fixed
            logger_party_cmds.warning(f"/party create: Character {discord_id_str} (active char: {active_char_id_log}) is already in a party.")
            await interaction.followup.send(f"Вы уже состоите в группе. Сначала покиньте текущую группу.", ephemeral=True)
        except Exception as e:
            logger_party_cmds.error(f"Error in /party create for user {discord_id_str}, guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send("Произошла непредвиденная ошибка при создании группы.", ephemeral=True)


    @party_group.command(name="disband", description="Распустить текущую группу (только для лидера).")
    async def cmd_party_disband(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        bot_instance: RPGBot = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            logger_party_cmds.error("GameManager not initialized for /party disband.")
            await interaction.followup.send("Ошибка: Игровые сервисы не полностью инициализированы.", ephemeral=True)
            return

        game_mngr: Optional["GameManager"] = getattr(bot_instance, 'game_manager', None)
        if not game_mngr:
            logger_party_cmds.error("GameManager not initialized for /party disband.")
            await interaction.followup.send("Ошибка: Игровые сервисы не полностью инициализированы.", ephemeral=True)
            return

        db_service: Optional["DBService"] = getattr(game_mngr, 'db_service', None)
        if not db_service: # Type "DBService | None" is not assignable to declared type "DBService" - Fixed
            logger_party_cmds.error("DBService not available for /party disband.")
            await interaction.followup.send("Ошибка: Сервис базы данных недоступен.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)
        disbanding_character_id: Optional[str] = None # Initialize
        party_id_to_disband: Optional[str] = None # Initialize

        try:
            character_manager = getattr(game_mngr, 'character_manager', None)
            party_manager = getattr(game_mngr, 'party_manager', None)

            if not character_manager or not party_manager:
                logger_party_cmds.error("CharacterManager or PartyManager not available for /party disband.")
                await interaction.followup.send("Ошибка: Основные сервисы управления персонажами или группами недоступны.", ephemeral=True)
                return

            player_account = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str) # Known attribute check for game_mngr done above
            if not player_account or not player_account.active_character_id:
                await interaction.followup.send("У вас должен быть активный персонаж, чтобы распустить группу.", ephemeral=True)
                return

            disbanding_character_id = str(player_account.active_character_id) # Ensure string

            character = await character_manager.get_character(guild_id_str, disbanding_character_id) # character_manager checked above
            if not character:
                await interaction.followup.send("Не удалось найти вашего активного персонажа.", ephemeral=True)
                return

            party_id_to_disband = character.current_party_id
            if not party_id_to_disband:
                await interaction.followup.send("Вы не состоите в группе, чтобы ее распускать.", ephemeral=True)
                return

            success = await party_manager.disband_party( # party_manager checked above
                guild_id=guild_id_str,
                party_id=str(party_id_to_disband), # Ensure string
                disbanding_character_id=disbanding_character_id
            )

            if success:
                await interaction.followup.send(f"Группа (ID: `{party_id_to_disband}`) успешно распущена.", ephemeral=False)
            else:
                await interaction.followup.send("Не удалось распустить группу. Проверьте, являетесь ли вы лидером, или попробуйте позже.", ephemeral=True)

        except NotPartyLeaderError:
            char_id_log = disbanding_character_id if disbanding_character_id else 'unknown_char' # disbanding_character_id is possibly unbound - Fixed
            party_id_log = party_id_to_disband if party_id_to_disband else 'unknown_party' # party_id_to_disband is possibly unbound - Fixed
            logger_party_cmds.warning(f"/party disband: Character {char_id_log} is not the leader of party {party_id_log}.")
            await interaction.followup.send("Только лидер группы может ее распустить.", ephemeral=True)
        except PartyNotFoundError:
            char_id_log_pnf = disbanding_character_id if disbanding_character_id else 'unknown_char' # disbanding_character_id is possibly unbound - Fixed
            party_id_log_pnf = party_id_to_disband if party_id_to_disband else 'unknown_party' # party_id_to_disband is possibly unbound - Fixed
            logger_party_cmds.warning(f"/party disband: Party {party_id_log_pnf} not found for character {char_id_log_pnf}.")
            if disbanding_character_id and game_mngr and hasattr(game_mngr, 'character_manager') and game_mngr.character_manager:
                 await game_mngr.character_manager.save_character_field(guild_id_str, disbanding_character_id, "current_party_id", None)
            await interaction.followup.send("Ваша группа не найдена (возможно, уже была распущена). Ваш статус обновлен.", ephemeral=True)
        except Exception as e:
            logger_party_cmds.error(f"Error in /party disband for user {discord_id_str}, guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send("Произошла непредвиденная ошибка при роспуске группы.", ephemeral=True)


    @party_group.command(name="join", description="Присоединиться к существующей группе.")
    @app_commands.describe(identifier="ID или точное название группы для присоединения")
    async def cmd_party_join(self, interaction: Interaction, identifier: str):
        await interaction.response.defer(ephemeral=True)

        bot_instance: RPGBot = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            logger_party_cmds.error("GameManager not initialized for /party join.")
            await interaction.followup.send("Ошибка: Игровые сервисы не полностью инициализированы.", ephemeral=True)
            return

        game_mngr: Optional["GameManager"] = getattr(bot_instance, 'game_manager', None)
        if not game_mngr:
            logger_party_cmds.error("GameManager not initialized for /party join.")
            await interaction.followup.send("Ошибка: Игровые сервисы не полностью инициализированы.", ephemeral=True)
            return

        db_service: Optional["DBService"] = getattr(game_mngr, 'db_service', None)
        loc_mngr_optional: Optional["LocationManager"] = getattr(game_mngr, 'location_manager', None) # For location name in error

        if not db_service or not loc_mngr_optional: # Type "DBService | None" is not assignable to declared type "DBService" - Fixed, Type "LocationManager | None" is not assignable to declared type "LocationManager" - Fixed
            logger_party_cmds.error("DBService or LocationManager not available for /party join.")
            await interaction.followup.send("Ошибка: Базовые сервисы игры недоступны.", ephemeral=True)
            return

        # Cast after None checks
        loc_mngr = cast("LocationManager", loc_mngr_optional)


        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)

        try:
            character_manager = getattr(game_mngr, 'character_manager', None)
            party_manager = getattr(game_mngr, 'party_manager', None)
            # location_manager already handled by loc_mngr

            if not character_manager or not party_manager or not loc_mngr : # loc_mngr is now checked
                logger_party_cmds.error("Key managers not available for /party join.")
                await interaction.followup.send("Ошибка: Основные сервисы игры недоступны.", ephemeral=True)
                return

            player_account = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str)
            if not player_account or not player_account.active_character_id:
                await interaction.followup.send("У вас должен быть активный персонаж, чтобы присоединиться к группе.", ephemeral=True)
                return

            character_id_to_join = str(player_account.active_character_id) # Ensure string
            character_to_join = await character_manager.get_character(guild_id_str, character_id_to_join)
            if not character_to_join:
                 await interaction.followup.send("Не удалось найти вашего активного персонажа.", ephemeral=True)
                 return

            if character_to_join.current_party_id:
                await interaction.followup.send(f"Вы уже состоите в группе (ID: `{character_to_join.current_party_id}`). Сначала покиньте текущую группу.", ephemeral=True)
                return

            character_current_loc_id = character_to_join.current_location_id
            if not character_current_loc_id: # "None" is not awaitable (Pyright error) - Fixed by checking None before using
                await interaction.followup.send("Ваш персонаж не находится в известной локации. Невозможно присоединиться к группе.", ephemeral=True)
                return

            target_party = await party_manager.get_party(guild_id_str, identifier)

            if not target_party:
                logger_party_cmds.info(f"/party join: Party ID '{identifier}' not found directly. Attempting name lookup in cache for guild {guild_id_str}.")
                parties_in_guild = getattr(party_manager, '_parties_cache', {}).get(guild_id_str, {}) # get is not a known attribute of "None" (Pyright error) - Fixed by using getattr
                found_parties_by_name = []
                if isinstance(parties_in_guild, dict): # Ensure it's a dict before iterating
                    for p_id, p_obj in parties_in_guild.items():
                        if hasattr(p_obj, 'name_i18n') and isinstance(p_obj.name_i18n, dict):
                            if any(name_val.lower() == identifier.lower() for name_val in p_obj.name_i18n.values()):
                                found_parties_by_name.append(p_obj)

                if len(found_parties_by_name) == 1:
                    target_party = found_parties_by_name[0]
                elif len(found_parties_by_name) > 1:
                    await interaction.followup.send(f"Найдено несколько групп с названием '{identifier}'. Пожалуйста, используйте ID группы для присоединения.", ephemeral=True)
                    return

            if not target_party:
                await interaction.followup.send(f"Группа с ID или названием '{identifier}' не найдена.", ephemeral=True)
                return

            target_party_loc_id = target_party.current_location_id
            if character_current_loc_id != target_party_loc_id: # "None" is not awaitable (Pyright error) - Fixed by checking character_current_loc_id before
                player_loc_name = str(character_current_loc_id)
                party_loc_name = str(target_party_loc_id) if target_party_loc_id else "Unknown Party Location"

                player_loc_obj = await loc_mngr.get_location_instance(guild_id_str, str(character_current_loc_id)) # Argument of type "Unknown | str | None" cannot be assigned (Pyright error) - Fixed by ensuring character_current_loc_id is str
                if player_loc_obj and hasattr(player_loc_obj, 'name_i18n') and isinstance(player_loc_obj.name_i18n, dict) and player_account.selected_language: # player_account is possibly unbound - Fixed
                    player_loc_name = player_loc_obj.name_i18n.get(player_account.selected_language, player_loc_name)

                if target_party_loc_id: # Only fetch if party has a location
                    party_loc_obj = await loc_mngr.get_location_instance(guild_id_str, str(target_party_loc_id))
                    if party_loc_obj and hasattr(party_loc_obj, 'name_i18n') and isinstance(party_loc_obj.name_i18n, dict) and player_account.selected_language:
                        party_loc_name = party_loc_obj.name_i18n.get(player_account.selected_language, party_loc_name)

                await interaction.followup.send(f"Вы должны находиться в той же локации, что и группа. Вы: '{player_loc_name}', Группа: '{party_loc_name}'.", ephemeral=True)
                return

            join_success = await party_manager.join_party(
                guild_id=guild_id_str,
                character_id=character_id_to_join,
                party_id=str(target_party.id) # Ensure ID is string
            )

            if join_success and hasattr(target_party, 'name_i18n') and isinstance(target_party.name_i18n, dict) and player_account and player_account.selected_language:
                party_display_name = target_party.name_i18n.get(player_account.selected_language, identifier)
                await interaction.followup.send(f"Вы успешно присоединились к группе '{party_display_name}' (ID: `{target_party.id}`).", ephemeral=False)
            elif join_success: # Fallback if name_i18n or selected_language is missing
                await interaction.followup.send(f"Вы успешно присоединились к группе (ID: `{target_party.id}`).", ephemeral=False)
            else:
                await interaction.followup.send("Не удалось присоединиться к группе. Возможно, она заполнена или произошла другая ошибка.", ephemeral=True)

        except CharacterAlreadyInPartyError:
            await interaction.followup.send(f"Вы уже состоите в группе. Сначала покиньте текущую группу.", ephemeral=True)
        except PartyFullError:
            await interaction.followup.send("Группа уже заполнена.", ephemeral=True)
        except PartyNotFoundError:
            await interaction.followup.send(f"Группа с ID или названием '{identifier}' не найдена.", ephemeral=True)
        except Exception as e:
            logger_party_cmds.error(f"Error in /party join for user {discord_id_str}, guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send("Произошла непредвиденная ошибка при попытке присоединиться к группе.", ephemeral=True)

    @party_group.command(name="leave", description="Покинуть текущую группу.")
    async def cmd_party_leave(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        bot_instance: RPGBot = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            logger_party_cmds.error("GameManager not initialized for /party leave.")
            await interaction.followup.send("Ошибка: Игровые сервисы не полностью инициализированы.", ephemeral=True)
            return

        game_mngr: Optional["GameManager"] = getattr(bot_instance, 'game_manager', None)
        if not game_mngr:
            logger_party_cmds.error("GameManager not initialized for /party leave.")
            await interaction.followup.send("Ошибка: Игровые сервисы не полностью инициализированы.", ephemeral=True)
            return

        db_service: Optional["DBService"] = getattr(game_mngr, 'db_service', None)
        if not db_service: # Type "DBService | None" is not assignable to declared type "DBService" - Fixed
            logger_party_cmds.error("DBService not available for /party leave.")
            await interaction.followup.send("Ошибка: Сервис базы данных недоступен.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)
        character_id_leaving: Optional[str] = None # Initialize

        try:
            character_manager = getattr(game_mngr, 'character_manager', None)
            party_manager = getattr(game_mngr, 'party_manager', None)

            if not character_manager or not party_manager:
                logger_party_cmds.error("CharacterManager or PartyManager not available for /party leave.")
                await interaction.followup.send("Ошибка: Основные сервисы управления персонажами или группами недоступны.", ephemeral=True)
                return

            player_account = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str)
            if not player_account or not player_account.active_character_id:
                await interaction.followup.send("У вас должен быть активный персонаж, чтобы покинуть группу.", ephemeral=True)
                return

            character_id_leaving = str(player_account.active_character_id) # Ensure string

            success = await party_manager.leave_party(
                guild_id=guild_id_str,
                character_id=character_id_leaving
            )

            if success:
                await interaction.followup.send("Вы успешно покинули группу.", ephemeral=False)
            else:
                await interaction.followup.send("Не удалось покинуть группу. Возможно, вы не состоите в группе или произошла другая ошибка.", ephemeral=True)

        except CharacterNotInPartyError:
            char_id_log_leave = character_id_leaving if character_id_leaving else discord_id_str # character_id_leaving is possibly unbound - Fixed
            logger_party_cmds.warning(f"/party leave: Character {char_id_log_leave} is not in a party.")
            await interaction.followup.send("Вы не состоите в какой-либо группе.", ephemeral=True)
        except PartyNotFoundError:
            char_id_log_pnf_leave = character_id_leaving if character_id_leaving else discord_id_str # character_id_leaving is possibly unbound - Fixed
            logger_party_cmds.warning(f"/party leave: Party not found for character {char_id_log_pnf_leave}. Character's party ID might be stale.")
            if character_id_leaving and game_mngr and hasattr(game_mngr, 'character_manager') and game_mngr.character_manager: # Ensure character_id_leaving is defined
                 await game_mngr.character_manager.save_character_field(guild_id_str, character_id_leaving, "current_party_id", None)
            await interaction.followup.send("Ваша группа не найдена (возможно, уже была распущена). Ваш статус обновлен.", ephemeral=True)
        except Exception as e:
            logger_party_cmds.error(f"Error in /party leave for user {discord_id_str}, guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send("Произошла непредвиденная ошибка при выходе из группы.", ephemeral=True)

    @party_group.command(name="view", description="Просмотреть информацию о группе.")
    @app_commands.describe(target="ID группы, имя группы или имя участника для просмотра информации о его группе. Оставьте пустым для вашей текущей группы.")
    async def cmd_party_view(self, interaction: Interaction, target: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        bot_instance: RPGBot = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            logger_party_cmds.error("GameManager not initialized for /party view.")
            await interaction.followup.send("Ошибка: Игровые сервисы не полностью инициализированы.", ephemeral=True)
            return

        game_mngr: Optional["GameManager"] = getattr(bot_instance, 'game_manager', None)
        if not game_mngr:
            logger_party_cmds.error("GameManager not initialized for /party view.")
            await interaction.followup.send("Ошибка: Игровые сервисы не полностью инициализированы.", ephemeral=True)
            return

        character_manager = getattr(game_mngr, 'character_manager', None)
        party_manager = getattr(game_mngr, 'party_manager', None)
        location_manager = getattr(game_mngr, 'location_manager', None)

        if not character_manager or not party_manager or not location_manager:
            logger_party_cmds.error("A required manager (Character, Party, or Location) is not available for /party view.")
            await interaction.followup.send("Ошибка: Некоторые сервисы управления игрой недоступны.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)
        target_party: Optional[PartyModel] = None
        player_account: Optional[Player] = None # Initialize

        player_account = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str)
        if not player_account or not player_account.active_character_id:
            await interaction.followup.send("У вас должен быть активный персонаж для использования команд группы.", ephemeral=True)
            return

        active_char_id = str(player_account.active_character_id) # Ensure string
        requesting_character = await character_manager.get_character(guild_id_str, active_char_id)
        if not requesting_character:
            await interaction.followup.send("Не удалось найти вашего активного персонажа.", ephemeral=True)
            return

        if target is None:
            if requesting_character.current_party_id:
                target_party = await party_manager.get_party(guild_id_str, str(requesting_character.current_party_id)) # Ensure string
            else:
                await interaction.followup.send("Вы не состоите в группе. Укажите ID группы, имя группы или имя участника, чтобы просмотреть информацию о другой группе.", ephemeral=True)
                return
        else:
            target_party = await party_manager.get_party(guild_id_str, target)

            if not target_party:
                target_character = await character_manager.get_character_by_name(guild_id_str, target)
                if target_character and target_character.current_party_id:
                    target_party = await party_manager.get_party(guild_id_str, str(target_character.current_party_id)) # Ensure string

            if not target_party:
                logger_party_cmds.info(f"/party view: Target '{target}' not found as Party ID or Character Name's party. Attempting Party Name lookup in cache for guild {guild_id_str}.")
                parties_in_guild = getattr(party_manager, '_parties_cache', {}).get(guild_id_str, {})
                found_parties_by_name = []
                if isinstance(parties_in_guild, dict):
                    for p_id, p_obj in parties_in_guild.items():
                        if hasattr(p_obj, 'name_i18n') and isinstance(p_obj.name_i18n, dict):
                            if any(name_val.lower() == target.lower() for name_val in p_obj.name_i18n.values()):
                                found_parties_by_name.append(p_obj)
                if len(found_parties_by_name) == 1:
                    target_party = found_parties_by_name[0]
                elif len(found_parties_by_name) > 1:
                    await interaction.followup.send(f"Найдено несколько групп с названием '{target}'. Пожалуйста, используйте ID группы.", ephemeral=True)
                    return

        if not target_party:
            await interaction.followup.send(f"Не удалось найти группу по указателю: '{target if target else 'ваша текущая группа'}'.", ephemeral=True)
            return

        party_lang_selected = player_account.selected_language if player_account else None # player_account is now always defined here
        guild_default_lang_rule = await game_mngr.get_rule(guild_id_str, "default_language", "en")
        party_lang = party_lang_selected or (str(guild_default_lang_rule) if guild_default_lang_rule else "en")

        party_name_i18n_dict = target_party.name_i18n if isinstance(target_party.name_i18n, dict) else {}
        party_display_name = party_name_i18n_dict.get(party_lang, party_name_i18n_dict.get("en", str(target_party.id)))


        leader_name = "Неизвестен"
        if target_party.leader_id:
            leader_char = await character_manager.get_character(guild_id_str, str(target_party.leader_id)) # Ensure string
            if leader_char and hasattr(leader_char, 'name_i18n') and isinstance(leader_char.name_i18n, dict):
                leader_name = leader_char.name_i18n.get(party_lang, leader_char.name_i18n.get("en", str(target_party.leader_id)))

        location_name = "Неизвестно"
        target_party_loc_id = target_party.current_location_id
        if target_party_loc_id: # "None" is not awaitable (Pyright error) - Fixed by checking not None
            loc_obj = await location_manager.get_location_instance(guild_id_str, str(target_party_loc_id)) # Argument of type "Unknown | str | None" cannot be assigned (Pyright error) - Fixed
            if loc_obj and hasattr(loc_obj, 'name_i18n') and isinstance(loc_obj.name_i18n, dict):
                location_name = loc_obj.name_i18n.get(party_lang, loc_obj.name_i18n.get("en", str(target_party_loc_id)))

        members_details_list = []
        party_members_models = await party_manager.get_party_members(guild_id_str, str(target_party.id)) # Ensure string
        for member_char in party_members_models:
            member_name_i18n_dict = member_char.name_i18n if isinstance(member_char.name_i18n, dict) else {}
            member_name = member_name_i18n_dict.get(party_lang, member_name_i18n_dict.get("en", str(member_char.id)))

            member_level = member_char.level if member_char.level is not None else 1 # Handle None for level
            member_class_str = member_char.character_class if member_char.character_class else "Класс не указан"
            members_details_list.append(f"- {member_name} (Уровень {member_level}, {member_class_str})")

        embed = discord.Embed(title=f"Информация о группе: {party_display_name}", color=discord.Color.blue())
        embed.add_field(name="ID Группы", value=f"`{target_party.id}`", inline=False)
        embed.add_field(name="Лидер", value=leader_name, inline=True)
        embed.add_field(name="Текущая локация", value=location_name, inline=True)

        if members_details_list:
            embed.add_field(name="Участники", value="\n".join(members_details_list), inline=False)
        else:
            embed.add_field(name="Участники", value="В группе нет участников.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    if not isinstance(bot, RPGBot): # Check type directly
        print("Error: PartyCommands setup received a bot instance that is not RPGBot.")
        return
    await bot.add_cog(PartyCog(bot))
    print("PartyCog loaded.")

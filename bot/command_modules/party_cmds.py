import discord
import traceback
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, cast, List

# Direct import for isinstance check in setup
from bot.bot_core import RPGBot
import uuid # Added
import json # Added
import logging # Added

# Database model imports
from bot.database.models import Player, Party as PartyModel # Renamed Party to PartyModel to avoid conflict
from bot.game.exceptions import CharacterAlreadyInPartyError, NotPartyLeaderError, PartyNotFoundError, PartyFullError, CharacterNotInPartyError # Corrected import path


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

        game_mngr: "GameManager" = bot_instance.game_manager
        db_service: "DBService" = game_mngr.db_service

        if not db_service:
            logger_party_cmds.error("DBService not available for /party create.")
            await interaction.followup.send("Ошибка: Сервис базы данных недоступен.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)

        try:
            if not game_mngr.character_manager or not game_mngr.party_manager:
                logger_party_cmds.error("CharacterManager or PartyManager not available for /party create.")
                await interaction.followup.send("Ошибка: Основные сервисы управления персонажами или группами недоступны.", ephemeral=True)
                return

            # Fetch Character (which is the entity that joins parties)
            # Assuming get_player_model_by_discord_id returns the active character if one exists, or we need a get_character_by_discord_id
            # For now, let's assume we need the Character ID.
            # The Player model holds active_character_id.
            player_account: Optional[Player] = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str)
            if not player_account or not player_account.active_character_id:
                logger_party_cmds.info(f"/party create: No active character found for discord_id {discord_id_str} in guild {guild_id_str}.")
                await interaction.followup.send("У вас должен быть активный персонаж для создания группы. Используйте `/character select` или `/character create`.", ephemeral=True)
                return

            leader_character_id = player_account.active_character_id

            # Prepare party name i18n
            # This part can be simplified if PartyManager handles i18n name creation based on a single provided name string
            guild_main_lang = await game_mngr.get_rule(guild_id_str, 'default_language', 'en') or "en"
            name_i18n_dict = {'en': name}
            if guild_main_lang != 'en': # Add guild's default lang if different
                name_i18n_dict[guild_main_lang] = name

            # Call PartyManager to create the party
            new_party = await game_mngr.party_manager.create_party(
                guild_id=guild_id_str,
                leader_character_id=leader_character_id,
                party_name_i18n=name_i18n_dict
            )

            if new_party:
                party_display_name = new_party.name_i18n.get(player_account.selected_language or guild_main_lang, new_party.name_i18n.get("en", new_party.id))
                logger_party_cmds.info(f"Party '{party_display_name}' (ID: {new_party.id}) created by character {leader_character_id} (discord {discord_id_str}) in guild {guild_id_str}.")
                await interaction.followup.send(f"Группа '{party_display_name}' (ID: `{new_party.id}`) успешно создана! Вы являетесь лидером.", ephemeral=False) # Non-ephemeral for success
            else:
                # create_party in PartyManager should ideally raise specific exceptions for known failure cases
                logger_party_cmds.error(f"PartyManager.create_party returned None for leader {leader_character_id}, name '{name}'.")
                await interaction.followup.send("Не удалось создать группу. Возможно, вы уже состоите в группе или произошла другая ошибка.", ephemeral=True)

        except CharacterAlreadyInPartyError: # Specific error from PartyManager
            logger_party_cmds.warning(f"/party create: Character {discord_id_str} (active char: {player_account.active_character_id if player_account else 'N/A'}) is already in a party.")
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

        game_mngr: "GameManager" = bot_instance.game_manager
        db_service: "DBService" = game_mngr.db_service

        if not db_service:
            logger_party_cmds.error("DBService not available for /party disband.")
            await interaction.followup.send("Ошибка: Сервис базы данных недоступен.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)

        try:
            if not game_mngr.character_manager or not game_mngr.party_manager:
                logger_party_cmds.error("CharacterManager or PartyManager not available for /party disband.")
                await interaction.followup.send("Ошибка: Основные сервисы управления персонажами или группами недоступны.", ephemeral=True)
                return

            player_account: Optional[Player] = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str)
            if not player_account or not player_account.active_character_id:
                await interaction.followup.send("У вас должен быть активный персонаж, чтобы распустить группу.", ephemeral=True)
                return

            disbanding_character_id = player_account.active_character_id

            # Fetch character to get current_party_id
            # This assumes CharacterManager.get_character returns the SQLAlchemy model from cache or DB
            character = await game_mngr.character_manager.get_character(guild_id_str, disbanding_character_id)
            if not character: # Should not happen if active_character_id is set
                await interaction.followup.send("Не удалось найти вашего активного персонажа.", ephemeral=True)
                return

            party_id_to_disband = character.current_party_id
            if not party_id_to_disband:
                await interaction.followup.send("Вы не состоите в группе, чтобы ее распускать.", ephemeral=True)
                return

            # Call PartyManager to disband the party
            # PartyManager's disband_party will handle fetching the party, checking leadership,
            # updating members, and deleting the party record.
            success = await game_mngr.party_manager.disband_party(
                guild_id=guild_id_str,
                party_id=party_id_to_disband,
                disbanding_character_id=disbanding_character_id
            )

            if success:
                # PartyManager.disband_party should ideally return party name or we fetch it before for message
                await interaction.followup.send(f"Группа (ID: `{party_id_to_disband}`) успешно распущена.", ephemeral=False)
            else:
                # PartyManager's disband_party should raise specific exceptions for known failure cases
                # This 'else' means an unexpected failure in PartyManager that didn't raise a specific error
                await interaction.followup.send("Не удалось распустить группу. Проверьте, являетесь ли вы лидером, или попробуйте позже.", ephemeral=True)

        except NotPartyLeaderError:
            logger_party_cmds.warning(f"/party disband: Character {disbanding_character_id} is not the leader of party {party_id_to_disband if 'party_id_to_disband' in locals() else 'unknown'}.")
            await interaction.followup.send("Только лидер группы может ее распустить.", ephemeral=True)
        except PartyNotFoundError:
            logger_party_cmds.warning(f"/party disband: Party {party_id_to_disband if 'party_id_to_disband' in locals() else 'unknown'} not found for character {disbanding_character_id}.")
            # It's possible the character's current_party_id was stale. Clear it.
            if 'disbanding_character_id' in locals() and game_mngr.character_manager: # Check if var defined
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

        game_mngr: "GameManager" = bot_instance.game_manager
        db_service: "DBService" = game_mngr.db_service
        loc_mngr: "LocationManager" = game_mngr.location_manager # For location name in error

        if not db_service or not loc_mngr:
            logger_party_cmds.error("DBService or LocationManager not available for /party join.")
            await interaction.followup.send("Ошибка: Базовые сервисы игры недоступны.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)

        try:
            if not game_mngr.character_manager or not game_mngr.party_manager or not game_mngr.location_manager:
                logger_party_cmds.error("Key managers not available for /party join.")
                await interaction.followup.send("Ошибка: Основные сервисы игры недоступны.", ephemeral=True)
                return

            player_account: Optional[Player] = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str)
            if not player_account or not player_account.active_character_id:
                await interaction.followup.send("У вас должен быть активный персонаж, чтобы присоединиться к группе.", ephemeral=True)
                return

            character_id_to_join = player_account.active_character_id
            character_to_join = await game_mngr.character_manager.get_character(guild_id_str, character_id_to_join)
            if not character_to_join: # Should not happen if active_character_id is valid
                 await interaction.followup.send("Не удалось найти вашего активного персонажа.", ephemeral=True)
                 return

            if character_to_join.current_party_id:
                await interaction.followup.send(f"Вы уже состоите в группе (ID: `{character_to_join.current_party_id}`). Сначала покиньте текущую группу.", ephemeral=True)
                return

            if not character_to_join.current_location_id:
                await interaction.followup.send("Ваш персонаж не находится в известной локации. Невозможно присоединиться к группе.", ephemeral=True)
                return

            # Resolve Target Party
            target_party: Optional[PartyModel] = await game_mngr.party_manager.get_party(guild_id_str, identifier)

            if not target_party:
                # Try to find by name - NOTE: This is a temporary cache-only name lookup.
                # A proper PartyManager.get_party_by_name(guild_id, name) would be better.
                logger_party_cmds.info(f"/party join: Party ID '{identifier}' not found directly. Attempting name lookup in cache for guild {guild_id_str}.")
                # Accessing _parties_cache directly is not ideal but done here as PartyManager lacks get_all_parties or get_by_name for now.
                parties_in_guild = game_mngr.party_manager._parties_cache.get(guild_id_str, {})
                found_parties_by_name = []
                for p_id, p_obj in parties_in_guild.items():
                    if p_obj.name_i18n and isinstance(p_obj.name_i18n, dict):
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

            # Check Party Location (Character must be in the same location as the party)
            if character_to_join.current_location_id != target_party.current_location_id:
                player_loc_name = character_to_join.current_location_id # Fallback to ID
                party_loc_name = target_party.current_location_id # Fallback to ID

                player_loc_obj = await game_mngr.location_manager.get_location_instance(guild_id_str, character_to_join.current_location_id)
                if player_loc_obj and player_loc_obj.name_i18n: player_loc_name = player_loc_obj.name_i18n.get(player_account.selected_language or "en", player_loc_name)

                party_loc_obj = await game_mngr.location_manager.get_location_instance(guild_id_str, target_party.current_location_id)
                if party_loc_obj and party_loc_obj.name_i18n: party_loc_name = party_loc_obj.name_i18n.get(player_account.selected_language or "en", party_loc_name)

                await interaction.followup.send(f"Вы должны находиться в той же локации, что и группа. Вы: '{player_loc_name}', Группа: '{party_loc_name}'.", ephemeral=True)
                return

            # Call PartyManager to join the party
            join_success = await game_mngr.party_manager.join_party(
                guild_id=guild_id_str,
                character_id=character_id_to_join,
                party_id=target_party.id
            )

            if join_success:
                party_display_name = target_party.name_i18n.get(player_account.selected_language or "en", identifier)
                await interaction.followup.send(f"Вы успешно присоединились к группе '{party_display_name}' (ID: `{target_party.id}`).", ephemeral=False)
            else:
                # join_party in PartyManager should raise specific exceptions
                await interaction.followup.send("Не удалось присоединиться к группе. Возможно, она заполнена или произошла другая ошибка.", ephemeral=True)

        except CharacterAlreadyInPartyError:
            await interaction.followup.send(f"Вы уже состоите в группе. Сначала покиньте текущую группу.", ephemeral=True)
        except PartyFullError:
            await interaction.followup.send("Группа уже заполнена.", ephemeral=True)
        except PartyNotFoundError: # Should be caught by initial checks, but good to have
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

        game_mngr: "GameManager" = bot_instance.game_manager
        db_service: "DBService" = game_mngr.db_service

        if not db_service:
            logger_party_cmds.error("DBService not available for /party leave.")
            await interaction.followup.send("Ошибка: Сервис базы данных недоступен.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)
        try:
            if not game_mngr.character_manager or not game_mngr.party_manager:
                logger_party_cmds.error("CharacterManager or PartyManager not available for /party leave.")
                await interaction.followup.send("Ошибка: Основные сервисы управления персонажами или группами недоступны.", ephemeral=True)
                return

            player_account: Optional[Player] = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str)
            if not player_account or not player_account.active_character_id:
                await interaction.followup.send("У вас должен быть активный персонаж, чтобы покинуть группу.", ephemeral=True)
                return

            character_id_leaving = player_account.active_character_id

            # Call PartyManager to handle leaving the party
            # PartyManager.leave_party will handle finding the party, updating members, leadership, or disbanding.
            success = await game_mngr.party_manager.leave_party(
                guild_id=guild_id_str,
                character_id=character_id_leaving
            )

            if success:
                await interaction.followup.send("Вы успешно покинули группу.", ephemeral=False)
            else:
                # PartyManager's leave_party should raise specific exceptions for known failure cases
                # This 'else' implies an unexpected failure in PartyManager.
                await interaction.followup.send("Не удалось покинуть группу. Возможно, вы не состоите в группе или произошла другая ошибка.", ephemeral=True)

        except CharacterNotInPartyError:
            logger_party_cmds.warning(f"/party leave: Character {character_id_leaving if 'character_id_leaving' in locals() else discord_id_str} is not in a party.")
            await interaction.followup.send("Вы не состоите в какой-либо группе.", ephemeral=True)
        except PartyNotFoundError: # Should be rare if Character.current_party_id is consistent
            logger_party_cmds.warning(f"/party leave: Party not found for character {character_id_leaving if 'character_id_leaving' in locals() else discord_id_str}. Character's party ID might be stale.")
            if 'character_id_leaving' in locals() and game_mngr.character_manager:
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

        game_mngr: "GameManager" = bot_instance.game_manager
        if not game_mngr.character_manager or not game_mngr.party_manager or not game_mngr.location_manager:
            logger_party_cmds.error("A required manager (Character, Party, or Location) is not available for /party view.")
            await interaction.followup.send("Ошибка: Некоторые сервисы управления игрой недоступны.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)
        target_party: Optional[PartyModel] = None

        player_account: Optional[Player] = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str)
        if not player_account or not player_account.active_character_id:
            await interaction.followup.send("У вас должен быть активный персонаж для использования команд группы.", ephemeral=True)
            return

        requesting_character = await game_mngr.character_manager.get_character(guild_id_str, player_account.active_character_id)
        if not requesting_character: # Should not happen if active_character_id is valid
            await interaction.followup.send("Не удалось найти вашего активного персонажа.", ephemeral=True)
            return

        if target is None: # View current character's party
            if requesting_character.current_party_id:
                target_party = await game_mngr.party_manager.get_party(guild_id_str, requesting_character.current_party_id)
            else:
                await interaction.followup.send("Вы не состоите в группе. Укажите ID группы, имя группы или имя участника, чтобы просмотреть информацию о другой группе.", ephemeral=True)
                return
        else: # Target is provided
            # 1. Try as Party ID
            target_party = await game_mngr.party_manager.get_party(guild_id_str, target)

            # 2. Try as Character Name (to find their party)
            if not target_party:
                # CharacterManager.get_character_by_name operates on cache.
                # This might need enhancement in CharacterManager for a DB lookup if not cached.
                target_character = game_mngr.character_manager.get_character_by_name(guild_id_str, target)
                if target_character and target_character.current_party_id:
                    target_party = await game_mngr.party_manager.get_party(guild_id_str, target_character.current_party_id)

            # 3. Try as Party Name (cache-only lookup for now)
            if not target_party:
                logger_party_cmds.info(f"/party view: Target '{target}' not found as Party ID or Character Name's party. Attempting Party Name lookup in cache for guild {guild_id_str}.")
                parties_in_guild = game_mngr.party_manager._parties_cache.get(guild_id_str, {}) # Accessing cache directly - needs improvement in PartyManager
                found_parties_by_name = []
                for p_id, p_obj in parties_in_guild.items():
                    if p_obj.name_i18n and isinstance(p_obj.name_i18n, dict):
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

        # Fetch details for the embed
        party_lang = player_account.selected_language or await game_mngr.get_rule(guild_id_str, "default_language", "en") or "en"
        party_display_name = target_party.name_i18n.get(party_lang, target_party.name_i18n.get("en", target_party.id)) if target_party.name_i18n else target_party.id

        leader_name = "Неизвестен"
        if target_party.leader_id:
            leader_char = await game_mngr.character_manager.get_character(guild_id_str, target_party.leader_id)
            if leader_char and leader_char.name_i18n:
                leader_name = leader_char.name_i18n.get(party_lang, leader_char.name_i18n.get("en", target_party.leader_id))

        location_name = "Неизвестно"
        if target_party.current_location_id:
            loc_obj = await game_mngr.location_manager.get_location_instance(guild_id_str, target_party.current_location_id)
            if loc_obj and loc_obj.name_i18n:
                location_name = loc_obj.name_i18n.get(party_lang, loc_obj.name_i18n.get("en", target_party.current_location_id))

        members_details_list = []
        party_members_models = await game_mngr.party_manager.get_party_members(guild_id_str, target_party.id)
        for member_char in party_members_models:
            member_name = member_char.name_i18n.get(party_lang, member_char.name_i18n.get("en", member_char.id)) if member_char.name_i18n else member_char.id
            member_class = member_char.character_class_i18n.get(party_lang, member_char.character_class_i18n.get("en", "Класс не указан")) if member_char.character_class_i18n else "Класс не указан"
            members_details_list.append(f"- {member_name} (Уровень {member_char.level or 1}, {member_class})")

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
    if not isinstance(bot, RPGBot):
        print("Error: PartyCommands setup received a bot instance that is not RPGBot.")
        return
    await bot.add_cog(PartyCog(bot))
    print("PartyCog loaded.")

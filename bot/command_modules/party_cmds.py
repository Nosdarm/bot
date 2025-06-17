import discord
import traceback
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, cast

# Direct import for isinstance check in setup
from bot.bot_core import RPGBot
import uuid # Added
import json # Added
import logging # Added

# Database model imports
from bot.database.models import Player, Party as PartyModel # Renamed Party to PartyModel to avoid conflict

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
            # Fetch Player
            player: Optional[Player] = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str)
            if not player:
                logger_party_cmds.info(f"/party create: Player not found for discord_id {discord_id_str} in guild {guild_id_str}.")
                await interaction.followup.send("Ваш профиль игрока не найден. Пожалуйста, создайте его сначала (например, используя /start).", ephemeral=True)
                return

            # Check if Player is Already in Party
            if player.current_party_id:
                logger_party_cmds.info(f"/party create: Player {player.id} (discord {discord_id_str}) is already in party {player.current_party_id}.")
                await interaction.followup.send(f"Вы уже состоите в группе (ID: `{player.current_party_id}`). Сначала покиньте текущую группу.", ephemeral=True)
                return

            if not player.current_location_id:
                logger_party_cmds.warning(f"/party create: Player {player.id} (discord {discord_id_str}) has no current_location_id.")
                await interaction.followup.send("Ваш персонаж не находится в известной локации. Невозможно создать группу.", ephemeral=True)
                return

            # Prepare Party Data
            party_id = str(uuid.uuid4())
            guild_main_lang = await game_mngr.get_rule(guild_id_str, 'default_language', 'en') or "en"

            name_i18n_dict = {'en': name}
            if guild_main_lang != 'en':
                name_i18n_dict[guild_main_lang] = name

            party_data = {
                "id": party_id,
                "guild_id": guild_id_str,
                "name_i18n": name_i18n_dict,
                "player_ids": [player.id], # Stored as JSONB, so list is fine
                "leader_id": player.id,
                "current_location_id": player.current_location_id,
                "turn_status": "active", # Or some other default, e.g., "idle", "pending_actions"
                "state_variables": {}
            }

            # Create Party Entity
            new_party: Optional[PartyModel] = await db_service.create_entity(model_class=PartyModel, entity_data=party_data)

            if not new_party:
                logger_party_cmds.error(f"Failed to create party object in DB for leader {player.id}, name '{name}'.")
                await interaction.followup.send("Не удалось создать группу в базе данных.", ephemeral=True)
                return

            # Update Player's current_party_id
            update_success = await db_service.update_player_field(
                player_id=player.id,
                field_name='current_party_id',
                value=new_party.id,
                guild_id_str=guild_id_str
            )

            if not update_success:
                logger_party_cmds.error(f"Party {new_party.id} created, but failed to update player {player.id} current_party_id. Attempting to clean up party.")
                # Attempt to delete the created party if player update fails
                await db_service.delete_entity_by_pk(PartyModel, new_party.id, guild_id=guild_id_str)
                await interaction.followup.send("Создали группу, но не удалось обновить ваш статус. Группа была удалена. Попробуйте еще раз.", ephemeral=True)
                return

            # player.current_party_id = new_party.id # Local object update (optional, as player object might not be used further)

            logger_party_cmds.info(f"Party '{name}' (ID: {new_party.id}) created by player {player.id} (discord {discord_id_str}) in guild {guild_id_str}.")
            await interaction.followup.send(f"Группа '{name}' (ID: `{new_party.id}`) успешно создана! Вы являетесь лидером.", ephemeral=False) # Non-ephemeral for success

        except Exception as e:
            logger_party_cmds.error(f"Error in /party create for user {discord_id_str}, guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send("Произошла непредвиденная ошибка при создании группы.", ephemeral=True)


    @party_group.command(name="disband", description="Disband your current party (leader only).")
    async def cmd_party_disband(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        # Assuming self.bot is already RPGBot
        bot_instance: RPGBot = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            await interaction.followup.send("Error: Core game services not initialized.", ephemeral=True); return

        game_mngr: "GameManager" = bot_instance.game_manager
        if not game_mngr.character_manager or not game_mngr.party_manager:
            await interaction.followup.send("Error: Character or Party services are not fully initialized.", ephemeral=True); return

        char_manager: "CharacterManager" = game_mngr.character_manager
        party_manager: "PartyManager" = game_mngr.party_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id
        try:
            player_char: Optional["Character"] = char_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)
            if not player_char or not player_char.id:
                await interaction.followup.send("You need a character.", ephemeral=True); return

            current_party_id = getattr(player_char, 'current_party_id', None)
            if not current_party_id:
                await interaction.followup.send("Not in a party.", ephemeral=True); return

            party_to_disband: Optional["Party"] = party_manager.get_party(guild_id_str, current_party_id) # Use Party
            if not party_to_disband:
                await char_manager.set_current_party_id(guild_id_str, player_char.id, None) # Clear inconsistent data
                await interaction.followup.send("Party info inconsistent, cleared your status.", ephemeral=True); return

            if party_to_disband.leader_id != player_char.id:
                await interaction.followup.send("Only the party leader can disband the party.", ephemeral=True); return

            context_kwargs = {"guild_id": guild_id_str, "character_manager": char_manager}
            disband_success = await party_manager.remove_party(current_party_id, guild_id_str, **context_kwargs)
            if disband_success:
                party_name_display = getattr(party_to_disband, 'name_i18n', {}).get(player_char.selected_language or 'en', current_party_id) if hasattr(party_to_disband, 'name_i18n') else getattr(party_to_disband, 'name', current_party_id)
                await interaction.followup.send(f"Party '{party_name_display}' disbanded.", ephemeral=False)
            else:
                await interaction.followup.send("Error disbanding party.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True); traceback.print_exc()


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
            player: Optional[Player] = await game_mngr.get_player_model_by_discord_id(guild_id=guild_id_str, discord_id=discord_id_str)
            if not player:
                await interaction.followup.send("Ваш профиль игрока не найден. Пожалуйста, создайте его сначала (например, используя /start).", ephemeral=True)
                return

            if player.current_party_id:
                await interaction.followup.send(f"Вы уже состоите в группе (ID: `{player.current_party_id}`). Сначала покиньте текущую группу.", ephemeral=True)
                return

            if not player.current_location_id:
                await interaction.followup.send("Ваш персонаж не находится в известной локации. Невозможно присоединиться к группе.", ephemeral=True)
                return

            # Find Target Party
            target_party: Optional[PartyModel] = None

            # Attempt 1: By ID
            try:
                # Check if identifier could be a UUID (party ID)
                uuid.UUID(identifier, version=4) # Will raise ValueError if not a valid UUID
                target_party = await db_service.get_entity_by_pk(PartyModel, pk_value=identifier, guild_id=guild_id_str)
            except ValueError:
                logger_party_cmds.debug(f"/party join: Identifier '{identifier}' is not a valid UUID. Will search by name.")
            except Exception as e: # Catch other DB errors during PK lookup
                logger_party_cmds.error(f"Error fetching party by ID '{identifier}': {e}", exc_info=True)
                # Continue to search by name

            # Attempt 2: By Name (if not found by ID)
            if not target_party:
                all_parties: List[PartyModel] = await db_service.get_entities_by_conditions(model_class=PartyModel, conditions={'guild_id': guild_id_str})

                found_parties_by_name: List[PartyModel] = []
                for p in all_parties:
                    if isinstance(p.name_i18n, dict):
                        if any(name_val.lower() == identifier.lower() for name_val in p.name_i18n.values()):
                            found_parties_by_name.append(p)

                if len(found_parties_by_name) == 1:
                    target_party = found_parties_by_name[0]
                elif len(found_parties_by_name) > 1:
                    await interaction.followup.send(f"Найдено несколько групп с названием '{identifier}'. Пожалуйста, используйте ID группы для присоединения.", ephemeral=True)
                    return

            if not target_party:
                await interaction.followup.send(f"Группа с ID или названием '{identifier}' не найдена.", ephemeral=True)
                return

            # Check Party Location
            if player.current_location_id != target_party.current_location_id:
                # Fetch location names for a more user-friendly message
                player_loc_name = "неизвестно"
                party_loc_name = "неизвестно"
                if loc_mngr:
                    player_loc_obj = await loc_mngr.get_location_instance(guild_id_str, player.current_location_id)
                    if player_loc_obj and player_loc_obj.name_i18n : player_loc_name = player_loc_obj.name_i18n.get(player.selected_language or "en", player.current_location_id)

                    party_loc_obj = await loc_mngr.get_location_instance(guild_id_str, target_party.current_location_id)
                    if party_loc_obj and party_loc_obj.name_i18n: party_loc_name = party_loc_obj.name_i18n.get(player.selected_language or "en", target_party.current_location_id)

                await interaction.followup.send(f"Вы должны находиться в той же локации, что и группа. Вы: '{player_loc_name}', Группа: '{party_loc_name}'.", ephemeral=True)
                return

            # Check Party Capacity
            max_party_size = await game_mngr.get_rule(guild_id_str, 'max_party_size', 4) # Default to 4 if rule not set

            # target_party.player_ids should be a Python list already thanks to JSONB
            player_ids_list = target_party.player_ids if target_party.player_ids is not None else []

            if len(player_ids_list) >= max_party_size:
                await interaction.followup.send("Группа уже заполнена.", ephemeral=True)
                return

            # Update Party and Player
            if player.id not in player_ids_list: # Should not happen if not already in party, but good check
                player_ids_list.append(player.id)

            party_update_success = await db_service.update_entity_by_pk(
                PartyModel,
                pk_value=target_party.id,
                updates={'player_ids': player_ids_list},
                guild_id=guild_id_str
            )

            if not party_update_success:
                logger_party_cmds.error(f"Failed to update party {target_party.id} with new member {player.id}.")
                await interaction.followup.send("Не удалось обновить состав группы. Попробуйте еще раз.", ephemeral=True)
                return

            player_update_success = await db_service.update_player_field(
                player_id=player.id,
                field_name='current_party_id',
                value=target_party.id,
                guild_id_str=guild_id_str
            )

            if not player_update_success:
                logger_party_cmds.error(f"Player {player.id} joined party {target_party.id}, but failed to update player's current_party_id. Attempting to revert party.")
                # Revert: remove player from party if player update failed
                player_ids_list.remove(player.id)
                await db_service.update_entity_by_pk(PartyModel, target_party.id, {'player_ids': player_ids_list}, guild_id=guild_id_str)
                await interaction.followup.send("Вы присоединились к группе, но не удалось обновить ваш статус. Изменения отменены. Попробуйте еще раз.", ephemeral=True)
                return

            party_display_name = target_party.name_i18n.get(player.selected_language or "en", identifier)
            await interaction.followup.send(f"Вы успешно присоединились к группе '{party_display_name}' (ID: `{target_party.id}`).", ephemeral=False)

        except Exception as e:
            logger_party_cmds.error(f"Error in /party join for user {discord_id_str}, guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send("Произошла непредвиденная ошибка при попытке присоединиться к группе.", ephemeral=True)

    @party_group.command(name="leave", description="Leave your current party.")
    async def cmd_party_leave(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        # Assuming self.bot is already RPGBot
        bot_instance: RPGBot = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            await interaction.followup.send("Error: Core game services not initialized.", ephemeral=True); return

        game_mngr: "GameManager" = bot_instance.game_manager
        if not game_mngr.character_manager or not game_mngr.party_manager or not game_mngr.location_manager:
            await interaction.followup.send("Error: Character, Party or Location services are not fully initialized.", ephemeral=True); return

        char_manager: "CharacterManager" = game_mngr.character_manager
        party_manager: "PartyManager" = game_mngr.party_manager
        loc_manager: "LocationManager" = game_mngr.location_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id
        try:
            player_char: Optional["Character"] = char_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int) # Use Character
            if not player_char or not player_char.id:
                await interaction.followup.send("You need a character.", ephemeral=True); return

            current_party_id = getattr(player_char, 'current_party_id', None)
            if not current_party_id:
                await interaction.followup.send("Not in a party.", ephemeral=True); return

            party_to_leave: Optional["Party"] = party_manager.get_party(guild_id_str, current_party_id) # Use Party
            if not party_to_leave:
                await char_manager.set_current_party_id(guild_id_str, player_char.id, None)
                await interaction.followup.send("Party info inconsistent, cleared your status.", ephemeral=True); return

            current_location_id = getattr(player_char, 'current_location_id', None)
            if not current_location_id:
                 await interaction.followup.send("Character not in a valid location.", ephemeral=True); return

            party_location_id = getattr(party_to_leave, 'current_location_id', None)
            if party_location_id is None: # Explicit None check
                 await interaction.followup.send(f"Party '{current_party_id}' is not currently at a known location.", ephemeral=True); return

            if current_location_id != party_location_id:
                player_loc_name = loc_manager.get_location_name(guild_id_str, current_location_id) or current_location_id
                party_loc_name = loc_manager.get_location_name(guild_id_str, party_location_id) or party_location_id # party_location_id is now checked not to be None
                await interaction.followup.send(f"Must be in same location to leave. You: '{player_loc_name}', Party: '{party_loc_name}'.", ephemeral=True); return

            context_kwargs = {"guild_id": guild_id_str, "character_manager": char_manager}
            leave_success = await party_manager.remove_member_from_party(current_party_id, player_char.id, guild_id_str, context_kwargs)
            if leave_success:
                await char_manager.set_current_party_id(guild_id_str, player_char.id, None) # No context needed for set_current_party_id as it's direct attribute
                party_name_display = getattr(party_to_leave, 'name_i18n', {}).get(player_char.selected_language or 'en', current_party_id) if hasattr(party_to_leave, 'name_i18n') else getattr(party_to_leave, 'name', current_party_id)
                await interaction.followup.send(f"Left '{party_name_display}'.", ephemeral=False)
            else:
                await interaction.followup.send("Error leaving party.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True); traceback.print_exc()


async def setup(bot: commands.Bot):
    if not isinstance(bot, RPGBot):
        print("Error: PartyCommands setup received a bot instance that is not RPGBot.")
        return
    await bot.add_cog(PartyCog(bot))
    print("PartyCog loaded.")

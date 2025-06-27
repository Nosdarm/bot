import discord # Ensure discord is imported
from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, List, Dict, Any
import functools # For partial
import logging
from discord.ui import View, Button # Corrected import
from discord import ButtonStyle # Corrected import
import uuid # Added for unique button IDs

# Models and DB utils for /whereami
from bot.database.models import Player, Location
from bot.database.crud_utils import get_entity_by_id, get_entity_by_attributes


if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor

logger = logging.getLogger(__name__) # Added logger for whereami

class ExplorationCog(commands.Cog, name="Exploration Commands"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    @app_commands.command(name="look", description="Осмотреть текущую локацию или конкретный объект.")
    @app_commands.describe(target="Объект или направление для осмотра (необязательно).")
    async def cmd_look(self, interaction: Interaction, target: Optional[str] = None):
        await interaction.response.defer(ephemeral=False)

        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore
        if not game_mngr:
            await interaction.followup.send("GameManager не доступен.", ephemeral=True)
            return

        char_action_proc: Optional["CharacterActionProcessor"] = game_mngr._character_action_processor # type: ignore
        if not char_action_proc:
            await interaction.followup.send("Обработчик действий персонажа не доступен.", ephemeral=True)
            return

        character_manager = getattr(game_mngr, "character_manager", None)
        if not character_manager: # Dependent manager check
            await interaction.followup.send("Менеджер персонажей не доступен.", ephemeral=True)
            return

        action_data = {"target": target} if target else {}
        
        player_char = await character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id) # Corrected access
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        current_loc_id = getattr(player_char, "current_location_id", "Unknown")
        logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Fetched player_char (ID: {player_char.id}), location_id: {current_loc_id}")


        logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Before handle_explore_action. Target: {target}, Action Data: {action_data}")
        result = await char_action_proc.handle_explore_action(
            character=player_char,
            guild_id=str(interaction.guild_id),
            action_params=action_data,
            context_channel_id=interaction.channel_id
        )
        logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - After handle_explore_action. Result: {result}")

        logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Checking result success. Result valid: {bool(result)}, Success flag: {result.get('success') if result else 'N/A'}")
        if result and result.get("success"):
            message_content = result.get("message", "You look around.")
            exits_data = result.get("data", {}).get("exits", [])
            logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Result success. Message: {message_content}, Exits data: {exits_data}")

            view = None
            if exits_data:
                logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Exits data found, creating View. Exits: {exits_data}")
                view = View(timeout=300.0)

                async def button_callback(interaction: discord.Interaction, target_loc_id: str, char_id: str, gm: "GameManager", cap: "CharacterActionProcessor"):
                    await interaction.response.defer(ephemeral=True)

                    # Ensure dependent managers are available on gm
                    if not hasattr(gm, 'character_manager') or not gm.character_manager or \
                       not hasattr(gm, 'handle_move_action') or not callable(gm.handle_move_action):
                        await interaction.followup.send("Ошибка: необходимые компоненты игры не доступны для перемещения.", ephemeral=True)
                        return

                    character_to_move = await gm.character_manager.get_character(guild_id=str(interaction.guild_id), character_id=char_id)
                    if not character_to_move:
                        await interaction.followup.send("Ошибка: не удалось найти данные вашего персонажа для перемещения.", ephemeral=True)
                        return

                    move_success = await gm.handle_move_action(
                        guild_id=str(interaction.guild_id),
                        character_id=char_id,
                        target_location_identifier=target_loc_id
                    )

                    if move_success:
                        updated_char = await gm.character_manager.get_character(guild_id=str(interaction.guild_id), character_id=char_id)
                        updated_char_current_loc_id = getattr(updated_char, "current_location_id", None)
                        if not updated_char or not updated_char_current_loc_id:
                            await interaction.message.edit(content="Вы переместились, но не удалось получить детали новой локации.", view=None)
                            await interaction.followup.send("Перемещение выполнено, но детали локации не обновлены.", ephemeral=True)
                            return

                        # Ensure cap (CharacterActionProcessor) is valid
                        if not cap or not hasattr(cap, 'handle_explore_action') or not callable(cap.handle_explore_action):
                            await interaction.message.edit(content=f"Вы прибыли в '{target_loc_id}', но не удалось осмотреться (обработчик действий недоступен).", view=None)
                            await interaction.followup.send(f"Перемещение в '{target_loc_id}' выполнено, но осмотр не удался.", ephemeral=True)
                            return

                        new_look_action_data = {}
                        new_look_result = await cap.handle_explore_action(
                            character=updated_char,
                            guild_id=str(interaction.guild_id),
                            action_params=new_look_action_data,
                            context_channel_id=interaction.channel_id
                        )

                        if new_look_result and new_look_result.get("success"):
                            new_message_content = new_look_result.get("message", "Вы прибыли в новую локацию.")
                            new_exits_data = new_look_result.get("data", {}).get("exits", [])
                            new_view = View(timeout=300.0)
                            if new_exits_data:
                                for exit_info_new in new_exits_data:
                                    btn_new = Button(
                                        label=f"Идти: {exit_info_new.get('name', 'Неизвестный выход')}",
                                        style=ButtonStyle.secondary,
                                        custom_id=f"look_move_{exit_info_new.get('target_location_id')}_{uuid.uuid4()}"
                                    )
                                    callback_new = functools.partial(button_callback,
                                                                     target_loc_id=exit_info_new.get('target_location_id'),
                                                                     char_id=char_id,
                                                                     gm=gm,
                                                                     cap=cap
                                                                    )
                                    btn_new.callback = callback_new
                                    new_view.add_item(btn_new)
                            else:
                                new_view = None

                            await interaction.message.edit(content=new_message_content, view=new_view if new_view and new_view.children else None)
                            await interaction.followup.send(f"Вы переместились в '{target_loc_id}'.", ephemeral=True)
                        else:
                            await interaction.message.edit(content=f"Вы прибыли в '{target_loc_id}', но не удалось осмотреться: {new_look_result.get('message', '') if new_look_result else 'Нет данных от осмотра.'}", view=None)
                            await interaction.followup.send(f"Перемещение в '{target_loc_id}' выполнено, но осмотр не удался.", ephemeral=True)
                    else:
                        await interaction.followup.send(f"Не удалось переместиться в '{target_loc_id}'. Возможно, путь заблокирован или что-то пошло не так.", ephemeral=True)

                for exit_info in exits_data:
                    target_location_id = exit_info.get("target_location_id")
                    exit_name = exit_info.get("name", "Неизвестный выход")
                    if not target_location_id:
                        continue

                    button = Button(
                        label=f"Идти: {exit_name}",
                        style=ButtonStyle.secondary,
                        custom_id=f"look_move_{target_location_id}_{uuid.uuid4()}" # Unique ID per button
                    )

                    if not player_char:
                         await interaction.followup.send("Ошибка: информация о персонаже потеряна перед созданием кнопок.", ephemeral=True)
                         return

                    callback_with_args = functools.partial(button_callback,
                                                           target_loc_id=target_location_id,
                                                           char_id=player_char.id,
                                                           gm=game_mngr,
                                                           cap=char_action_proc)
                    button.callback = callback_with_args
                    view.add_item(button)

            if view is not None and isinstance(view, discord.ui.View) and view.children:
                logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Sending success message. View attached: {bool(view and view.children)}")
                await interaction.followup.send(message_content, view=view, ephemeral=False)
            else:
                logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Sending success message. View attached: {bool(view and view.children)}")
                await interaction.followup.send(message_content, ephemeral=False)
        else:
            error_message = result.get("message", "You can't seem to see anything clearly right now.") if result else "An unexpected error occurred while looking around."
            logging.error(f"ExplorationCog.cmd_look: Error condition - User: {interaction.user.id}, Guild: {interaction.guild_id}, Channel: {interaction.channel_id}. Error message: '{error_message}'. Result from handle_explore_action: {result}", exc_info=True)
            await interaction.followup.send(error_message, ephemeral=True)

    @app_commands.command(name="move", description="Move to a connected location.")
    @app_commands.describe(target="The name or static ID of the location to move to.")
    @app_commands.guild_only() # Explicitly guild_only
    async def cmd_move(self, interaction: Interaction, target: str):
        await interaction.response.defer(ephemeral=True)

        guild_id_str = str(interaction.guild_id) # guild_id is guaranteed by @app_commands.guild_only()
        discord_id_str = str(interaction.user.id)

        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore
        if not game_mngr:
            logger.error(f"GameManager not available for /move command by {discord_id_str} in guild {guild_id_str}")
            await interaction.followup.send("GameManager is not available. Please try again later.", ephemeral=True)
            return

        character_manager = getattr(game_mngr, "character_manager", None)
        location_manager = getattr(game_mngr, "location_manager", None)

        if not character_manager or not location_manager:
            logger.error(f"CharacterManager or LocationManager not available for /move command by {discord_id_str} in guild {guild_id_str}")
            await interaction.followup.send("Required game services are not available. Please try again later.", ephemeral=True)
            return

        try:
            player_account: Optional[Player] = None
            if hasattr(game_mngr, "get_player_model_by_discord_id") and callable(game_mngr.get_player_model_by_discord_id):
                player_account = await game_mngr.get_player_model_by_discord_id(
                    guild_id=guild_id_str,
                    discord_id=discord_id_str
                )

            if not player_account:
                await interaction.followup.send("You need to have a player profile to move. Use `/start` to create one.", ephemeral=True)
                return

            active_character_id = getattr(player_account, "active_character_id", None)
            if not active_character_id:
                await interaction.followup.send("You do not have an active character selected. Use `/character select` or `/character create`.", ephemeral=True)
                return

            success = False
            if hasattr(game_mngr, "handle_move_action") and callable(game_mngr.handle_move_action):
                success = await game_mngr.handle_move_action(
                    guild_id=guild_id_str,
                    character_id=active_character_id,
                    target_location_identifier=target
                )

            if success:
                updated_character = await character_manager.get_character(guild_id_str, active_character_id)
                updated_char_current_loc_id = getattr(updated_character, "current_location_id", None)

                if not updated_character or not updated_char_current_loc_id:
                    logging.error(f"Move successful for character {active_character_id} but failed to refetch updated character or location ID.")
                    await interaction.followup.send("Movement processed, but could not confirm new location details.", ephemeral=True)
                    return

                new_location = await location_manager.get_location_instance(guild_id_str, updated_char_current_loc_id)

                if new_location:
                    from bot.utils import i18n_utils

                    player_lang_val = getattr(player_account, "selected_language", None)
                    default_lang_val = "en"
                    if hasattr(game_mngr, "get_rule") and callable(game_mngr.get_rule):
                        default_lang_val = await game_mngr.get_rule(guild_id_str, "default_language", "en") or "en"

                    player_lang = player_lang_val or default_lang_val

                    loc_name = i18n_utils.get_entity_localized_text(new_location, 'name_i18n', player_lang)
                    if not loc_name: # Ensure loc_name is a string
                        loc_name = getattr(new_location, "static_id", None) or getattr(new_location, "id", "Unknown Location")


                    await interaction.followup.send(f"You have moved to '{loc_name}'.", ephemeral=False)
                else:
                    logging.error(f"Move successful for character {active_character_id} to {updated_char_current_loc_id}, but new location object not found.")
                    await interaction.followup.send("Movement processed, but could not retrieve details of the new location.", ephemeral=True)
            else:
                await interaction.followup.send(f"Could not move to '{target}'. It might be an invalid destination or not connected.", ephemeral=True)

        except Exception as e:
            logging.error(f"Unexpected error in /move command for user {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send("An unexpected error occurred while trying to move.", ephemeral=True)

    @app_commands.command(name="check", description="Проверить что-либо, используя навык (например, предмет, окружение).")
    @app_commands.describe(skill_name="Навык для использования (например, внимательность, знание_магии).", target="Что или кого вы проверяете.")
    async def cmd_check(self, interaction: Interaction, skill_name: str, target: Optional[str] = None):
        await interaction.response.defer(ephemeral=False)

        game_mngr: Optional["GameManager"] = getattr(self.bot, "game_manager", None)
        if not game_mngr:
            await interaction.followup.send("GameManager не доступен.", ephemeral=True)
            return

        char_action_proc: Optional["CharacterActionProcessor"] = getattr(game_mngr, "_character_action_processor", None)
        if not char_action_proc or not callable(getattr(char_action_proc, "process_action", None)): # Added callable check
            await interaction.followup.send("Обработчик действий персонажа не доступен.", ephemeral=True)
            return

        character_manager = getattr(game_mngr, "character_manager", None)
        if not character_manager or not callable(getattr(character_manager, "get_character_by_discord_id", None)): # Added callable check
            await interaction.followup.send("Менеджер персонажей не доступен.", ephemeral=True)
            return

        player_char_obj = await character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id) # Renamed to avoid conflict
        if not player_char_obj:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        player_char_id = getattr(player_char_obj, "id", None)
        if not player_char_id:
            await interaction.followup.send("Не удалось получить ID вашего персонажа.", ephemeral=True)
            return


        action_data = {"skill_name": skill_name, "target": target if target else "окружение"}
        
        # Ensure all context managers are valid before passing
        context_game_mngr = game_mngr
        context_char_mngr = getattr(context_game_mngr, "character_manager", None)
        context_rule_engine = getattr(context_game_mngr, "rule_engine", None)
        context_openai_service = getattr(context_game_mngr, "openai_service", None)

        if not all([context_char_mngr, context_rule_engine]): # openai_service can be optional
             await interaction.followup.send("Некоторые компоненты игры не инициализированы для выполнения действия.", ephemeral=True)
             return

        result = await char_action_proc.process_action(
            character_id=player_char_id, # Use fetched character ID
            action_type="skill_check",
            action_data=action_data,
            context={
                'guild_id': str(interaction.guild_id),
                'author_id': str(interaction.user.id),
                'channel_id': interaction.channel_id,
                'game_manager': context_game_mngr,
                'character_manager': context_char_mngr,
                'rule_engine': context_rule_engine,
                'openai_service': context_openai_service, # Can be None
                'send_to_command_channel': interaction.followup.send
            }
        )
        # Assuming result handling is done by process_action or its callees via send_to_command_channel

    @app_commands.command(name="whereami", description="Shows information about your current location.")
    async def cmd_whereami(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        discord_id = str(interaction.user.id)

        game_mngr: Optional["GameManager"] = getattr(self.bot, "game_manager", None)
        if not game_mngr:
            logger.error(f"/whereami: GameManager not available for user {discord_id} in guild {guild_id}.")
            await interaction.followup.send("The game manager is not available. Please try again later.", ephemeral=True)
            return

        db_service = getattr(game_mngr, "db_service", None)
        if not db_service or not callable(getattr(db_service, "get_session", None)):
            logger.error(f"/whereami: DBService not available or get_session is not callable for user {discord_id} in guild {guild_id}.")
            await interaction.followup.send("The database service is not available. Please try again later.", ephemeral=True)
            return

        try:
            player: Optional[Player] = None
            location: Optional[Location] = None
            async with db_service.get_session() as session: # Ensure session is AsyncSession
                if not isinstance(session, discord.ext.commands.Context): # Crude check, better to use isinstance with actual AsyncSession if imported
                    player = await get_entity_by_attributes(session, Player, {"discord_id": discord_id, "guild_id": guild_id}) # Added guild_id
                else:
                    logger.error("/whereami: DB session is not of expected type AsyncSession.")
                    raise Exception("Invalid DB session type")


                if not player:
                    logger.info(f"/whereami: Player not found for discord_id {discord_id} in guild {guild_id}.")
                    await interaction.followup.send("Player not found. Have you registered or started your character?", ephemeral=True)
                    return

                player_current_loc_id = getattr(player, "current_location_id", None)
                if not player_current_loc_id:
                    logger.info(f"/whereami: Player {getattr(player, 'id', 'UnknownID')} has no current_location_id in guild {guild_id}.")
                    await interaction.followup.send("Your current location is unknown. You might be adrift in the void!", ephemeral=True)
                    return

                if not isinstance(session, discord.ext.commands.Context): # Crude check
                     location = await get_entity_by_id(session, Location, player_current_loc_id) # Removed guild_id, Location PK is just id
                else:
                    logger.error("/whereami: DB session is not of expected type AsyncSession for location fetch.")
                    raise Exception("Invalid DB session type for location fetch")


                if not location:
                    logger.warning(f"/whereami: Location data not found for location_id {player_current_loc_id} (Player {getattr(player, 'id', 'UnknownID')}, guild {guild_id}).")
                    await interaction.followup.send(f"Your current location (ID: {player_current_loc_id}) data could not be found. This is unusual.", ephemeral=True)
                    return

            player_lang_val = getattr(player, "selected_language", None)
            default_lang_val = "en"
            if hasattr(game_mngr, "get_rule") and callable(game_mngr.get_rule):
                 default_lang_val = await game_mngr.get_rule(guild_id, 'default_language', 'en') or 'en'
            player_lang = player_lang_val or default_lang_val


            loc_name_i18n = getattr(location, "name_i18n", {})
            loc_desc_i18n = getattr(location, "descriptions_i18n", {})
            loc_name = loc_name_i18n.get(player_lang, loc_name_i18n.get("en", "Unknown Location")) if isinstance(loc_name_i18n, dict) else "Unknown Location"
            loc_desc = loc_desc_i18n.get(player_lang, loc_desc_i18n.get("en", "No description available.")) if isinstance(loc_desc_i18n, dict) else "No description available."


            embed = discord.Embed(title=f"📍 You are at: {loc_name}", color=discord.Color.dark_green())
            embed.description = loc_desc
            embed.add_field(name="Location ID", value=f"`{getattr(location, 'id', 'N/A')}`", inline=True)

            location_coordinates = getattr(location, "coordinates", None)
            if location_coordinates:
                 embed.add_field(name="Coordinates", value=f"`{location_coordinates}`", inline=True)

            location_exits = getattr(location, "exits", None)
            if location_exits and isinstance(location_exits, dict) and location_exits:
                exit_str_list = [] # Renamed variable
                for direction, exit_details in location_exits.items():
                    if isinstance(exit_details, dict):
                        exit_name_i18n = exit_details.get("name_i18n", {})
                        exit_name = exit_name_i18n.get(player_lang, exit_name_i18n.get("en", direction.capitalize())) if isinstance(exit_name_i18n, dict) else direction.capitalize()
                        exit_str_list.append(f"**{direction.capitalize()}**: {exit_name}")
                    else:
                        exit_str_list.append(f"**{direction.capitalize()}**: Leads to an unknown area")
                if exit_str_list:
                    embed.add_field(name="Exits", value="\n".join(exit_str_list), inline=False)
                else:
                    embed.add_field(name="Exits", value="None apparent.", inline=False)
            else:
                embed.add_field(name="Exits", value="None apparent.", inline=False)

            logger.info(f"/whereami: User {discord_id} in guild {guild_id} is at location {getattr(location, 'id', 'N/A')} ('{loc_name}').")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in /whereami for user {discord_id} in guild {guild_id}: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while trying to determine your location.", ephemeral=True)


async def setup(bot: "RPGBot"): # Added RPGBot type hint
    await bot.add_cog(ExplorationCog(bot))
    print("ExplorationCog loaded.")

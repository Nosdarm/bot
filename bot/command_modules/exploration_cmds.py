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

        if not game_mngr.character_manager: # Dependent manager check
            await interaction.followup.send("Менеджер персонажей не доступен.", ephemeral=True)
            return

        action_data = {"target": target} if target else {}
        
        player_char = await game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return
        # Ensure player_char is not None before accessing attributes for logging
        # This check is technically redundant if the above 'if not player_char: return' is hit,
        # but good for robustness if logic changes.
        if player_char:
            logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Fetched player_char (ID: {player_char.id}), location_id: {player_char.current_location_id}") # Assuming current_location_id on Character model
        else: # Should not be reached if the above guard works
            logging.error(f"ExplorationCog.cmd_look: User {interaction.user.id} - player_char is None after get_character_by_discord_id, though it should have returned early.")


        logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Before handle_explore_action. Target: {target}, Action Data: {action_data}")
        # The action_data dictionary ({'target': target} or {}) is suitable for action_params
        result = await char_action_proc.handle_explore_action(
            character=player_char,
            guild_id=str(interaction.guild_id),
            action_params=action_data, # action_data already contains {'target': target} or is empty
            context_channel_id=interaction.channel_id
        )
        logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - After handle_explore_action. Result: {result}")

        logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Checking result success. Result valid: {bool(result)}, Success flag: {result.get('success') if result else 'N/A'}")
        # Send the message from the result
        if result and result.get("success"):
            message_content = result.get("message", "You look around.")
            exits_data = result.get("data", {}).get("exits", [])
            logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Result success. Message: {message_content}, Exits data: {exits_data}")

            view = None
            if exits_data:
                logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Exits data found, creating View. Exits: {exits_data}")
                view = View(timeout=300.0) # Increased timeout

                async def button_callback(interaction: discord.Interaction, target_loc_id: str, char_id: str, gm: "GameManager", cap: "CharacterActionProcessor"):
                    await interaction.response.defer(ephemeral=True) # Acknowledge button press, visible only to user

                    move_action_data = {"destination": target_loc_id, "is_interaction_button": True}

                    # Prepare context similar to how cmd_move does, but simplified for button interaction
                    # Note: Accessing managers directly from 'gm' (GameManager)
                    # Corrected: Use a method designed for player movement, not process_tick.
                    # Assuming CharacterActionProcessor has a method like `handle_move_action`
                    # or that GameManager's handle_move_action can be used directly if appropriate context is built.
                    # For now, let's assume a direct call to game_manager's move handler is more suitable
                    # as it encapsulates the logic for player-initiated moves.

                    # Fetch the character object again to ensure we have the latest state before attempting a move.
                    # The char_id passed to the callback is the ID of the character who initiated the /look command.
                    character_to_move = gm.character_manager.get_character(guild_id=str(interaction.guild_id), character_id=char_id)
                    if not character_to_move:
                        await interaction.followup.send("Ошибка: не удалось найти данные вашего персонажа для перемещения.", ephemeral=True)
                        return

                    # Call GameManager's handle_move_action for player-initiated move
                    move_success = await gm.handle_move_action(
                        guild_id=str(interaction.guild_id),
                        character_id=char_id, # Use the character_id passed to the callback
                        target_location_identifier=target_loc_id # The ID of the location to move to
                    )

                    if move_success:
                        # Successfully moved. Now fetch the new location's description.
                        updated_char = gm.character_manager.get_character(guild_id=str(interaction.guild_id), character_id=char_id)
                        if not updated_char or not updated_char.current_location_id:
                            await interaction.message.edit(content="Вы переместились, но не удалось получить детали новой локации.", view=None)
                            await interaction.followup.send("Перемещение выполнено, но детали локации не обновлены.", ephemeral=True)
                            return

                        # Perform a new "look" action for the new location
                        new_look_action_data = {} # Look at the new location generally
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
                                        custom_id=f"look_move_{exit_info_new.get('target_location_id')}_{uuid.uuid4()}" # Ensure unique custom_id
                                    )
                                    # Re-create partial for the new buttons
                                    callback_new = functools.partial(button_callback,
                                                                     target_loc_id=exit_info_new.get('target_location_id'),
                                                                     char_id=char_id,
                                                                     gm=gm, # Pass gm (GameManager)
                                                                     cap=cap  # Pass cap (CharacterActionProcessor)
                                                                    )
                                    btn_new.callback = callback_new
                                    new_view.add_item(btn_new)
                            else:
                                new_view = None

                            await interaction.message.edit(content=new_message_content, view=new_view if new_view and new_view.children else None)
                            await interaction.followup.send(f"Вы переместились в '{target_loc_id}'.", ephemeral=True)
                        else: # Failed to get new look description
                            await interaction.message.edit(content=f"Вы прибыли в '{target_loc_id}', но не удалось осмотреться: {new_look_result.get('message', '') if new_look_result else 'Нет данных от осмотра.'}", view=None)
                            await interaction.followup.send(f"Перемещение в '{target_loc_id}' выполнено, но осмотр не удался.", ephemeral=True)
                    else: # Move failed
                        # Get reason for failure from GameManager or default message
                        # For now, a generic failure message for the button interaction.
                        # The handle_move_action in GameManager should ideally log details or return them.
                        await interaction.followup.send(f"Не удалось переместиться в '{target_loc_id}'. Возможно, путь заблокирован или что-то пошло не так.", ephemeral=True)

                for exit_info in exits_data:
                    target_location_id = exit_info.get("target_location_id")
                    exit_name = exit_info.get("name", "Неизвестный выход")
                    if not target_location_id:
                        continue

                    button = Button(
                        label=f"Идти: {exit_name}",
                        style=ButtonStyle.secondary,
                        # custom_id is good for persistent views, but direct callback is fine too
                        custom_id=f"look_move_{target_location_id}"
                    )

                    # Use functools.partial to pass additional arguments to the callback
                    # Need player_char.id for the callback
                    if not player_char: # Should not happen due to earlier checks, but as a safeguard
                         await interaction.followup.send("Ошибка: информация о персонаже потеряна перед созданием кнопок.", ephemeral=True)
                         return

                    callback_with_args = functools.partial(button_callback,
                                                           target_loc_id=target_location_id,
                                                           char_id=player_char.id, # Pass character ID
                                                           gm=game_mngr,
                                                           cap=char_action_proc)
                    button.callback = callback_with_args
                    view.add_item(button)

            if view is not None and isinstance(view, discord.ui.View) and view.children:
                logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Sending success message. View attached: {bool(view and view.children)}")
                await interaction.followup.send(message_content, view=view, ephemeral=False)
            else:
                logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Sending success message. View attached: {bool(view and view.children)}") # view will be None or have no children
                await interaction.followup.send(message_content, ephemeral=False)
        else:
            error_message = result.get("message", "You can't seem to see anything clearly right now.") if result else "An unexpected error occurred while looking around."
            logging.error(f"ExplorationCog.cmd_look: Error condition - User: {interaction.user.id}, Guild: {interaction.guild_id}, Channel: {interaction.channel_id}. Error message: '{error_message}'. Result from handle_explore_action: {result}", exc_info=True)
            await interaction.followup.send(error_message, ephemeral=True)

    @app_commands.command(name="move", description="Move to a connected location.") # English description
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

        if not game_mngr.character_manager or not game_mngr.location_manager:
            logger.error(f"CharacterManager or LocationManager not available for /move command by {discord_id_str} in guild {guild_id_str}")
            await interaction.followup.send("Required game services are not available. Please try again later.", ephemeral=True)
            return

        try:
            # Fetch Player to get active_character_id
            player_account: Optional[Player] = await game_mngr.get_player_model_by_discord_id(
                guild_id=guild_id_str,
                discord_id=discord_id_str
            )

            if not player_account:
                await interaction.followup.send("You need to have a player profile to move. Use `/start` to create one.", ephemeral=True)
                return

            if not player_account.active_character_id:
                await interaction.followup.send("You do not have an active character selected. Use `/character select` or `/character create`.", ephemeral=True)
                return

            active_character_id = player_account.active_character_id

            # Call GameManager's handle_move_action with character_id
            success = await game_mngr.handle_move_action(
                guild_id=guild_id_str,
                character_id=active_character_id, # Use character_id
                target_location_identifier=target
            )

            if success:
                # Re-fetch character and then their location for confirmation message
                # CharacterManager's get_character method should return the updated character from cache or DB
                updated_character = await game_mngr.character_manager.get_character(guild_id_str, active_character_id)

                if not updated_character or not updated_character.current_location_id:
                    logging.error(f"Move successful for character {active_character_id} but failed to refetch updated character or location ID.")
                    await interaction.followup.send("Movement processed, but could not confirm new location details.", ephemeral=True)
                    return

                new_location = await game_mngr.location_manager.get_location_instance(guild_id_str, updated_character.current_location_id)

                if new_location:
                    from bot.utils import i18n_utils

                    player_lang = player_account.selected_language or await game_mngr.get_rule(guild_id_str, "default_language", "en") or "en"
                    loc_name = i18n_utils.get_entity_localized_text(new_location, 'name_i18n', player_lang)
                    if not loc_name:
                        loc_name = new_location.static_id or new_location.id

                    await interaction.followup.send(f"You have moved to '{loc_name}'.", ephemeral=False)
                else:
                    logging.error(f"Move successful for character {active_character_id} to {updated_character.current_location_id}, but new location object not found.")
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

        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore
        if not game_mngr:
            await interaction.followup.send("GameManager не доступен.", ephemeral=True)
            return

        char_action_proc: Optional["CharacterActionProcessor"] = game_mngr._character_action_processor # type: ignore
        if not char_action_proc:
            await interaction.followup.send("Обработчик действий персонажа не доступен.", ephemeral=True)
            return

        if not game_mngr.character_manager: # Dependent manager check
            await interaction.followup.send("Менеджер персонажей не доступен.", ephemeral=True)
            return

        player_char = game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        action_data = {"skill_name": skill_name, "target": target if target else "окружение"}
        
        result = await char_action_proc.process_action(
            character_id=player_char.id,
            action_type="skill_check",
            action_data=action_data,
            context={
                'guild_id': str(interaction.guild_id),
                'author_id': str(interaction.user.id),
                'channel_id': interaction.channel_id,
                'game_manager': game_mngr,
                'character_manager': game_mngr.character_manager,
                'rule_engine': game_mngr.rule_engine,
                'openai_service': game_mngr.openai_service,
                'send_to_command_channel': interaction.followup.send
            }
        )

    @app_commands.command(name="whereami", description="Shows information about your current location.")
    async def cmd_whereami(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        discord_id = str(interaction.user.id)

        if not self.bot.game_manager:
            logger.error(f"/whereami: GameManager not available for user {discord_id} in guild {guild_id}.")
            await interaction.followup.send("The game manager is not available. Please try again later.", ephemeral=True)
            return

        game_mngr: "GameManager" = self.bot.game_manager
        if not game_mngr.db_service:
            logger.error(f"/whereami: DBService not available for user {discord_id} in guild {guild_id}.")
            await interaction.followup.send("The database service is not available. Please try again later.", ephemeral=True)
            return

        try:
            async with game_mngr.db_service.get_session() as session:
                player = await get_entity_by_attributes(session, Player, {"discord_id": discord_id}, guild_id)

                if not player:
                    logger.info(f"/whereami: Player not found for discord_id {discord_id} in guild {guild_id}.")
                    await interaction.followup.send("Player not found. Have you registered or started your character?", ephemeral=True)
                    return

                if not player.current_location_id:
                    logger.info(f"/whereami: Player {player.id} has no current_location_id in guild {guild_id}.")
                    await interaction.followup.send("Your current location is unknown. You might be adrift in the void!", ephemeral=True)
                    return

                location = await get_entity_by_id(session, Location, player.current_location_id)

                if not location:
                    logger.warning(f"/whereami: Location data not found for location_id {player.current_location_id} (Player {player.id}, guild {guild_id}).")
                    await interaction.followup.send(f"Your current location (ID: {player.current_location_id}) data could not be found. This is unusual.", ephemeral=True)
                    return

            # Determine language for localization
            # Using game_manager.get_rule which is async
            player_lang = player.selected_language or await game_mngr.get_rule(guild_id, 'default_language', 'en')

            loc_name = location.name_i18n.get(player_lang, location.name_i18n.get("en", "Unknown Location"))
            loc_desc = location.descriptions_i18n.get(player_lang, location.descriptions_i18n.get("en", "No description available."))

            embed = discord.Embed(title=f"📍 You are at: {loc_name}", color=discord.Color.dark_green())
            embed.description = loc_desc
            embed.add_field(name="Location ID", value=f"`{location.id}`", inline=True)
            if location.coordinates:
                 embed.add_field(name="Coordinates", value=f"`{location.coordinates}`", inline=True)

            # Add exits if available in location.exits (assuming exits is a dict like {"north": "loc_id_2"})
            if location.exits and isinstance(location.exits, dict) and location.exits:
                exit_str = []
                for direction, exit_details in location.exits.items():
                    # Assuming exit_details might be a string (loc_id) or a dict {"id": "loc_id", "name_i18n": {...}}
                    if isinstance(exit_details, dict) and "name_i18n" in exit_details:
                        exit_name = exit_details["name_i18n"].get(player_lang, exit_details["name_i18n"].get("en", direction.capitalize()))
                        exit_str.append(f"**{direction.capitalize()}**: {exit_name}")
                    else: # Fallback if structure is different or just an ID
                        exit_str.append(f"**{direction.capitalize()}**: Leads to an unknown area")
                if exit_str:
                    embed.add_field(name="Exits", value="\n".join(exit_str), inline=False)
                else:
                    embed.add_field(name="Exits", value="None apparent.", inline=False)
            else:
                embed.add_field(name="Exits", value="None apparent.", inline=False)

            logger.info(f"/whereami: User {discord_id} in guild {guild_id} is at location {location.id} ('{loc_name}').")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in /whereami for user {discord_id} in guild {guild_id}: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while trying to determine your location.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ExplorationCog(bot)) # type: ignore
    print("ExplorationCog loaded.")

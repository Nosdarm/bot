import discord # Ensure discord is imported
from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, List, Dict, Any
import functools # For partial
import logging
from discord.ui import View, Button # Corrected import
from discord import ButtonStyle # Corrected import

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor

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
        
        player_char = game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return
        else: logging.debug(f"ExplorationCog.cmd_look: User {interaction.user.id} - Fetched player_char (ID: {player_char.id}), location_id: {player_char.location_id}")

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
                    move_context = {
                        'guild_id': str(interaction.guild_id),
                        'author_id': str(interaction.user.id), # This is the user who clicked the button
                        'channel_id': interaction.channel_id, # Original channel
                        'game_manager': gm,
                        'character_manager': gm.character_manager,
                        'location_manager': gm.location_manager,
                        'rule_engine': gm.rule_engine,
                        'time_manager': gm.time_manager,
                        'openai_service': gm.openai_service,
                        # 'send_to_command_channel': interaction.followup.send # For ephemeral button responses
                    }

                    move_result = await cap.process_tick(char_id=char_id, game_time_delta=1.0, guild_id=str(interaction.guild_id))

                    response_message = "Вы не смогли переместиться." # Default if no message in result
                    if move_result and move_result.get("message"):
                        response_message = move_result.get("message")

                    # Check if the original /look message needs updating (e.g. if move was successful)
                    if move_result and move_result.get("success"):
                        # Attempt to fetch new location description
                        # This requires the character object to be updated or re-fetched
                        updated_char = gm.character_manager.get_character(guild_id=str(interaction.guild_id), character_id=char_id)
                        if updated_char:
                            new_look_action_data = {} # Look at the new location
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
                                            custom_id=f"look_move_{exit_info_new.get('target_location_id')}"
                                        )
                                        # Need to re-bind callback for new buttons
                                        # This recursive-like structure for callbacks can get complex.
                                        # For simplicity in this step, the new buttons won't auto-update the message again upon click.
                                        # A more robust solution might involve a stateful View class.
                                        # For now, new buttons will just attempt a move and send ephemeral feedback.

                                        # Re-create partial for the new buttons
                                        # Important: Need player_char.id for the new callback as well.
                                        # It's better to pass player_char.id to the initial callback.
                                        callback_new = functools.partial(button_callback,
                                                                         target_loc_id=exit_info_new.get('target_location_id'),
                                                                         char_id=char_id, # Pass original character ID
                                                                         gm=game_mngr,
                                                                         cap=char_action_proc)
                                        btn_new.callback = callback_new
                                        new_view.add_item(btn_new)
                                else: # no exits from new location
                                     new_view = None # Pass None if no new exits

                                await interaction.message.edit(content=new_message_content, view=new_view if new_view and new_view.children else None)
                                await interaction.followup.send(f"Вы переместились. {response_message}", ephemeral=True)
                                return # Exit after successful move and message edit
                            else: # Failed to get new look description
                                await interaction.message.edit(content=f"Вы прибыли, но не удалось осмотреться: {new_look_result.get('message', '')}", view=None) # Clear buttons
                                await interaction.followup.send(response_message, ephemeral=True) # Send move feedback
                                return

                        else: # Failed to get updated character
                            await interaction.message.edit(content="Вы прибыли, но не удалось обновить информацию о персонаже.", view=None)
                            await interaction.followup.send(response_message, ephemeral=True)
                            return
                    else: # Move failed
                        await interaction.followup.send(f"Не удалось переместиться: {response_message}", ephemeral=True)

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

    @app_commands.command(name="move", description="Переместиться в другую локацию.")
    @app_commands.describe(destination="Название выхода или ID локации назначения.")
    async def cmd_move(self, interaction: Interaction, destination: str):
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

        action_data = {"destination": destination}
        result = await char_action_proc.process_action(
            character_id=player_char.id,
            action_type="move",
            action_data=action_data,
            context={
                'guild_id': str(interaction.guild_id),
                'author_id': str(interaction.user.id),
                'channel_id': interaction.channel_id,
                'game_manager': game_mngr,
                'character_manager': game_mngr.character_manager,
                'location_manager': game_mngr.location_manager,
                'rule_engine': game_mngr.rule_engine,
                'time_manager': game_mngr.time_manager,
                'openai_service': game_mngr.openai_service,
                'send_to_command_channel': interaction.followup.send
            }
        )

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

async def setup(bot: commands.Bot):
    await bot.add_cog(ExplorationCog(bot)) # type: ignore
    print("ExplorationCog loaded.")

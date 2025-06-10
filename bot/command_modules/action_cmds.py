from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, TYPE_CHECKING
import asyncio
if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.party_processors.party_action_processor import PartyActionProcessor
import asyncio # Should be already here from previous step
import logging # Added for logging

class ActionModuleCog(commands.Cog, name="Action Commands Module"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    @app_commands.command(name="interact", description="Взаимодействовать с объектом или NPC.")
    @app_commands.describe(target_id="ID объекта или NPC для взаимодействия.", action_type="Тип взаимодействия (если необходимо).")
    async def cmd_interact(self, interaction: Interaction, target_id: str, action_type: Optional[str] = None):
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

        action_data = {"target_id": target_id, "interaction_type": action_type}
        result = await char_action_proc.process_action(
            character_id=player_char.id,
            action_type="interact",
            action_data=action_data,
            context={
                'guild_id': str(interaction.guild_id), 'author_id': str(interaction.user.id),
                'channel_id': interaction.channel_id, 'game_manager': game_mngr,
                'character_manager': game_mngr.character_manager, 'location_manager': game_mngr.location_manager,
                'item_manager': game_mngr.item_manager, 'npc_manager': game_mngr.npc_manager,
                'event_manager': game_mngr.event_manager, 'rule_engine': game_mngr.rule_engine,
                'openai_service': game_mngr.openai_service,
                'send_to_command_channel': interaction.followup.send
            }
        )

    @app_commands.command(name="fight", description="Атаковать цель (NPC или существо).")
    @app_commands.describe(target_id="ID цели для атаки.")
    async def cmd_fight(self, interaction: Interaction, target_id: str):
        await interaction.response.defer(ephemeral=False)

        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore
        if not game_mngr:
            await interaction.followup.send("GameManager не доступен.", ephemeral=True)
            return

        char_action_proc: Optional["CharacterActionProcessor"] = game_mngr._character_action_processor # type: ignore
        if not char_action_proc:
            await interaction.followup.send("Обработчик действий персонажа не доступен.", ephemeral=True)
            return

        # Check for other essential managers for this command
        if not game_mngr.character_manager or not game_mngr.npc_manager or \
           not game_mngr.combat_manager or not game_mngr.rule_engine or \
           not game_mngr.location_manager:
            await interaction.followup.send("Один или несколько необходимых игровых модулей не доступны.", ephemeral=True)
            return

        player_char = game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        action_data = {"target_id": target_id}
        result = await char_action_proc.process_action(
            character_id=player_char.id,
            action_type="initiate_combat",
            action_data=action_data,
            context={
                'guild_id': str(interaction.guild_id), 'author_id': str(interaction.user.id),
                'channel_id': interaction.channel_id, 'game_manager': game_mngr,
                'character_manager': game_mngr.character_manager, 'npc_manager': game_mngr.npc_manager,
                'combat_manager': game_mngr.combat_manager, 'rule_engine': game_mngr.rule_engine,
                'location_manager': game_mngr.location_manager,
                'send_to_command_channel': interaction.followup.send
            }
        )

    @app_commands.command(name="talk", description="Поговорить с NPC.")
    @app_commands.describe(npc_id="ID NPC, с которым вы хотите поговорить.", message_text="Ваше первое сообщение (необязательно).")
    async def cmd_talk(self, interaction: Interaction, npc_id: str, message_text: Optional[str] = None):
        await interaction.response.defer(ephemeral=False)

        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore
        if not game_mngr:
            await interaction.followup.send("GameManager не доступен.", ephemeral=True)
            return

        char_action_proc: Optional["CharacterActionProcessor"] = game_mngr._character_action_processor # type: ignore
        if not char_action_proc:
            await interaction.followup.send("Обработчик действий персонажа не доступен.", ephemeral=True)
            return

        # Check for other essential managers for this command
        if not game_mngr.character_manager or not game_mngr.npc_manager or \
           not game_mngr.dialogue_manager or not game_mngr.location_manager:
            await interaction.followup.send("Один или несколько необходимых игровых модулей не доступны.", ephemeral=True)
            return

        player_char = game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        action_data = {"npc_id": npc_id, "initial_message": message_text}
        result = await char_action_proc.process_action(
            character_id=player_char.id,
            action_type="talk",
            action_data=action_data,
            context={
                'guild_id': str(interaction.guild_id), 'author_id': str(interaction.user.id),
                'channel_id': interaction.channel_id, 'game_manager': game_mngr,
                'character_manager': game_mngr.character_manager, 'npc_manager': game_mngr.npc_manager,
                'dialogue_manager': game_mngr.dialogue_manager, 'location_manager': game_mngr.location_manager,
                'send_to_command_channel': interaction.followup.send
            }
        )

    @app_commands.command(name="end_turn", description="Завершает ход: пропускает время/передает инициативу. Если персонаж бездействует, продвигает время.")
    async def cmd_end_turn(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore
        if not game_mngr:
            await interaction.followup.send("GameManager не доступен.", ephemeral=True)
            return

        # Keep existing boilerplate for GameManager
        # CharacterManager is retrieved below, as per existing structure.

        turn_processing_service = game_mngr.turn_processing_service
        if not turn_processing_service:
            await interaction.followup.send("Сервис обработки ходов не доступен.", ephemeral=True)
            return

        if not game_mngr.character_manager: # Check for CharacterManager as it's used next
            await interaction.followup.send("Менеджер персонажей не доступен.", ephemeral=True)
            return

        player_char = game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)

        if player_char:
            player_char.current_status = 'processing_turn'
            game_mngr.character_manager.mark_character_dirty(player_char) # Assumes player_char object is passed

            # Import asyncio if not already imported at the top of the file
            # For this refactoring, assuming asyncio is available (standard library)
            # import asyncio # Add this at the top if it's missing
            await asyncio.sleep(0.5) # Make sure asyncio is imported

            # Ensure player_char.id is the correct attribute for the player's ID
            # The method expects a list of player IDs.
            result = await game_mngr.turn_processing_service.process_player_turns([player_char.id], str(interaction.guild_id))

            guild_id_str = str(interaction.guild_id)
            # Assuming player_char.id is the correct attribute and is a string.
            # If player_char.id is not a string, it should be str(player_char.id).
            # For consistency with how player_id is used in TurnProcessingService results (often string keys in dicts).
            player_id_str = player_char.id

            log_message_suffix = f"for player {player_id_str} in guild {guild_id_str}."

            no_actions_detected = False
            # Condition 1: Global status indicates no actions
            if result.get("status") == "no_actions":
                no_actions_detected = True
            else:
                # Condition 2: Player-specific feedback indicates no actions.
                # This requires checking `processed_action_details` for this player.
                processed_actions_for_player = []
                if isinstance(result.get("processed_action_details"), list):
                    for detail in result["processed_action_details"]:
                        # Ensure comparison is between same types, e.g. both strings if player_id_str is string.
                        if detail.get("player_id") == player_id_str:
                            processed_actions_for_player.append(detail)

                if not processed_actions_for_player and result.get("status") != "error": # Avoid masking errors as "no action"
                    # If no actions were processed for this specific player,
                    # and there wasn't a general error, it's effectively "no actions" for them.
                    # This handles cases where TPS might not set global "no_actions" if other players had actions.
                    no_actions_detected = True
                    # Also check if feedback_per_player for this player explicitly says no actions
                    player_feedback = result.get("feedback_per_player", {}).get(player_id_str, [])
                    if player_feedback and "no actions taken" in player_feedback[0].lower(): # Example check
                         no_actions_detected = True


            if no_actions_detected:
                logging.info(f"cmd_end_turn: No actions found or processed {log_message_suffix}")
                await interaction.followup.send(
                    "Ход завершен, но не было обнаружено действий для обработки. "
                    "Если вы описывали действия текстом, попробуйте еще раз или используйте /undo_action, "
                    "если считаете, что они не были распознаны.",
                    ephemeral=True
                )
            elif result.get("status") == "completed":
                logging.info(f"cmd_end_turn: Actions processed successfully {log_message_suffix}")
                await interaction.followup.send("Ход обработан.", ephemeral=True)
            elif result.get("status") == "error":
                logging.error(f"cmd_end_turn: Error during turn processing {log_message_suffix}. Result: {result}")
                # Provide more specific error if available in feedback
                error_message = "Ошибка при обработке хода."
                player_feedback_msgs = result.get("feedback_per_player", {}).get(player_id_str, [])
                if player_feedback_msgs:
                    error_message = player_feedback_msgs[0]
                await interaction.followup.send(error_message, ephemeral=True)
            else: # Other statuses like "in_progress" or custom ones
                player_feedback_msgs = result.get("feedback_per_player", {}).get(player_id_str, [])
                # Default message if no specific feedback for this player
                default_message = "Обработка вашего хода продолжается или ожидает дополнительных действий."
                feedback_to_send = player_feedback_msgs[0] if player_feedback_msgs else default_message

                logging.info(f"cmd_end_turn: Turn processing status '{result.get('status')}' {log_message_suffix}. Feedback: {feedback_to_send}")
                await interaction.followup.send(feedback_to_send, ephemeral=True)
        else:
            logging.warning(f"cmd_end_turn: Player character not found for Discord user {interaction.user.id} in guild {str(interaction.guild_id)}.")
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return


    @app_commands.command(name="end_party_turn", description="ГМ: Завершить ход для всей текущей активной партии.")
    async def cmd_end_party_turn(self, interaction: Interaction):
        bot_admin_ids = [str(id_val) for id_val in self.bot.game_manager._settings.get('bot_admins', [])]
        if str(interaction.user.id) not in bot_admin_ids: # Simplified GM check
             await interaction.response.send_message("Только Мастер может использовать эту команду.", ephemeral=True)
             return

        await interaction.response.defer(ephemeral=True)

        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore
        if not game_mngr:
            await interaction.followup.send("GameManager не доступен.", ephemeral=True)
            return

        party_action_proc: Optional["PartyActionProcessor"] = game_mngr.party_action_processor # type: ignore
        if not party_action_proc:
            await interaction.followup.send("Обработчик действий партии не доступен.", ephemeral=True)
            return

        result = await party_action_proc.gm_force_end_party_turn(
            guild_id=str(interaction.guild_id),
            context={'game_manager': game_mngr, 'send_to_command_channel': interaction.followup.send}
        )
        if result and result.get("message"):
            await interaction.followup.send(result.get("message"), ephemeral=True)
        elif not result or not result.get("success"):
            if not (result and result.get("message")):
                 await interaction.followup.send("Не удалось завершить ход партии.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ActionModuleCog(bot)) # type: ignore
    print("ActionModuleCog loaded.")

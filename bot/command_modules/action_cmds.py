from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, TYPE_CHECKING
import asyncio
from bot.utils.i18n_utils import get_i18n_text
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

        guild_id_str = str(interaction.guild_id) # Define guild_id_str here
        player_char = game_mngr.character_manager.get_character_by_discord_id(guild_id_str, interaction.user.id)

        if player_char:
            # Set status to indicate readiness for periodic processing
            player_char.current_game_status = 'ожидание_обработки'
            game_mngr.character_manager.mark_character_dirty(guild_id_str, player_char.id)

            # Optional: Immediately save this status change to DB
            try:
                await game_mngr.save_game_state_after_action(guild_id_str)
                logging.info(f"cmd_end_turn: Player {player_char.id} status updated to 'ожидание_обработки' and saved for guild {guild_id_str}.")
            except Exception as e:
                logging.error(f"cmd_end_turn: Error saving player status update for {player_char.id} in guild {guild_id_str}: {e}", exc_info=True)
                # Decide if we should inform the user of save failure or proceed with optimistic message

            # Inform the user
            # TODO: Localize "Turn ended. Your actions will be processed shortly."
            # Assuming get_i18n_text is available and configured for this cog or globally
            # For now, using a direct string.
            lang = player_char.selected_language or (interaction.locale.language if interaction.locale else "en")
            end_turn_confirmation = get_i18n_text(None, "end_turn_confirmation", lang, default_lang="en", default_text="Turn ended. Your actions will be processed shortly.")
            await interaction.followup.send(end_turn_confirmation, ephemeral=True)
        else:
            # TODO: Localize "Character not found."
            lang_for_error = interaction.locale.language if interaction.locale else "en"
            char_not_found_msg = get_i18n_text(None, "inventory_error_no_character", lang_for_error, default_lang="en", default_text="You need to create a character first! Use `/start_new_character`.")
            logging.warning(f"cmd_end_turn: Player character not found for Discord user {interaction.user.id} in guild {guild_id_str}.")
            await interaction.followup.send(char_not_found_msg, ephemeral=True)
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

import discord # For discord.utils.MISSING
from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, TYPE_CHECKING
import asyncio
import logging # Added for logging (already present from previous step, but good to confirm)

from bot.utils.i18n_utils import get_i18n_text
from bot.game.models.action_request import ActionRequest
from bot.database.models import Player # Added for /end_turn
from bot.database.crud_utils import get_entity_by_attributes, update_entity # Added for /end_turn

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.party_processors.party_action_processor import PartyActionProcessor
# import asyncio # Already imported via discord.ext.commands or discord
# import logging # Already imported via discord.ext.commands or discord

logger = logging.getLogger(__name__) # Define logger for the module

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

        # Check for essential managers for this command
        # CharacterManager is checked by getting player_char. RuleEngine is used for rules_config.
        # CharacterActionProcessor (char_action_proc) is assumed to have its internal dependencies (like LocationInteractionService) met.
        if not game_mngr.character_manager or not game_mngr.rule_engine:
            logging.warning(f"cmd_interact: Missing CharacterManager or RuleEngine. CM={bool(game_mngr.character_manager)}, RE={bool(game_mngr.rule_engine)}")
            await interaction.followup.send(get_i18n_text(None, "error_required_modules_missing", interaction.locale.language if interaction.locale and hasattr(interaction.locale, 'language') else "en", "Один или несколько необходимых игровых модулей не доступны."), ephemeral=True)
            return

        player_char = game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        # Prepare action_data for the ActionRequest
        # 'action_type' from the command is the specific kind of interaction (e.g., "pull_lever", "read_sign")
        action_data_for_request = {"target_id": target_id, "interaction_type": action_type}

        # Create the ActionRequest
        action_request = ActionRequest(
            guild_id=str(interaction.guild_id),
            actor_id=player_char.id,
            action_type="PLAYER_INTERACT",  # Generic type for CAP to route to interaction systems
            action_data=action_data_for_request
        )

        rules_config_data = game_mngr.rule_engine.rules_config_data # Already checked rule_engine exists

        context_for_cap = {
            'channel_id': interaction.channel_id,
            'rules_config': rules_config_data,
        }

        try:
            result = await char_action_proc.process_action_from_request(
                action_request=action_request,
                character=player_char,
                context=context_for_cap
            )
        except Exception as e:
            logging.error(f"cmd_interact: Error calling process_action_from_request for {player_char.id} on target {target_id}: {e}", exc_info=True)
            lang_code = player_char.selected_language or (interaction.locale.language if interaction.locale and hasattr(interaction.locale, 'language') else "en")
            error_msg_text = get_i18n_text(None, "interact_error_exception", lang_code, default_text=f"An unexpected error occurred while trying to interact: {e}")
            await interaction.followup.send(error_msg_text, ephemeral=True)
            return

        # Handle the result
        if result and result.get("message"):
            is_ephemeral = result.get("data", {}).get("ephemeral", False)
            view_to_send = discord.utils.MISSING
            # Hypothetical view creation
            # if result.get("data") and result["data"].get("components") and hasattr(self.bot, 'get_dynamic_view_from_data'):
            #    try:
            #        view_to_send = self.bot.get_dynamic_view_from_data(result["data"]["components"])
            #    except Exception as ve:
            #        logging.error(f"cmd_interact: Failed to create view from components: {ve}", exc_info=True)

            await interaction.followup.send(result["message"], view=view_to_send, ephemeral=is_ephemeral)

        elif result and not result.get("success"):
            lang_code = player_char.selected_language or (interaction.locale.language if interaction.locale and hasattr(interaction.locale, 'language') else "en")
            error_text = get_i18n_text(None, "interact_error_generic", lang_code, default_text="Could not complete interaction.")
            await interaction.followup.send(error_text, ephemeral=True)
        elif not result:
            lang_code = player_char.selected_language or (interaction.locale.language if interaction.locale and hasattr(interaction.locale, 'language') else "en")
            fallback_error_text = get_i18n_text(None, "interact_error_unknown", lang_code, default_text="An unknown error occurred while trying to interact.")
            await interaction.followup.send(fallback_error_text, ephemeral=True)

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

        # Prepare action_data for the ActionRequest
        action_data_for_request = {"npc_id": npc_id, "initial_message": message_text}

        # Create the ActionRequest
        action_request = ActionRequest(
            guild_id=str(interaction.guild_id),
            actor_id=player_char.id,
            action_type="PLAYER_TALK",
            action_data=action_data_for_request
        )

        rules_config_data = game_mngr.rule_engine.rules_config_data if game_mngr.rule_engine else None

        context_for_cap = {
            'channel_id': interaction.channel_id,
            'rules_config': rules_config_data,
        }

        try:
            result = await char_action_proc.process_action_from_request(
                action_request=action_request,
                character=player_char,
                context=context_for_cap
            )
        except Exception as e:
            logging.error(f"cmd_talk: Error calling process_action_from_request for {player_char.id}: {e}", exc_info=True)
            lang_code = player_char.selected_language or (interaction.locale.language if interaction.locale and hasattr(interaction.locale, 'language') else "en")
            error_msg_text = get_i18n_text(None, "talk_error_exception", lang_code, default_text=f"An unexpected error occurred while trying to talk: {e}")
            await interaction.followup.send(error_msg_text, ephemeral=True)
            return

        if result and result.get("message"):
            is_ephemeral = result.get("data", {}).get("ephemeral", False)
            view_to_send = discord.utils.MISSING
            # Example for view creation if component data is present and a helper exists
            # if result.get("data") and result["data"].get("components") and hasattr(self.bot, 'get_dynamic_view_from_data'):
            #    try:
            #        view_to_send = self.bot.get_dynamic_view_from_data(result["data"]["components"])
            #    except Exception as ve:
            #        logging.error(f"cmd_talk: Failed to create view from components: {ve}", exc_info=True)

            await interaction.followup.send(result["message"], view=view_to_send, ephemeral=is_ephemeral)

        elif result and not result.get("success"):
            lang_code = player_char.selected_language or (interaction.locale.language if interaction.locale and hasattr(interaction.locale, 'language') else "en")
            error_text = get_i18n_text(None, "talk_error_generic", lang_code, default_text="Could not complete talk action.")
            await interaction.followup.send(error_text, ephemeral=True)
        elif not result:
            lang_code = player_char.selected_language or (interaction.locale.language if interaction.locale and hasattr(interaction.locale, 'language') else "en")
            fallback_error_text = get_i18n_text(None, "talk_error_unknown", lang_code, default_text="An unknown error occurred while trying to talk.")
            await interaction.followup.send(fallback_error_text, ephemeral=True)

    @app_commands.command(name="end_turn", description="Завершает ход: пропускает время/передает инициативу. Если персонаж бездействует, продвигает время.")
    async def cmd_end_turn(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)
        logger.info(f"/end_turn initiated by {discord_id_str} in guild {guild_id_str}.")

        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore
        if not game_mngr or not game_mngr.db_service:
            logger.error(f"/end_turn: GameManager or DBService not available for user {discord_id_str} in guild {guild_id_str}.")
            await interaction.followup.send("Game services are not available. Please try again later.", ephemeral=True)
            return

        try:
            async with game_mngr.db_service.get_session() as session:
                # Fetch the Player model instance
                player = await get_entity_by_attributes(session, Player, {"discord_id": discord_id_str, "guild_id": guild_id_str})

                if not player:
                    logger.warning(f"/end_turn: Player not found for discord_id {discord_id_str} in guild {guild_id_str}.")
                    # TODO: Localize this message
                    await interaction.followup.send("Player not found. Have you registered or started your character?", ephemeral=True)
                    return

                # Update Player status
                new_status = "actions_submitted"
                player.current_game_status = new_status

                # Persist the change for the Player model
                # update_entity handles session.add(player)
                await update_entity(session, player, {"current_game_status": new_status})
                # No specific guild_id needed for update_entity as player object is already specific

                await session.commit()
                logger.info(f"/end_turn: Player {player.id} (Discord: {discord_id_str}) status updated to '{new_status}' in guild {guild_id_str}.")

            # Inform the user
            # TODO: Localize "You have ended your turn. Your actions will be processed soon."
            # For now, using a direct string.
            # lang = player.selected_language or (interaction.locale.language if interaction.locale and hasattr(interaction.locale, 'language') else "en")
            # end_turn_confirmation = get_i18n_text(None, "end_turn_confirmation", lang, default_lang="en", default_text="You have ended your turn. Your actions will be processed soon.")
            end_turn_confirmation = "You have ended your turn. Your actions will be processed soon."
            await interaction.followup.send(end_turn_confirmation, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in /end_turn for user {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            # Rollback is handled by the async_session context manager on exception
            await interaction.followup.send("An unexpected error occurred while ending your turn.", ephemeral=True)

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

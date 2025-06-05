from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.bot_core import RPGBot

class ActionModuleCog(commands.Cog, name="Action Commands Module"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    @app_commands.command(name="interact", description="Взаимодействовать с объектом или NPC.")
    @app_commands.describe(target_id="ID объекта или NPC для взаимодействия.", action_type="Тип взаимодействия (если необходимо).")
    async def cmd_interact(self, interaction: Interaction, target_id: str, action_type: Optional[str] = None):
        await interaction.response.defer(ephemeral=False)
        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_action_processor or not game_mngr.character_manager:
            await interaction.followup.send("Система взаимодействия временно недоступна.", ephemeral=True)
            return

        player_char = await game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        action_data = {"target_id": target_id, "interaction_type": action_type}
        result = await game_mngr.character_action_processor.process_action(
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
        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_action_processor or not game_mngr.character_manager or \
           not game_mngr.npc_manager or not game_mngr.combat_manager or not game_mngr.rule_engine or \
           not game_mngr.location_manager:
            await interaction.followup.send("Боевая система временно недоступна.", ephemeral=True)
            return

        player_char = await game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        action_data = {"target_id": target_id}
        result = await game_mngr.character_action_processor.process_action(
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
        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_action_processor or not game_mngr.character_manager or \
           not game_mngr.npc_manager or not game_mngr.dialogue_manager or not game_mngr.location_manager:
            await interaction.followup.send("Система диалогов временно недоступна.", ephemeral=True)
            return

        player_char = await game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        action_data = {"npc_id": npc_id, "initial_message": message_text}
        result = await game_mngr.character_action_processor.process_action(
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

    @app_commands.command(name="end_turn", description="Завершить свой ход (в бою или пошаговом режиме).")
    async def cmd_end_turn(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_action_processor or not game_mngr.character_manager or \
           not game_mngr.combat_manager: # party_manager might be optional depending on turn structure
            await interaction.followup.send("Система ходов временно недоступна.", ephemeral=True)
            return

        player_char = await game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        result = await game_mngr.character_action_processor.process_action(
            character_id=player_char.id,
            action_type="end_turn",
            action_data={},
            context={
                'guild_id': str(interaction.guild_id), 'author_id': str(interaction.user.id),
                'channel_id': interaction.channel_id, 'game_manager': game_mngr,
                'character_manager': game_mngr.character_manager, # Added for completeness
                'combat_manager': game_mngr.combat_manager,
                'party_manager': game_mngr.party_manager,
                'send_to_command_channel': interaction.followup.send
            }
        )
        if result and result.get("message"):
             await interaction.followup.send(result.get("message"), ephemeral=True)
        elif not result or not result.get("success"):
            # Only send this if process_action didn't already send a more specific message.
            # This requires process_action to have a clear contract about its own messaging.
            # For now, assuming if success is false, a generic message here is okay if no message in result.
            if not (result and result.get("message")):
                 await interaction.followup.send("Не удалось завершить ход.", ephemeral=True)


    @app_commands.command(name="end_party_turn", description="ГМ: Завершить ход для всей текущей активной партии.")
    async def cmd_end_party_turn(self, interaction: Interaction):
        bot_admin_ids = [str(id_val) for id_val in self.bot.game_manager._settings.get('bot_admins', [])]
        if str(interaction.user.id) not in bot_admin_ids: # Simplified GM check
             await interaction.response.send_message("Только Мастер может использовать эту команду.", ephemeral=True)
             return

        await interaction.response.defer(ephemeral=True)
        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.party_action_processor:
            await interaction.followup.send("Система управления партиями недоступна.", ephemeral=True)
            return

        result = await game_mngr.party_action_processor.gm_force_end_party_turn(
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

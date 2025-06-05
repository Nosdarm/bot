from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.bot_core import RPGBot

class ExplorationCog(commands.Cog, name="Exploration Commands"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    @app_commands.command(name="look", description="Осмотреть текущую локацию или конкретный объект.")
    @app_commands.describe(target="Объект или направление для осмотра (необязательно).")
    async def cmd_look(self, interaction: Interaction, target: Optional[str] = None):
        await interaction.response.defer(ephemeral=False)
        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_action_processor:
            await interaction.followup.send("Система исследования мира временно недоступна.", ephemeral=True)
            return

        action_data = {"target": target} if target else {}
        
        player_char = await game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        result = await game_mngr.character_action_processor.process_action(
            character_id=player_char.id,
            action_type="look",
            action_data=action_data,
            context={
                'guild_id': str(interaction.guild_id),
                'author_id': str(interaction.user.id),
                'channel_id': interaction.channel_id,
                'game_manager': game_mngr,
                'character_manager': game_mngr.character_manager,
                'location_manager': game_mngr.location_manager,
                'item_manager': game_mngr.item_manager,
                'npc_manager': game_mngr.npc_manager,
                'openai_service': game_mngr.openai_service,
                'send_to_command_channel': interaction.followup.send
            }
        )

    @app_commands.command(name="move", description="Переместиться в другую локацию.")
    @app_commands.describe(destination="Название выхода или ID локации назначения.")
    async def cmd_move(self, interaction: Interaction, destination: str):
        await interaction.response.defer(ephemeral=False)
        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_action_processor:
            await interaction.followup.send("Система перемещения временно недоступна.", ephemeral=True)
            return

        player_char = await game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        action_data = {"destination": destination}
        result = await game_mngr.character_action_processor.process_action(
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
        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_action_processor:
            await interaction.followup.send("Система проверки навыков временно недоступна.", ephemeral=True)
            return

        player_char = await game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not player_char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True)
            return

        action_data = {"skill_name": skill_name, "target": target if target else "окружение"}
        
        result = await game_mngr.character_action_processor.process_action(
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

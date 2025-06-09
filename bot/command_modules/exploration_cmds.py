from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, TYPE_CHECKING

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

        if char_action_proc:
            try:
                action_params_for_handler = {}
                if target: # 'target' is the argument to cmd_look
                    action_params_for_handler['target_name'] = target

                explore_result = await char_action_proc.handle_explore_action(
                    character=player_char,
                    guild_id=str(interaction.guild_id),
                    action_params=action_params_for_handler,
                    context_channel_id=interaction.channel_id
                )

                if explore_result.get("success"):
                    # Send as non-ephemeral to the channel by default
                    await interaction.followup.send(explore_result.get("message", "Вы ничего особенного не видите."), ephemeral=False)
                else:
                    await interaction.followup.send(explore_result.get("message", "Вы не можете осмотреться."), ephemeral=True)
            except Exception as e:
                print(f"Error in cmd_look calling handle_explore_action: {e}")
                # Consider logging traceback
                # import traceback
                # traceback.print_exc()
                await interaction.followup.send("Произошла ошибка при попытке осмотреться.", ephemeral=True)
        else:
            # This case should ideally be caught by earlier checks for char_action_proc
            await interaction.followup.send("Не удалось обработать команду осмотра в данный момент.", ephemeral=True)

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

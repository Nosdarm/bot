# bot/command_modules/character_cmds.py
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
import json
from typing import TYPE_CHECKING, Optional, Literal, Dict, Any, List # Added Dict, Any, List

if TYPE_CHECKING:
    from bot.bot_core import RPGBot # Changed from BotCore
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.models.character import Character
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.services.notification_service import NotificationService
    from bot.game.rules.rule_engine import RuleEngine

class CharacterDevelopmentCog(commands.Cog):
    def __init__(self, bot: RPGBot): # Changed BotCore to RPGBot
        self.bot = bot
        # Assuming game_manager is always present on RPGBot after setup
        game_mngr: GameManager = self.bot.game_manager # type: ignore[assignment]
        self.character_manager: Optional[CharacterManager] = game_mngr.character_manager
        self.game_log_manager: Optional[GameLogManager] = game_mngr.game_log_manager
        self.notification_service: Optional[NotificationService] = game_mngr.notification_service
        self.rule_engine: Optional[RuleEngine] = game_mngr.rule_engine

    @app_commands.command(name="spend_xp", description="Spend your Unspent XP to improve your character.")
    @app_commands.describe(
        improvement_type="What do you want to improve?",
        stat_name="The name of the stat to improve (e.g., strength, dexterity).",
        skill_name="The name of the skill to learn or improve."
    )
    async def spend_xp(
        self,
        interaction: discord.Interaction,
        improvement_type: Literal["increase_stat", "learn_skill", "improve_skill"],
        stat_name: Optional[str] = None,
        skill_name: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id:
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        if not self.character_manager or not self.rule_engine or not self.game_log_manager:
            await interaction.followup.send("Character services are not available at the moment.", ephemeral=True)
            return

        char: Optional[Character] = await self.character_manager.get_character_by_discord_id(guild_id, discord_user_id)

        if not char:
            await interaction.followup.send("You don't have a character in this game yet.", ephemeral=True)
            return

        if not hasattr(char, 'unspent_xp') or char.unspent_xp is None: # Added None check
            char.unspent_xp = 0

        # Ensure rules_data is accessed correctly if it's a method or property
        rules_data = {}
        if hasattr(self.rule_engine, '_rules_data') and isinstance(self.rule_engine._rules_data, dict): # Basic check
            rules_data = self.rule_engine._rules_data
        elif hasattr(self.rule_engine, 'get_rules_data_for_guild'): # Ideal
            rules_data = await self.rule_engine.get_rules_data_for_guild(guild_id) or {}

        dev_rules = rules_data.get("character_development_rules", {})
        feedback_message = "Could not process improvement."
        success = False
        log_details: Dict[str, Any] = {}

        if improvement_type == "increase_stat":
            if not stat_name:
                await interaction.followup.send("Please specify the `stat_name` to improve.", ephemeral=True)
                return
            cost = dev_rules.get("stat_increase_cost", 10)
            if char.unspent_xp >= cost: # type: ignore[operator] # char.unspent_xp is now int
                current_stats = getattr(char, "stats", {})
                if isinstance(current_stats, dict) and stat_name.lower() in current_stats:
                    current_stats[stat_name.lower()] = current_stats.get(stat_name.lower(), 0) + 1
                    char.unspent_xp -= cost # type: ignore[operator]
                    await self.character_manager.trigger_stats_recalculation(guild_id, char.id)
                    self.character_manager.mark_character_dirty(guild_id, char.id)
                    log_details = {
                        "message": f"{char.name} increased {stat_name} to {current_stats[stat_name.lower()]}.",
                        "related_entities": [{"id": char.id, "type": "Character"}],
                        "metadata": {"improvement": "stat", "stat": stat_name, "cost": cost}
                    }
                    feedback_message = f"You spent {cost} Unspent XP to increase {stat_name} to {current_stats[stat_name.lower()]}!"
                    success = True
                else: feedback_message = f"Stat '{stat_name}' not found."
            else: feedback_message = f"Not enough XP. Need {cost}, have {char.unspent_xp}."

        elif improvement_type == "learn_skill":
            if not skill_name: await interaction.followup.send("Please specify `skill_name`.", ephemeral=True); return
            cost = dev_rules.get("skill_learn_cost", 5)
            if char.unspent_xp >= cost: # type: ignore[operator]
                char_skills = getattr(char, "skills", None)
                if char_skills is None: char.skills = {}
                if not isinstance(char.skills, dict): char.skills = {} # Ensure it's a dict

                if skill_name.lower() not in char.skills:
                    char.skills[skill_name.lower()] = 1
                    char.unspent_xp -= cost # type: ignore[operator]
                    await self.character_manager.trigger_stats_recalculation(guild_id, char.id)
                    self.character_manager.mark_character_dirty(guild_id, char.id)
                    log_details = {"message": f"{char.name} learned {skill_name}.", "related_entities": [{"id": char.id, "type": "Character"}], "metadata": {"improvement": "learn_skill", "skill": skill_name, "cost": cost}}
                    feedback_message = f"Spent {cost} XP to learn {skill_name}!"
                    success = True
                else: feedback_message = f"You already know {skill_name}."
            else: feedback_message = f"Not enough XP. Need {cost}, have {char.unspent_xp}."

        elif improvement_type == "improve_skill":
            if not skill_name: await interaction.followup.send("Please specify `skill_name`.", ephemeral=True); return
            cost = dev_rules.get("skill_improve_cost", 2)
            if char.unspent_xp >= cost: # type: ignore[operator]
                char_skills = getattr(char, "skills", None)
                if isinstance(char_skills, dict) and skill_name.lower() in char_skills:
                    char_skills[skill_name.lower()] = char_skills.get(skill_name.lower(), 0) + 1
                    char.unspent_xp -= cost # type: ignore[operator]
                    await self.character_manager.trigger_stats_recalculation(guild_id, char.id)
                    self.character_manager.mark_character_dirty(guild_id, char.id)
                    log_details = {"message": f"{char.name} improved {skill_name} to {char_skills[skill_name.lower()]}.", "related_entities": [{"id": char.id, "type": "Character"}], "metadata": {"improvement": "improve_skill", "skill": skill_name, "cost": cost}}
                    feedback_message = f"Spent {cost} XP to improve {skill_name} to level {char_skills[skill_name.lower()]}!"
                    success = True
                else: feedback_message = f"Skill '{skill_name}' not found or not learned."
            else: feedback_message = f"Not enough XP. Need {cost}, have {char.unspent_xp}."

        if success and self.game_log_manager and log_details:
            await self.game_log_manager.log_event(guild_id, "XP_SPENT", details=log_details)

        if success and self.notification_service:
            await self.notification_service.send_notification(str(discord_user_id), feedback_message) # Ensure discord_user_id is str

        await interaction.followup.send(feedback_message, ephemeral=True)

    @app_commands.command(name="stats", description="Показывает характеристики вашего персонажа.")
    async def cmd_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id: await interaction.followup.send("Use in a server.", ephemeral=True); return
        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        if not self.character_manager: await interaction.followup.send("Char manager unavailable.", ephemeral=True); return

        char: Optional[Character] = await self.character_manager.get_character_by_discord_id(guild_id, discord_user_id)
        if not char: await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True); return

        await self.character_manager.trigger_stats_recalculation(guild_id, char.id)
        char = await self.character_manager.get_character(guild_id, char.id) # Re-fetch
        if not char: await interaction.followup.send("Ошибка при обновлении данных.", ephemeral=True); return

        char_name = getattr(char, 'name', 'Безымянный')
        if isinstance(getattr(char, 'name_i18n', None), dict):
            char_name = char.name_i18n.get(str(interaction.locale), char.name_i18n.get("en", char_id_val)) # type: ignore # char_id_val not defined

        embed = discord.Embed(title=f"Статистика: {char_name}", color=discord.Color.blue())
        embed.add_field(name="Имя", value=char_name, inline=True)
        embed.add_field(name="Уровень", value=str(getattr(char, 'level', 1)), inline=True)
        embed.add_field(name="Опыт", value=str(getattr(char, 'experience', 0)), inline=True)
        embed.add_field(name="Непотраченный опыт", value=str(getattr(char, 'unspent_xp', 0)), inline=True)

        base_stats_str = []
        base_stats_data = getattr(char, 'stats', {})
        if isinstance(base_stats_data, dict) and base_stats_data: # Check if dict and not empty
            for stat_name, stat_value in base_stats_data.items(): base_stats_str.append(f"**{stat_name.capitalize()}**: {stat_value}")
            embed.add_field(name="Базовые Характеристики", value="\n".join(base_stats_str) or "Нет данных", inline=False)
        else: embed.add_field(name="Базовые Характеристики", value="Нет данных", inline=False)

        effective_stats_str = []
        effective_stats_json_str = getattr(char, 'effective_stats_json', '{}') # Default to empty JSON string
        effective_stats_data: Optional[Dict[str, Any]] = None # Initialize
        try:
            if isinstance(effective_stats_json_str, str): effective_stats_data = json.loads(effective_stats_json_str)
            elif isinstance(effective_stats_json_str, dict): effective_stats_data = effective_stats_json_str # Already a dict

            if isinstance(effective_stats_data, dict) and effective_stats_data:
                for stat_name, stat_value in effective_stats_data.items(): effective_stats_str.append(f"**{stat_name.replace('_', ' ').capitalize()}**: {stat_value}")
                embed.add_field(name="Эффективные Характеристики", value="\n".join(effective_stats_str) or "Нет данных", inline=False)
            else: embed.add_field(name="Эффективные Характеристики", value="Нет данных (не рассчитаны)", inline=False)
        except json.JSONDecodeError: embed.add_field(name="Эффективные Характеристики", value="Ошибка данных.", inline=False)

        current_hp = getattr(char, 'hp', 'N/A')
        max_hp_val = 'N/A'
        if isinstance(effective_stats_data, dict): max_hp_val = effective_stats_data.get('max_hp', getattr(char, 'max_health', 'N/A'))
        else: max_hp_val = getattr(char, 'max_health', 'N/A')
        embed.add_field(name="Здоровье", value=f"{current_hp} / {max_hp_val}", inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: RPGBot): # Changed BotCore to RPGBot
    await bot.add_cog(CharacterDevelopmentCog(bot))

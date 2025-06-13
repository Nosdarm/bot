# bot/command_modules/character_cmds.py
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from typing import TYPE_CHECKING, Optional, Literal

if TYPE_CHECKING:
    from bot.bot_core import BotCore
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.services.notification_service import NotificationService
    from bot.game.rules.rule_engine import RuleEngine # To access character_development_rules

# Define a cog for character development commands
class CharacterDevelopmentCog(commands.Cog):
    def __init__(self, bot: BotCore):
        self.bot = bot
        # Corrected access to character_manager through game_manager
        self.character_manager: CharacterManager = self.bot.game_manager.character_manager
        self.game_log_manager: GameLogManager = self.bot.get_manager("GameLogManager") # Assuming this is correct or will be addressed separately
        self.notification_service: NotificationService = self.bot.get_service("NotificationService")
        self.rule_engine: RuleEngine = self.bot.get_manager("RuleEngine") # RuleEngine for rules

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
        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        char = self.character_manager.get_character_by_discord_id(guild_id, discord_user_id)

        if not char:
            await interaction.followup.send("You don't have a character in this game yet.", ephemeral=True)
            return

        if not hasattr(char, 'unspent_xp'):
            char.unspent_xp = 0 # Initialize if missing, though it should be by RuleEngine

        dev_rules = self.rule_engine._rules_data.get("character_development_rules", {})
        feedback_message = "Could not process improvement."
        success = False

        if improvement_type == "increase_stat":
            if not stat_name:
                await interaction.followup.send("Please specify the `stat_name` to improve.", ephemeral=True)
                return

            cost = dev_rules.get("stat_increase_cost", 10)
            if char.unspent_xp >= cost:
                if stat_name.lower() in char.stats:
                    char.stats[stat_name.lower()] += 1
                    char.unspent_xp -= cost
                    await self.character_manager.trigger_stats_recalculation(guild_id, char.id)
                    self.character_manager.mark_character_dirty(guild_id, char.id)
                    await self.game_log_manager.log_event(
                        guild_id, "XP_SPENT",
                        f"{char.name} increased {stat_name} to {char.stats[stat_name.lower()]}.",
                        related_entities=[{"id": char.id, "type": "Character"}],
                        metadata={"improvement": "stat", "stat": stat_name, "cost": cost}
                    )
                    feedback_message = f"You spent {cost} Unspent XP to increase {stat_name} to {char.stats[stat_name.lower()]}!"
                    success = True
                else:
                    feedback_message = f"Stat '{stat_name}' not found for your character."
            else:
                feedback_message = f"Not enough Unspent XP. You need {cost}, but have {char.unspent_xp}."

        elif improvement_type == "learn_skill":
            if not skill_name:
                await interaction.followup.send("Please specify the `skill_name` to learn.", ephemeral=True)
                return

            cost = dev_rules.get("skill_learn_cost", 5)
            if char.unspent_xp >= cost:
                if not hasattr(char, 'skills') or char.skills is None: # Ensure skills dict exists
                    char.skills = {}
                if skill_name.lower() not in char.skills:
                    char.skills[skill_name.lower()] = 1 # Learn at level 1
                    char.unspent_xp -= cost
                    # Skills might affect effective_stats if they grant passive bonuses, trigger recalc
                    await self.character_manager.trigger_stats_recalculation(guild_id, char.id)
                    self.character_manager.mark_character_dirty(guild_id, char.id)
                    await self.game_log_manager.log_event(
                        guild_id, "XP_SPENT",
                        f"{char.name} learned skill {skill_name}.",
                        related_entities=[{"id": char.id, "type": "Character"}],
                        metadata={"improvement": "learn_skill", "skill": skill_name, "cost": cost}
                    )
                    feedback_message = f"You spent {cost} Unspent XP to learn the skill: {skill_name}!"
                    success = True
                else:
                    feedback_message = f"You already know the skill: {skill_name}."
            else:
                feedback_message = f"Not enough Unspent XP. You need {cost}, but have {char.unspent_xp}."

        elif improvement_type == "improve_skill":
            if not skill_name:
                await interaction.followup.send("Please specify the `skill_name` to improve.", ephemeral=True)
                return

            cost = dev_rules.get("skill_improve_cost", 2)
            if char.unspent_xp >= cost:
                if hasattr(char, 'skills') and char.skills is not None and skill_name.lower() in char.skills:
                    char.skills[skill_name.lower()] += 1
                    char.unspent_xp -= cost
                    await self.character_manager.trigger_stats_recalculation(guild_id, char.id)
                    self.character_manager.mark_character_dirty(guild_id, char.id)
                    await self.game_log_manager.log_event(
                        guild_id, "XP_SPENT",
                        f"{char.name} improved {skill_name} to level {char.skills[skill_name.lower()]}.",
                        related_entities=[{"id": char.id, "type": "Character"}],
                        metadata={"improvement": "improve_skill", "skill": skill_name, "cost": cost}
                    )
                    feedback_message = f"You spent {cost} Unspent XP to improve {skill_name} to level {char.skills[skill_name.lower()]}!"
                    success = True
                else:
                    feedback_message = f"Skill '{skill_name}' not found or not learned by your character."
            else:
                feedback_message = f"Not enough Unspent XP. You need {cost}, but have {char.unspent_xp}."

        if success:
            await self.notification_service.send_notification(discord_user_id, feedback_message)
        await interaction.followup.send(feedback_message, ephemeral=True)

# Setup function for the cog
async def setup(bot: BotCore):
    await bot.add_cog(CharacterDevelopmentCog(bot))

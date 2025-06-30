import unittest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from unittest.mock import AsyncMock, MagicMock, patch
import json

from bot.bot_core import bot # Corrected import path
from bot.game.managers.game_manager import GameManager # Corrected import path
from bot.services.db_service import DBService

class TestIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db_service = DBService()
        self.game_manager = GameManager(self.db_service, {})
        bot.game_manager = self.game_manager

    async def test_full_flow(self):
        # Mock the discord context
        ctx = AsyncMock()
        ctx.guild.id = 123
        ctx.author.id = 456
        ctx.author.name = "TestUser"

        # 1. Start the game
        await bot.get_command('start')(ctx)
        
        # 2. Look around
        await bot.get_command('look')(ctx)
        
        # 3. End turn
        await bot.get_command('end_turn')(ctx)
        
        # 4. Move
        await bot.get_command('move')(ctx, destination="tavern")
        
        # 5. End turn
        await bot.get_command('end_turn')(ctx)

if __name__ == '__main__':
    unittest.main()

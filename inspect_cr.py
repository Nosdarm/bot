import inspect
from bot.game.command_router import CommandRouter

print(inspect.signature(CommandRouter.__init__))

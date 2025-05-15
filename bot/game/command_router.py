import json
import traceback
from typing import Optional, Dict, Any, List, Callable, Awaitable

# Импортируем необходимые типы Discord объектов и Embed
from discord import Message, Embed, Colour

# Импорты менеджеров и процессоров
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.event_manager import EventManager
from bot.game.event_processors.event_action_processor import EventActionProcessor
from bot.game.event_processors.event_stage_processor import EventStageProcessor
from bot.game.managers.persistence_manager import PersistenceManager
from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
from bot.game.managers.location_manager import LocationManager
from bot.game.rules.rule_engine import RuleEngine
from bot.services.openai_service import OpenAIService
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.crafting_manager import CraftingManager
from bot.game.managers.economy_manager import EconomyManager
from bot.game.character_processors.character_action_processor import CharacterActionProcessor
from bot.game.character_processors.character_view_service import CharacterViewService
from bot.game.party_processors.party_action_processor import PartyActionProcessor


# Типы для колбэков отправки сообщений: принимает content и любые kwargs (embed, files, tts и т.д.)
SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

# Тип для функции-обработчика команд
CommandHandler = Callable[[int, str, List[str], Message], Awaitable[None]]


class CommandRouter:
    """
    Маршрутизатор Discord-команд: парсит префикс, ключевое слово и аргументы,
    делегирует выполнение соответствующим менеджерам и процессорам.
    """
    def __init__(
        self,
        character_manager: CharacterManager,
        event_manager: EventManager,
        event_action_processor: EventActionProcessor,
        event_stage_processor: EventStageProcessor,
        persistence_manager: PersistenceManager,
        settings: Dict[str, Any],
        world_simulation_processor: WorldSimulationProcessor,
        send_callback_factory: SendCallbackFactory,
        character_action_processor: CharacterActionProcessor,
        character_view_service: CharacterViewService,
        party_action_processor: Optional[PartyActionProcessor] = None,
        location_manager: Optional[LocationManager] = None,
        rule_engine: Optional[RuleEngine] = None,
        openai_service: Optional[OpenAIService] = None,
        item_manager: Optional[ItemManager] = None,
        npc_manager: Optional[NpcManager] = None,
        combat_manager: Optional[CombatManager] = None,
        time_manager: Optional[TimeManager] = None,
        status_manager: Optional[StatusManager] = None,
        party_manager: Optional[PartyManager] = None,
        crafting_manager: Optional[CraftingManager] = None,
        economy_manager: Optional[EconomyManager] = None,
    ):
        print("Initializing CommandRouter...")
        self._character_manager = character_manager
        self._event_manager = event_manager
        self._event_action_processor = event_action_processor
        self._event_stage_processor = event_stage_processor
        self._persistence_manager = persistence_manager
        self._settings = settings
        self._world_simulation_processor = world_simulation_processor
        self._send_callback_factory = send_callback_factory
        self._character_action_processor = character_action_processor
        self._character_view_service = character_view_service
        self._party_action_processor = party_action_processor
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._openai_service = openai_service
        self._item_manager = item_manager
        self._npc_manager = npc_manager
        self._combat_manager = combat_manager
        self._time_manager = time_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._crafting_manager = crafting_manager
        self._economy_manager = economy_manager

        self._command_prefix = settings.get('discord_command_prefix', '/')
        self._gm_discord_ids = set(settings.get('gm_discord_ids', []))

        self._gm_subcommands: Dict[str, CommandHandler] = {
            "help": self._handle_gm_help_command,
            "load_campaign": self._handle_gm_load_campaign_command,
            "save_state": self._handle_gm_save_state_command,
            "create_char": self._handle_gm_create_char_command,
            "create_npc": self._handle_gm_create_npc_command,
            "delete_npc": self._handle_gm_delete_npc_command,
            "start_event": self._handle_gm_start_event_command,
            "end_event": self._handle_gm_end_event_command,
        }

        self._char_subcommands: Dict[str, CommandHandler] = {
            "help": self._handle_character_help_command,
            "create": self._handle_character_create_command,
            "sheet": self._handle_character_sheet_command,
            "inventory": self._handle_character_inventory_command,
            "use": self._handle_character_use_item_command,
        }

        self._party_subcommands: Dict[str, CommandHandler] = {
            "help": self._handle_party_help_command,
            "create": self._handle_party_create_command,
            "join": self._handle_party_join_command,
            "leave": self._handle_party_leave_command,
            "disband": self._handle_party_disband_command,
            "invite": self._handle_party_invite_command,
            "accept": self._handle_party_accept_invite_command,
            "deny": self._handle_party_deny_invite_command,
        }

        self._commands: Dict[str, CommandHandler] = {
            "help": self._handle_help_command,
            "status": self._handle_status_command,
            "look": self._handle_look_command,
            "move": self._handle_move_command,
            "roll": self._handle_roll_command,
            "talk": self._handle_talk_command,
            "gm": self._handle_gm_command,
            "character": self._handle_character_command,
            "party": self._handle_party_command,
        }

        print("CommandRouter initialized.")

    def get_command_prefix(self, message: Message) -> str:
        return self._command_prefix

    def _is_gm(self, discord_user_id: int) -> bool:
        return discord_user_id in self._gm_discord_ids

    async def route(self, message: Message) -> None:
        content = message.content.strip()
        prefix = self.get_command_prefix(message)
        if not content.startswith(prefix):
            return

        parts = content[len(prefix):].split(maxsplit=1)
        if not parts:
            return

        command = parts[0].lower()
        args = parts[1].split() if len(parts) > 1 else []
        discord_user_id = message.author.id

        print(f"CommandRouter: Received command '{command}' from user {discord_user_id} with args: {args}.")
        send_callback = self._send_callback_factory(message.channel.id)
        handler = self._commands.get(command)

        if handler:
            try:
                await handler(discord_user_id, command, args, message)
            except Exception as e:
                print(f"Error executing command '{command}': {e}")
                traceback.print_exc()
                await send_callback(f"❌ Ошибка выполнения команды `{prefix}{command}`.")
        else:
            await send_callback(f"🤷‍♀️ Неизвестная команда `{prefix}{command}`. Используйте `{prefix}help`.")

    # --- Основные команды ---
    async def _handle_help_command(
        self,
        discord_user_id: int,
        command: str,
        args: List[str],
        message: Message
    ) -> None:
        send_callback = self._send_callback_factory(message.channel.id)
        if not args:
            cmds = [f"`{self._command_prefix}{c}`" for c in self._commands if c not in ['gm','character','party']]
            text = "**Основные команды:**\n" + "\n".join(sorted(cmds))
            await send_callback(text)
        else:
            target = args[0].lower()
            if target == 'status':
                await send_callback(f"Команда `{self._command_prefix}status` показывает состояние вашего персонажа.")
            else:
                await send_callback(f"Нет подробной справки для `{target}`.")

    async def _handle_status_command(
        self,
        discord_user_id: int,
        command: str,
        args: List[str],
        message: Message
    ) -> None:
        send_callback = self._send_callback_factory(message.channel.id)
        target_char = self._character_manager.get_character_by_discord_id(discord_user_id)
        if not target_char:
            await send_callback(f"У вас нет персонажа. Создайте его `{self._command_prefix}character create <Имя>`.")
            return
        if not self._character_view_service:
            await send_callback("Сервис просмотра недоступен.")
            return

        status_embed = await self._character_view_service.get_character_sheet_embed(target_char)
        if status_embed:
            await send_callback(embed=status_embed)
            print(f"Status embed sent for character {target_char.id}.")
        else:
            await send_callback("Не удалось получить информацию о персонаже.")

    async def _handle_look_command(
        self,
        discord_user_id: int,
        command: str,
        args: List[str],
        message: Message
    ) -> None:
        send_callback = self._send_callback_factory(message.channel.id)
        player_char = self._character_manager.get_character_by_discord_id(discord_user_id)
        if not player_char:
            await send_callback("У вас нет персонажа.")
            return
        target = args[0] if args else "окрестности"
        await send_callback(f"Вы осматриваете {target}. WIP.")

    async def _handle_move_command(
        self,
        discord_user_id: int,
        command: str,
        args: List[str],
        message: Message
    ) -> None:
        send_callback = self._send_callback_factory(message.channel.id)
        player_char = self._character_manager.get_character_by_discord_id(discord_user_id)
        if not player_char:
            await send_callback("У вас нет персонажа.")
            return
        if not args:
            await send_callback(f"Куда? Например `{self._command_prefix}move north`.")
            return
        dest = " ".join(args)
        await send_callback(f"Перемещаемся в '{dest}'. WIP.")

    async def _handle_roll_command(
        self,
        discord_user_id: int,
        command: str,
        args: List[str],
        message: Message
    ) -> None:
        send_callback = self._send_callback_factory(message.channel.id)
        player_char = self._character_manager.get_character_by_discord_id(discord_user_id)
        if not player_char:
            await send_callback("У вас нет персонажа.")
            return
        if not args:
            await send_callback(f"Укажите бросок, напр. `{self._command_prefix}roll 1d6+2`.")
            return
        formula = " ".join(args)
        await send_callback(f"Результат броска '{formula}' WIP.")

    async def _handle_talk_command(
        self,
        discord_user_id: int,
        command: str,
        args: List[str],
        message: Message
    ) -> None:
        send_callback = self._send_callback_factory(message.channel.id)
        player_char = self._character_manager.get_character_by_discord_id(discord_user_id)
        if not player_char:
            await send_callback("У вас нет персонажа.")
            return
        if not args:
            await send_callback(f"Кому говорить? `{self._command_prefix}talk NPC`.")
            return
        name = " ".join(args)
        await send_callback(f"Разговор с '{name}' WIP.")

    # --- GM команды ---
    async def _handle_gm_command(
        self,
        discord_user_id: int,
        command: str,
        args: List[str],
        message: Message
    ) -> None:
        send_callback = self._send_callback_factory(message.channel.id)
        if not self._is_gm(discord_user_id):
            await send_callback("🚫 Только GM может")
            return
        if not args:
            await send_callback(f"Используйте `{self._command_prefix}gm help`.")
            return
        subcmd = args[0].lower()
        handler = self._gm_subcommands.get(subcmd)
        if handler:
            await handler(discord_user_id, subcmd, args[1:], message)
        else:
            await send_callback(f"Неизвестна GM подкоманда `{subcmd}`.")

    async def _handle_gm_help_command(
        self,
        discord_user_id: int,
        command: str,
        args: List[str],
        message: Message
    ) -> None:
        send_callback = self._send_callback_factory(message.channel.id)
        cmds = [f"`{self._command_prefix}gm {c}`" for c in self._gm_subcommands]
        await send_callback("**GM команды:**\n" + "\n".join(sorted(cmds)))

    async def _handle_gm_load_campaign_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        if not args:
            await send_callback(f"Укажите файл: `{self._command_prefix}gm load_campaign <файл>`.")
            return
        path = args[0]
        try:
            # TODO: actual load
            await send_callback(f"Кампания '{path}' загружена (заглушка)")
        except FileNotFoundError:
            await send_callback(f"Файл '{path}' не найден.")
        except json.JSONDecodeError:
            await send_callback(f"Ошибка JSON в '{path}'.")
        except Exception as e:
            await send_callback(f"Ошибка: {e}")

    async def _handle_gm_save_state_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        try:
            if self._persistence_manager:
                await self._persistence_manager.save_game_state()
                await send_callback("✅ Состояние сохранено.")
            else:
                await send_callback("Persistence недоступен.")
        except Exception as e:
            await send_callback(f"Ошибка сохранения: {e}")

    async def _handle_gm_create_char_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        if not args or len(args) < 2:
            await send_callback(f"Используйте `{self._command_prefix}gm create_char <DiscordID> <Имя>`.")
            return
        target_id = int(args[0])
        name = " ".join(args[1:])
        try:
            new_char = await self._character_manager.create_character(
                discord_id=target_id,
                name=name,
                initial_location_id=None
            )
            if new_char:
                await send_callback(f"✅ Создан персонаж '{new_char.name}' (<@{target_id}>). ID: {new_char.id}")
                if self._persistence_manager:
                    await self._persistence_manager.save_game_state()
            else:
                await send_callback(f"❌ Не удалось создать '{name}'.")
        except Exception as e:
            await send_callback(f"Ошибка создания: {e}")

    async def _handle_gm_create_npc_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        await send_callback("GM: create_npc - WIP")

    async def _handle_gm_delete_npc_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        await send_callback("GM: delete_npc - WIP")

    async def _handle_gm_start_event_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        await send_callback("GM: start_event - WIP")

    async def _handle_gm_end_event_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        await send_callback("GM: end_event - WIP")

    # --- Команды персонажа (/character) ---
    async def _handle_character_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        if not args:
            await send_callback(f"Используйте `{self._command_prefix}character help`.")
            return
        subcmd = args[0].lower()
        handler = self._char_subcommands.get(subcmd)
        if handler:
            await handler(discord_user_id, subcmd, args[1:], message)
        else:
            await send_callback(f"Неизвестна команда character `{subcmd}`.")

    async def _handle_character_help_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        cmds = [f"`{self._command_prefix}character {c}`" for c in self._char_subcommands]
        await send_callback("**Команды персонажа:**\n" + "\n".join(sorted(cmds)))

    async def _handle_character_create_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        if not args:
            await send_callback(f"Укажите имя: `{self._command_prefix}character create <Имя>`.")
            return
        name = " ".join(args)
        existing = self._character_manager.get_character_by_discord_id(discord_user_id)
        if existing:
            await send_callback(f"У вас уже есть персонаж '{existing.name}'.")
            return
        new_char = await self._character_manager.create_character(
            discord_id=discord_user_id,
            name=name,
            initial_location_id=None
        )
        if new_char:
            await send_callback(f"✅ Ваш персонаж '{new_char.name}' создан! ID: {new_char.id}")
            if self._persistence_manager:
                await self._persistence_manager.save_game_state()
        else:
            await send_callback(f"❌ Не удалось создать '{name}'.")

    async def _handle_character_sheet_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        char = self._character_manager.get_character_by_discord_id(discord_user_id)
        if not char:
            await send_callback("У вас нет персонажа.")
            return
        embed = await self._character_view_service.get_character_sheet_embed(char)
        if embed:
            await send_callback(embed=embed)
        else:
            await send_callback("Не удалось получить лист персонажа.")

    async def _handle_character_inventory_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        # WIP
        await send_callback("Character: inventory - WIP")

    async def _handle_character_use_item_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        # WIP
        await send_callback("Character: use - WIP")

    # --- Команды партии (/party) ---
    async def _handle_party_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        if not args:
            await send_callback(f"Используйте `{self._command_prefix}party help`.")
            return
        subcmd = args[0].lower()
        handler = self._party_subcommands.get(subcmd)
        if handler:
            await handler(discord_user_id, subcmd, args[1:], message)
        else:
            await send_callback(f"Неизвестна команда party `{subcmd}`.")

    async def _handle_party_help_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        cmds = [f"`{self._command_prefix}party {c}`" for c in self._party_subcommands]
        await send_callback("**Команды партии:**\n" + "\n".join(sorted(cmds)))

    async def _handle_party_create_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        await send_callback("Party: create - WIP")

    async def _handle_party_join_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        await send_callback("Party: join - WIP")

    async def _handle_party_leave_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        await send_callback("Party: leave - WIP")

    async def _handle_party_disband_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        await send_callback("Party: disband - WIP")

    async def _handle_party_invite_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        await send_callback("Party: invite - WIP")

    async def _handle_party_accept_invite_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        await send_callback("Party: accept - WIP")

    async def _handle_party_deny_invite_command(self, discord_user_id, command, args, message):
        send_callback = self._send_callback_factory(message.channel.id)
        await send_callback("Party: deny - WIP")

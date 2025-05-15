# main.py

import os
import json
import discord
from discord.ext import commands
import asyncio
import traceback
from typing import Dict, Any, Optional, List

# --- Импорты ---
from dotenv import load_dotenv # Импортируем функцию для загрузки .env
from bot.game.managers.game_manager import GameManager # Импорт GameManager

# --- 1) Загрузка переменных окружения из .env ---
# Вызываем это СРАЗУ после импортов, до любой попытки чтения os.getenv
load_dotenv()

# --- Отладочная печать (для проверки, загрузился ли токен из .env) ---
print(f"DEBUG: Value from os.getenv('DISCORD_TOKEN') AFTER load_dotenv(): {os.getenv('DISCORD_TOKEN')}")
# -------------------------------------------------------------------

# --- 2) Функция загрузки настроек из settings.json ---
def load_settings(file_path: str = 'settings.json') -> Dict[str, Any]:
    """
    Загружает настройки из JSON-файла.
    Если файла нет или он невалиден — возвращает пустой dict.
    """
    try:
        if os.path.exists(file_path):
            print(f"Loading settings from '{file_path}'...")
            with open(file_path, encoding='utf-8') as f:
                settings_data = json.load(f)
                print("Settings loaded successfully.")
                return settings_data
        else:
            print(f"Warning: settings file '{file_path}' not found, using empty settings.")
            return {}
    except json.JSONDecodeError:
         print(f"Error: Invalid JSON in settings file '{file_path}'. Using empty settings.")
         return {}
    except Exception as e:
        print(f"Error loading settings from '{file_path}': {e}")
        return {}

# --- 3) Чтение всех настроек (из .env И settings.json, с приоритетом для .env) ---
# Сначала загружаем settings.json
SETTINGS = load_settings()

# Теперь читаем переменные окружения и настройки, применяя приоритет
TOKEN = os.getenv('DISCORD_TOKEN') or SETTINGS.get('discord_token')
OPENAI_KEY = os.getenv('OPENAI_API_KEY') or SETTINGS.get('openai_api_key')
COMMAND_PREFIX = os.getenv('COMMAND_PREFIX') or SETTINGS.get('discord_command_prefix', '/') # Также можно читать префикс из env
DATABASE_PATH = os.getenv('DATABASE_PATH') or SETTINGS.get('database_path', 'game_state.db')

# Если OpenAI ключ есть — кладём его в секцию настроек (для GameManager, если он их ожидает в таком формате)
if OPENAI_KEY:
    # Убедимся, что 'openai_settings' существует перед добавлением ключа
    if 'openai_settings' not in SETTINGS:
        SETTINGS['openai_settings'] = {}
    SETTINGS['openai_settings']['api_key'] = OPENAI_KEY
    print("OpenAI API Key loaded.")

# --- Инициализация Discord-клиента ---
# Инициализируем после того, как определили COMMAND_PREFIX
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)
print(f"Discord bot initialized with prefix: '{COMMAND_PREFIX}'")

# GameManager будет глобальным
game_manager: Optional[GameManager] = None

# --- Главная асинхронная функция запуска ---
async def main():
    global game_manager

    # 4) Проверяем токен ПЕРЕД инициализацией GameManager (или сразу после, как вам удобнее, но до bot.start)
    # Важно: Проверка должна идти после того, как TOKEN УЖЕ ОПРЕДЕЛЕН из env или settings.json
    if not TOKEN:
        print("❌ FATAL: Discord token not provided (env DISCORD_TOKEN or settings.json). Cannot start bot.")
        # Не пытаемся запускать GameManager, если нет токена Discord
        # game_manager останется None
        return # Прекращаем выполнение main()

    # 5) Инстанцируем и подготавливаем GameManager
    # Передаем актуальные SETTINGS, которые теперь включают OpenAI Key, если он был найден
    game_manager = GameManager(
        discord_client=bot,
        settings=SETTINGS, # Передаем загруженные настройки
        db_path=DATABASE_PATH
    )
    print("GameManager instantiated. Running setup...")
    try:
        await game_manager.setup()
        print("GameManager: setup() успешно выполнен.")
    except Exception as e:
        print(f"❌ FATAL: GameManager.setup() failed: {e}")
        traceback.print_exc()
        await game_manager.shutdown() # Попытка корректного завершения при ошибке setup
        game_manager = None # Устанавливаем в None, чтобы finally не пытался сохранить/выключить снова
        return

    # 6) Запускаем бота
    print("Starting Discord bot...")
    try:
        await bot.start(TOKEN)
    except discord.errors.LoginFailure:
        # Это исключение ловится, если токен недействителен
        print("❌ FATAL: Invalid Discord token. Please check your DISCORD_TOKEN in the .env file and Discord Developer Portal.")
    except Exception as e:
        print(f"❌ FATAL: bot.start() error: {e}")
        traceback.print_exc()
    finally:
        # 7) При любом завершении bot.start() (кроме KeyboardInterrupt) — сохраняем состояние и выключаем GameManager
        # Этот блок выполнится и при успешном запуске (когда бот остановится), и при ошибке запуска.
        print("Application shutting down...")

        # Первым делом корректно закрываем Discord клиент
        if bot: # Проверяем, был ли бот инициализирован
            print("Closing Discord connection...")
            try:
                await bot.close() # <-- Добавлено для корректного закрытия aiohttp коннектора
                print("Discord connection closed.")
            except Exception as e:
                print(f"Error closing Discord connection: {e}")
                traceback.print_exc()


        # Затем выключаем GameManager (который внутри себя сохранит состояние)
        if game_manager: # Проверяем, был ли GameManager успешно инициализирован
            print("Shutting down GameManager...")
            try:
                 # Сохранение происходит ВНУТРИ shutdown(), поэтому save_game_state() не нужен здесь
                 await game_manager.shutdown()
                 print("GameManager: shutdown() выполнен.")
            except Exception as e:
                 print(f"Error during GameManager shutdown(): {e}")
                 traceback.print_exc()
        else:
            print("GameManager was not initialized, skipping shutdown.")


# --- События Discord ---
# События определяются ДО вызова asyncio.run(main())

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")
    # Загружаем состояние (если вдруг нужно повторно после on_ready,
    # но обычно setup() уже должен был это сделать при старте main)
    # Эту часть можно убрать, если load_game_state() уже вызывается в game_manager.setup()
    # или если вы не хотите перезагружать состояние после каждого переподключения.
    # if game_manager:
    #     try:
    #         print("Attempting to load game state on_ready...")
    #         await game_manager.load_game_state()
    #         print("GameManager: load_game_state() выполнен в on_ready.")
    #     except Exception as e:
    #         print(f"Error in load_game_state() in on_ready: {e}")
    #         traceback.print_exc()


@bot.event
async def on_message(message: discord.Message):
    """
    Обрабатывает входящие сообщения Discord, передавая их GameManager.
    GameManager/CommandRouter отвечает за проверку префикса, парсинг
    и маршрутизацию команды.
    """
    # Игнорируем ботов и свои сообщения
    if message.author.bot:
        return

    # Убедимся, что GameManager инициализирован перед обработкой сообщения
    if game_manager:
        # Логируем, что сообщение получено и передается в GameManager
        # GameManager сам определит, является ли это командой.
        print(f"Passing message from {message.author.name} ({message.author.id}) in channel {message.channel.id} to GameManager: '{message.content}'")
        try:
            # Вызываем правильный метод GameManager, передавая ВЕСЬ объект message
            # GameManager (через CommandRouter) теперь отвечает за:
            # 1. Проверку префикса
            # 2. Парсинг команды и аргументов
            # 3. Маршрутизацию к нужному обработчику
            await game_manager.handle_discord_message(message)

        except Exception as e:
            # Обработка ошибок, возникших при обработке сообщения внутри GameManager/Router
            print(f"Error handling message in GameManager for user {message.author.id}: {e}")
            traceback.print_exc()
            # Опционально: отправить сообщение об ошибке пользователю
            try:
                # Отправляем сообщение об ошибке в тот же канал, откуда пришла команда
                await message.channel.send(f"Произошла внутренняя ошибка при обработке вашего запроса.")
            except:
                pass # Игнорируем ошибки отправки сообщения об ошибке
    else:
        # Если GameManager неинициализирован, ответить пользователю
        # (Этот случай маловероятен после on_ready, но для безопасности)
        try:
            await message.channel.send("⚠️ Игровой движок еще загружается или недоступен. Пожалуйста, подождите.")
        except:
            pass

# --- Запуск всего приложения ---
# Запускаем главную асинхронную функцию main()
if __name__ == '__main__':
    print("Starting application...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted by user (KeyboardInterrupt), exiting.")
        # В случае KeyboardInterrupt, main() мог не дойти до finally блока,
        # но asyncio.run по идее должен обработать очистку асинхронных ресурсов.
        # Дополнительный вызов shutdown здесь может быть рискованным,
        # лучше полагаться на finally в main().
    print("Application finished.")
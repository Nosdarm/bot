# main.py
"""
Основной файл для запуска Discord-бота.
Этот файл теперь делегирует всю логику инициализации и запуска бота модулю bot.bot_core.
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
from bot.bot_core import run_bot # Импортируем новую функцию запуска

# --- Главная функция ---
# В main.py теперь остается только точка входа,
# которая вызывает функцию из bot_core.
async def main():
    """
    Асинхронная функция-обертка для запуска бота.
    """
    # run_bot() из bot_core.py теперь синхронная и сама обрабатывает asyncio.run()
    # Поэтому здесь нам не нужно делать await или asyncio.run
    # Вместо этого, если run_bot() должна быть вызвана асинхронно,
    # то и она должна быть async, и здесь мы бы её await-или.
    # Но по структуре run_bot() -> asyncio.run(start_bot()),
    # main() может быть либо пустой, либо вызывать синхронный run_bot().
    # Для простоты, if __name__ == '__main__' будет напрямую вызывать run_bot().
    print("main.py: Delegating to bot_core.run_bot()")
    # run_bot() теперь содержит цикл asyncio, поэтому здесь ее не нужно запускать в asyncio.run
    # Если бы run_bot была async, то: await run_bot()


# --- Запуск всего приложения ---
if __name__ == '__main__':
    print("main.py: Starting application...")
    # Поскольку run_bot() в bot_core.py теперь является синхронным вызывающим объектом,
    # который внутри себя использует asyncio.run(), мы просто вызываем его.
    run_bot()
    print("main.py: Application finished.")

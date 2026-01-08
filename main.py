import asyncio
import logging
import sys

# Показываем питону, где искать папку app
sys.path.append(".")

from app.bot import start_bot

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        print("Бот остановлен")
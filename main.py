import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram import F
from aiogram.types import Message
from aiogram.types import FSInputFile

import openai
import aiohttp
import os
import requests

from config import BOT_TOKEN, OPENAI_API_KEY, system_propmpt


logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

openai.api_key = OPENAI_API_KEY

MAX_DIALOG_LIMIT = 20
dialog_history = {}

TEMP_DIR = "/mnt/data/"
os.makedirs(TEMP_DIR, exist_ok=True)

def init_db():
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_modes (
            user_id INTEGER PRIMARY KEY,
            mode TEXT DEFAULT 'chat'
        )
    """)
    conn.commit()
    conn.close()

def get_user_mode(user_id):
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT mode FROM user_modes WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "chat"

def set_user_mode(user_id, mode):
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_modes (user_id, mode) 
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET mode=excluded.mode
    """, (user_id, mode))
    conn.commit()
    conn.close()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Это GPT-бот. Используйте команду /chat для текста или /image для генерации изображений.")

@dp.message(Command("image"))
async def cmd_image(message: types.Message):
    set_user_mode(message.from_user.id, "image")
    await message.answer("Режим обработки изображений активирован. Пожалуйста, отправьте следующее сообщение с описанием изображения.")

@dp.message(Command("chat"))
async def cmd_chat(message: types.Message):
    set_user_mode(message.from_user.id, "chat")
    await message.answer("Режим чата активирован. Просто пиши промпт.")

@dp.message(F.text)
async def handle_message(message: Message):
    user_mode = get_user_mode(message.from_user.id)
    if user_mode == "chat":
        await handle_chat_message(message)
    elif user_mode == "image":
        await handle_image_message(message)

async def handle_chat_message(message: Message):
    await message.answer("Генерирую ответ...")

    user_id = message.from_user.id
    if user_id not in dialog_history:
        dialog_history[user_id] = []

    dialog_history[user_id].append({"role": "user", "content": message.text})

    answer = await get_answer(message.text, user_id)
    dialog_history[user_id].append({"role": "assistant", "content": answer})

    await message.answer(answer)

    if len(dialog_history[user_id]) >= MAX_DIALOG_LIMIT:
        dialog_history[user_id].clear()
        await message.answer("История диалога сброшена, так как достигнут лимит сообщений.")

async def handle_image_message(message: Message):
    await message.answer("Генерирую изображение...")

    url = "https://api.openai.com/v1/images/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }
    data = {
        "model": "dall-e-3",
        "prompt": message.text,
        "n": 1,
        "size": "1024x1024"
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        image_url = response.json()["data"][0]["url"]
        
        user_id = message.from_user.id
        image_path = os.path.join(TEMP_DIR, f"generated_image_{user_id}.png")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as img_response:
                if img_response.status == 200:
                    with open(image_path, "wb") as f:
                        f.write(await img_response.read())

                    await message.answer_photo(FSInputFile(image_path))
                    os.remove(image_path)
                else:
                    await message.answer("Ошибка при загрузке изображения, попробуйте ещё раз.")
    else:
        await message.answer("Ошибка при генерации изображения, попробуйте ещё раз.")


async def get_answer(prompt_user: str, user_id: int):
    messages = [{"role": "system", "content": system_propmpt}] + dialog_history.get(user_id, []) + [{"role": "user", "content": prompt_user}]
    
    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages
    )

    return response.choices[0].message.content

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
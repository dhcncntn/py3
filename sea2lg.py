import asyncio
import aiohttp
import base64
import json
import os
from aiogram.client.default import DefaultBotProperties
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ParseMode
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.filters import Command

# === НАСТРОЙКИ ===
BOT_TOKEN = "7772734850:AAE7h2N9yZSaQv68u2EnpBH0J6yv7dbbvCw"
GEMINI_API_KEY = "AIzaSyBZfx8a3cx9oTLFLcdhceaOqGjwBWGuUDw"
PROXY_URL = "http://grib:work7315@45.140.211.222:50100"
DEFAULT_MODEL = "gemini-2.0-flash"
DATA_FILE = "saved_chats.json"

# === ИНИЦИАЛИЗАЦИЯ ===
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# === СОСТОЯНИЯ ===
class ChatStates(StatesGroup):
    normal = State()
    waiting_for_caption = State()
    waiting_for_chat_name = State()
    choosing_chat = State()
    deleting_chat = State()

# === ДАННЫЕ ===
user_data = {}
saved_chats = {}

def load_saved_chats():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            saved_chats.update(json.load(f))

def save_chats():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(saved_chats, f, ensure_ascii=False, indent=2)

load_saved_chats()

# === КНОПКИ ===
def get_main_keyboard():
    kb = [
        [KeyboardButton(text="🆕 Новый чат"), KeyboardButton(text="🛑 Завершить чат")],
        [KeyboardButton(text="📂 Выбрать чат"), KeyboardButton(text="🗑️ Удалить чат")],
        [KeyboardButton(text="🧠 Переключить модель")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_chat_choice_keyboard(user_id):
    chats = saved_chats.get(str(user_id), {})
    keyboard = [[KeyboardButton(text=name)] for name in sorted(chats.keys())]
    keyboard.append([KeyboardButton(text="⬅️ Назад")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

model_options = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    
   
]

# === ВСПОМОГАТЕЛЬНОЕ ===
def estimate_tokens(text):
    return len(text.split()) * 1.5

def trim_history(history, max_tokens=8000):
    total_tokens = 0
    trimmed = []
    for item in reversed(history):
        content = item["parts"][0].get("text", "") if item["parts"] else ""
        total_tokens += estimate_tokens(content)
        trimmed.insert(0, item)
        if total_tokens > max_tokens:
            trimmed = trimmed[1:]
    return trimmed

async def send_reply(chat_id: int, text: str):
    if not text:
        await bot.send_message(chat_id, "❗ Пустой ответ.")
    else:
        await bot.send_message(chat_id, text)
    await bot.send_message(chat_id, "✅ Ответ закончен.")

async def analyze(user_id: int, text: str = None, image_data: bytes = None):
    if user_id not in user_data:
        user_data[user_id] = {"history": [], "model": DEFAULT_MODEL}

    parts = []
    prompt = "Ты — умный и дружелюбный ассистент. Решай пошагово, если это задание."

    if image_data:
        parts.append({"text": prompt})
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(image_data).decode("utf-8")
            }
        })
        if text:
            parts.append({"text": text})
    elif text:
        parts.append({"text": prompt + "\n" + text})
    else:
        return "❗ Пустой запрос."

    user_data[user_id]["history"].append({"role": "user", "parts": parts})
    user_data[user_id]["history"] = trim_history(user_data[user_id]["history"])

    payload = {
        "contents": user_data[user_id]["history"],
        "generationConfig": {"maxOutputTokens": 2000, "temperature": 0.5}
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{user_data[user_id]['model']}:generateContent?key={GEMINI_API_KEY}",
                json=payload,
                proxy=PROXY_URL
            ) as resp:
                data = await resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                user_data[user_id]["history"].append({"role": "model", "parts": [{"text": text}]})
                return text
    except Exception as e:
        return f"⚠️ Ошибка: {e}"

# === ОБРАБОТЧИКИ ===
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_data[message.from_user.id] = {"history": [], "model": DEFAULT_MODEL}
    await message.answer("Привет! Отправь текст или фото.", reply_markup=get_main_keyboard())
    await state.set_state(ChatStates.normal)

@dp.message(F.text.startswith("🧠 Переключить модель"))
async def change_model(message: Message):
    current = user_data[message.from_user.id]["model"]
    idx = model_options.index(current)
    new_model = model_options[(idx + 1) % len(model_options)]
    user_data[message.from_user.id]["model"] = new_model
    await message.answer(f"Модель переключена: {new_model}", reply_markup=get_main_keyboard())

@dp.message(F.text == "🆕 Новый чат")
async def new_chat(message: Message, state: FSMContext):
    user_data[message.from_user.id]["history"] = []
    await message.answer("Начат новый чат.")

@dp.message(F.text == "🛑 Завершить чат")
async def end_chat(message: Message, state: FSMContext):
    await message.answer("Введите имя для сохранения чата:")
    await state.set_state(ChatStates.waiting_for_chat_name)

@dp.message(ChatStates.waiting_for_chat_name)
async def save_chat(message: Message, state: FSMContext):
    name = message.text.strip()
    user_id = str(message.from_user.id)
    saved_chats.setdefault(user_id, {})[name] = user_data[message.from_user.id]
    save_chats()
    await message.answer(f"Чат сохранён как <b>{name}</b>.", reply_markup=get_main_keyboard())
    await state.set_state(ChatStates.normal)

@dp.message(F.text == "📂 Выбрать чат")
async def choose_chat(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    if user_id not in saved_chats or not saved_chats[user_id]:
        await message.answer("Нет сохранённых чатов.")
    else:
        await message.answer("Выбери чат:", reply_markup=get_chat_choice_keyboard(user_id))
        await state.set_state(ChatStates.choosing_chat)

@dp.message(ChatStates.choosing_chat)
async def handle_chat_selection(message: Message, state: FSMContext):
    name = message.text.strip()
    if name == "⬅️ Назад":
        await message.answer("Меню", reply_markup=get_main_keyboard())
        await state.set_state(ChatStates.normal)
        return
    user_id = str(message.from_user.id)
    if name in saved_chats.get(user_id, {}):
        user_data[message.from_user.id] = saved_chats[user_id][name]
        await message.answer(f"Чат <b>{name}</b> выбран.", reply_markup=get_main_keyboard())
    else:
        await message.answer("Чат не найден.")
    await state.set_state(ChatStates.normal)

@dp.message(F.text == "🗑️ Удалить чат")
async def delete_chat_prompt(message: Message, state: FSMContext):
    await message.answer("Имя чата для удаления:")
    await state.set_state(ChatStates.deleting_chat)

@dp.message(ChatStates.deleting_chat)
async def delete_chat(message: Message, state: FSMContext):
    name = message.text.strip()
    user_id = str(message.from_user.id)
    if name in saved_chats.get(user_id, {}):
        del saved_chats[user_id][name]
        save_chats()
        await message.answer(f"Чат <b>{name}</b> удалён.")
    else:
        await message.answer("Чат не найден.")
    await state.set_state(ChatStates.normal)

@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as resp:
            image_data = await resp.read()
    await message.answer("Изображение получено. Обработка...")
    response = await analyze(message.from_user.id, image_data=image_data)
    await send_reply(message.chat.id, response)

@dp.message(ChatStates.normal)
async def handle_text(message: Message, state: FSMContext):
    text = message.text.strip()
    if text in ["🆕 Новый чат", "🛑 Завершить чат", "📂 Выбрать чат", "🗑️ Удалить чат"]:
        return
    await message.answer("Думаю...")
    response = await analyze(message.from_user.id, text=text)
    await send_reply(message.chat.id, response)

# === ЗАПУСК ===
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

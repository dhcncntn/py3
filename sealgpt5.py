import asyncio
import aiohttp
import base64
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Конфигурация
BOT_TOKEN = "7267745404:AAEjc5GNhonrXoPSbgRDn8gAGCae0V34wo4"
GEMINI_API_KEY = "AIzaSyBZfx8a3cx9oTLFLcdhceaOqGjwBWGuUDw"
PROXY_URL = "http://grib:work7315@45.140.211.222:50100"
MODEL_NAME = "gemini-1.5-flash"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

user_data = {}
MAX_HISTORY_TOKENS = 8000

class ChatStates(StatesGroup):
    normal = State()
    waiting_for_caption = State()

def estimate_tokens(text):
    return len(text.split()) * 1.5

def trim_history(history):
    total_tokens = 0
    trimmed = []
    for item in reversed(history):
        content = item["parts"][0].get("text", "") if item["parts"] else ""
        total_tokens += estimate_tokens(content)
        trimmed.insert(0, item)
        if total_tokens > MAX_HISTORY_TOKENS:
            trimmed = trimmed[1:]
    return trimmed

async def analyze_image(user_id: int, image_data: bytes = None, caption: str = None):
    if user_id not in user_data:
        user_data[user_id] = {"photos": [], "history": []}

    parts = []
    if image_data:
        prompt = "Проанализируй это изображение"
        if caption:
            prompt += f". Подпись: {caption}"
        parts.append({"text": prompt})
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(image_data).decode("utf-8")
            }
        })
        user_data[user_id]["photos"].append({"data": image_data, "caption": caption})
    elif caption:
        parts.append({"text": caption})
    else:
        return "❗ Пустой запрос. Пожалуйста, отправьте фото или текст."

    user_data[user_id]["history"].append({"role": "user", "parts": parts})
    user_data[user_id]["history"] = trim_history(user_data[user_id]["history"])

    payload = {
        "contents": user_data[user_id]["history"],
        "generationConfig": {
            "maxOutputTokens": 2000,
            "temperature": 0.7
        }
    }

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}",
                    json=payload,
                    proxy=PROXY_URL,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        response_text = data["candidates"][0]["content"]["parts"][0]["text"]
                        user_data[user_id]["history"].append({"role": "model", "parts": [{"text": response_text}]})
                        return response_text
                    elif response.status == 400:
                        return "⚠️ Превышено ограничение GPT. Нажмите /start для сброса сессии."
                    elif response.status == 429:
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        else:
                            return "⚠️ Слишком много запросов подряд. Подожди немного или нажми /start для перезапуска."
                    else:
                        return f"⚠️ Ошибка API (код {response.status}). Нажмите /start для перезапуска."
        except Exception:
            return "⚠️ Не удалось связаться с сервером. Попробуйте позже или нажмите /start."

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_data[message.from_user.id] = {"photos": [], "history": []}
    await message.answer(
        "🤖 <b>Фотоаналитик Gemini</b>\n"
        "Присылайте фото или текст — я всё проанализирую!\n\n"
        "Команды:\n/start — перезапуск\n/help — помощь\n/clear — очистка истории",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )
    await state.set_state(ChatStates.normal)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "📸 <b>Как использовать:</b>\n"
        "1. Отправьте фото — я его проанализирую\n"
        "2. Можно с подписью или без\n"
        "3. Можно задать текстовый вопрос\n"
        "4. Вопросы можно писать отдельно от фото\n\n"
        "⚙️ <b>Команды:</b>\n"
        "/start — перезапуск бота\n"
        "/clear — очистка истории\n"
        "/help — помощь"
    )
    await message.answer(help_text, parse_mode="HTML")

@dp.message(Command("clear"))
async def cmd_clear(message: types.Message, state: FSMContext):
    user_data[message.from_user.id] = {"photos": [], "history": []}
    await message.answer("🧹 История очищена. Можно присылать новые фото или тексты.")
    await state.set_state(ChatStates.normal)

@dp.message(F.photo, ChatStates.normal)
async def handle_photo(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as response:
            image_data = await response.read()

    user_data[message.from_user.id]["current_photo"] = image_data
    await message.answer("📝 Хотите добавить подпись к фото? Напишите её или отправьте любое сообщение для пропуска.")
    await state.set_state(ChatStates.waiting_for_caption)

@dp.message(F.text, ChatStates.waiting_for_caption)
async def handle_caption(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    image_data = user_data[user_id]["current_photo"]
    caption = message.text if message.text.lower() != "пропустить" else None

    await message.answer("🔍 Анализирую изображение...")
    response = await analyze_image(user_id, image_data=image_data, caption=caption)
    await message.answer(response)
    await state.set_state(ChatStates.normal)

@dp.message(F.text, ChatStates.normal)
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if not text:
        await message.answer("Пожалуйста, введите текст.")
        return

    await message.answer("💬 Анализирую текст...")
    response = await analyze_image(user_id, caption=text)
    await message.answer(response)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


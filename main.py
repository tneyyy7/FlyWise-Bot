import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from groq import Groq

# Включаем логирование
logging.basicConfig(level=logging.INFO)
load_dotenv("keys.env")

# Забираем ключи
TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_KEY")

# Настраиваем клиента Groq
client = Groq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- ПАМЯТЬ БОТА (СОСТОЯНИЯ) ---
class TripPlan(StatesGroup):
    waiting_for_budget = State()
    waiting_for_flight_selection = State()

# --- 1. ПАРСЕР (ВЫТЯГИВАЕТ ДАННЫЕ) ---
async def extract_info(text):
    prompt = f"Extract from '{text}': Origin IATA, Dest IATA, Date YYYY-MM-DD. Return ONLY 3 comma-separated values. Example: WAW, MXP, 2026-04-29. Today is March 12, 2026."
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
        )
        parts = chat_completion.choices[0].message.content.strip().replace("`", "").split(",")
        if len(parts) >= 3:
            return parts[0].strip().upper()[:3], parts[1].strip().upper()[:3], parts[2].strip()
        return "WAW", "MXP", "2026-04-29"
    except Exception as e:
        logging.error(f"Extract Error: {e}")
        return "WAW", "MXP", "2026-04-29"

# --- 2. ПРИВЕТСТВИЕ /start ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "🌍 **Welcome to FlyWise!**\n\n"
        "Your personal premium travel planner. I find the best routes, "
        "cozy hotels, and delicious local food tailored to your exact needs.\n\n"
        "Tell me where and when you want to go.\n"
        "💬 *Example: 'Warsaw to Tokyo on March 25'*"
    )
    await message.answer(welcome_text, parse_mode="Markdown")

# --- 3. ЛОВИМ ГОРОДА И СПРАШИВАЕМ БЮДЖЕТ ---
@dp.message(StateFilter(None))
async def handle_route(message: types.Message, state: FSMContext):
    status = await message.answer("🔍 *Analyzing destinations...*", parse_mode="Markdown")
    
    origin, dest, date = await extract_info(message.text)
    await state.update_data(origin=origin, dest=dest, date=date)
    await state.set_state(TripPlan.waiting_for_budget)
    
    await status.edit_text(
        f"🎯 **Destination locked:** {origin} ➡️ {dest} on {date}\n\n"
        f"💸 **What is your flight budget?** (e.g., '150 EUR', '$50', or 'cheapest possible')"
    )

# --- 4. ШАГ 1: ГЕНЕРИРУЕМ ТОЛЬКО БИЛЕТЫ И КНОПКИ ---
@dp.message(TripPlan.waiting_for_budget)
async def handle_budget(message: types.Message, state: FSMContext):
    budget = message.text
    status = await message.answer("✈️ *Hunting for the best flights...*", parse_mode="Markdown")
    
    user_data = await state.get_data()
    origin, dest, date = user_data.get('origin', 'WAW'), user_data.get('dest', 'MXP'), user_data.get('date', '2026-04-20')
    
    # Жесткий промпт: запрещаем ныть и просим только 2 рейса со временем
    flight_prompt = f"""
    Find 2 flight options from {origin} to {dest} on {date}. User's budget is {budget}.
    
    STRICT RULES:
    1. NO APOLOGIES, NO LONG EXPLANATIONS about budget difficulty. 
    2. If the budget is impossible, simply say: "No flights found for this budget. Here are the absolute cheapest options:"
    3. You MUST provide exact or estimated Departure and Arrival Times.
    4. Format exactly like this:
    ✈️ **Option 1: [Airline Name]**
    🕒 [Time] - [Time]
    💸 Price: [Price]
    
    START DIRECTLY WITH THE OPTIONS. Make it bright and attractive.
    """
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": flight_prompt}],
            model="llama-3.3-70b-versatile",
        )
        flight_response = chat_completion.choices[0].message.content
        
        # Создаем красивые кнопки
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛫 Choose Option 1", callback_data="flight_1")],
            [InlineKeyboardButton(text="🛫 Choose Option 2", callback_data="flight_2")]
        ])
        
        await status.edit_text(flight_response, parse_mode="Markdown", reply_markup=keyboard)
        await state.set_state(TripPlan.waiting_for_flight_selection)
        
    except Exception as e:
        logging.error(f"Flight Gen Error: {e}")
        await status.edit_text("❌ Connection error. Please try again.")

# --- 5. ШАГ 2: ОБРАБОТКА НАЖАТИЯ КНОПКИ (ССЫЛКА + ОТЕЛИ) ---
@dp.callback_query(F.data.startswith("flight_"))
async def process_flight_selection(callback: types.CallbackQuery, state: FSMContext):
    # Убираем "часики" с кнопки в Телеграме
    await callback.answer() 
    
    # Редактируем старое сообщение, убирая кнопки
    await callback.message.edit_reply_markup(reply_markup=None)
    
    status = await callback.message.answer("🎉 *Excellent choice! Preparing your booking links and local guide...*", parse_mode="Markdown")
    
    user_data = await state.get_data()
    origin, dest, date = user_data.get('origin', 'WAW'), user_data.get('dest', 'MXP'), user_data.get('date', '2026-04-20')
    
    # Очищаем память
    await state.clear()
    
    # Формируем ссылку на Google Flights
    google_flights_url = f"https://www.google.com/travel/flights?q=Flights%20from%20{origin}%20to%20{dest}%20on%20{date}"
    
    # Промпт для отелей и еды
    hotel_prompt = f"""
    The user just booked a flight to {dest}. Act as FlyWise and provide:
    1. HOTELS: 3 options (Budget, Mid-range, Luxury) with real names. 
    FORMAT LINK EXACTLY LIKE THIS: `[Search on Booking](https://www.booking.com/searchresults.html?ss=Hotel+Name+{dest})` (replace spaces in hotel name with +).
    2. DINING: 3 highly-rated local restaurants with their signature dishes.
    
    RULES: Use bold titles, NO markdown headers (#), use emojis, make it vibrant and welcoming.
    """
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": hotel_prompt}],
            model="llama-3.3-70b-versatile",
        )
        hotel_response = chat_completion.choices[0].message.content
        
        # Склеиваем ссылку на билет и ответ ИИ по отелям
        final_message = (
            f"✅ **Your flight is ready to be booked!**\n"
            f"👉 [Click here to book your tickets securely]({google_flights_url})\n\n"
            f"--- \n\n"
            f"{hotel_response}"
        )
        
        await status.edit_text(final_message, parse_mode="Markdown", disable_web_page_preview=True)
        
    except Exception as e:
        logging.error(f"Hotel Gen Error: {e}")
        await status.edit_text("❌ Error loading the guide. Your flight link is ready though!")

# --- ЗАПУСК ---
async def main():
    print("🚀 FlyWise is online with interactive buttons and smart links!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
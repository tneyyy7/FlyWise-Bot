import os
import asyncio
import json
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from groq import Groq

# --- 1. НАСТРОЙКИ ---
load_dotenv("keys.env")
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
dp = Dispatcher()
client = Groq(api_key=os.getenv("GROQ_KEY"))

# --- 2. СОСТОЯНИЯ ---
class TravelStates(StatesGroup):
    waiting_for_departure = State()
    waiting_for_airport_dep = State()
    waiting_for_destination = State()
    waiting_for_airport_dest = State()
    waiting_for_date = State()
    waiting_for_return_choice = State()
    waiting_for_return_date = State()
    waiting_for_budget = State()

# --- 3. ПОИСК АЭРОПОРТОВ ---
async def get_airports(city):
    prompt = f"List 3 major airports in {city}. Return ONLY a JSON list: {{'airports': [{{'name': '...', 'iata': '...'}}]}}"
    try:
        res = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}], 
            model="llama-3.3-70b-versatile", 
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content).get('airports', [])
    except: return []

# --- 4. ХЭНДЛЕРЫ ДИАЛОГА ---

# ПРИВЕТСТВИЕ (НИКОГДА НЕ МЕНЯТЬ)
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "🌟 <b>Добро пожаловать в FlyWise</b> 🌟\n\n"
        "Я помогу тебе спланировать поездку: найду билеты, подберу жилье и хорошие места, где можно поесть.\n\n"
        "✈️ <b>Напиши, из какого города ты вылетаешь?</b>"
    )
    await message.answer(welcome_text, parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_departure)

@dp.message(TravelStates.waiting_for_departure)
async def process_dep(message: types.Message, state: FSMContext):
    await state.update_data(dep_city=message.text)
    airports = await get_airports(message.text)
    if not airports:
        await message.answer("Не нашел аэропорты. Введи IATA код вручную (например, WAW):")
        await state.set_state(TravelStates.waiting_for_airport_dep)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"ad_{a['iata']}")] for a in airports])
        await message.answer(f"📍 Выбери аэропорт вылета в <b>{message.text}</b>:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("ad_"))
async def set_dep_iata(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("ad_", "")
    await state.update_data(dep_iata=iata)
    await callback.message.edit_text(f"🛫 Вылет из: <b>{iata}</b>", parse_mode="HTML")
    # КУДА ЛЕТИМ (НИКОГДА НЕ МЕНЯТЬ)
    await callback.message.answer("🌍 <b>Понял. А куда хочешь полететь?</b>\n(Напиши название города)", parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_destination)

@dp.message(TravelStates.waiting_for_destination)
async def process_dest(message: types.Message, state: FSMContext):
    await state.update_data(dest_city=message.text)
    airports = await get_airports(message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"ax_{a['iata']}")] for a in airports])
    await message.answer(f"📍 Выбери аэропорт прилета в <b>{message.text}</b>:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("ax_"))
async def set_dest_iata(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("ax_", "")
    await state.update_data(dest_iata=iata)
    await callback.message.edit_text(f"🛬 Назначение: <b>{iata}</b>", parse_mode="HTML")
    await callback.message.answer("📅 <b>Когда вылетаем?</b>\n(Например: 20 мая)", parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_date)

@dp.message(TravelStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    await state.update_data(dep_date=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, нужен обратный ✅", callback_data="r_yes")],
        [InlineKeyboardButton(text="Нет, в одну сторону ✈️", callback_data="r_no")]
    ])
    await message.answer("🔄 Добавляем обратный билет?", reply_markup=kb)

@dp.callback_query(F.data == "r_yes")
async def r_yes(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📅 <b>Когда летим обратно?</b>\n(Например: 30 мая)", parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_return_date)

@dp.callback_query(F.data == "r_no")
async def r_no(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(return_date=None)
    await callback.message.answer("💰 <b>Какой бюджет на билеты?</b>\n(Например: $300)", parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_return_date)
async def process_ret_date(message: types.Message, state: FSMContext):
    await state.update_data(return_date=message.text)
    await message.answer("💰 <b>Какой общий бюджет на билеты?</b>\n(Например: $500)", parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_budget)
async def process_final(message: types.Message, state: FSMContext):
    await state.update_data(budget=message.text)
    data = await state.get_data()
    await message.answer("💎 <b>Собираю лучшие варианты для тебя...</b>", parse_mode="HTML")
    
    ret_info = f"Обратно: {data['return_date']}" if data.get('return_date') else "В одну сторону"
    
    # ИТОГОВОЕ СООБЩЕНИЕ (СТРОГИЙ ПРОМПТ)
    prompt = (
        f"Find flight options from {data['dep_iata']} to {data['dest_iata']} on {data['dep_date']}. "
        f"{ret_info}. Budget: {data['budget']}. "
        "Strict Formatting Rules:\n"
        "1. Use ONLY HTML tags (<b>, <code>, <a>). ABSOLUTELY NO Markdown characters like ** or symbols like - at start of rows.\n"
        "2. Add travel emojis ✈️, 🏨, 🍴.\n"
        "3. Sections: ВАРИАНТЫ ПЕРЕЛЕТА, ОТЕЛИ, РЕСТОРАНЫ. Empty line between sections.\n"
        "4. Flights: 2 options. Include Airline, Price, Departure Time, and Flight Duration.\n"
        "5. Hotels: Exactly 3 tiers (Smart Budget, Value Comfort, Premium Luxury). Must include real names in <code>, price per night, and Booking.com link.\n"
        "6. Restaurants: Exactly 3 tiers (Бюджетный, Средний чек, Люкс). Must include real names in <code>, avg check per person, and TripAdvisor link.\n"
        "7. Use <a href='...'>[Забронировать]</a> for all links to keep it clean."
    )
    
    res = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.3-70b-versatile").choices[0].message.content

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Новый поиск", callback_data="restart")]])
    await message.answer(res, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    await state.clear()

@dp.callback_query(F.data == "restart")
async def restart(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Готов к новому путешествию! Напиши /start")

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
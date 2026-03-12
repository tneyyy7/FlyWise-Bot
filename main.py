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
    prompt = f"List 3 major airports in {city}. JSON: {{'airports': [{{'name': '...', 'iata': '...'}}]}}"
    try:
        res = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}], 
            model="llama-3.3-70b-versatile", 
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content).get('airports', [])
    except: return []

# --- 4. ХЭНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("✈️ <b>FlyWise Premium</b>\n\nWhere are you flying from?", parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_departure)

@dp.message(TravelStates.waiting_for_departure)
async def process_dep(message: types.Message, state: FSMContext):
    await state.update_data(dep_city=message.text)
    airports = await get_airports(message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"ad_{a['iata']}")] for a in airports])
    await message.answer(f"📍 Select airport in <b>{message.text}</b>:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("ad_"))
async def set_dep_iata(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("ad_", "")
    await state.update_data(dep_iata=iata)
    await callback.message.edit_text(f"🛫 Departure: <b>{iata}</b>", parse_mode="HTML")
    await callback.message.answer("🏙 Where to?")
    await state.set_state(TravelStates.waiting_for_destination)

@dp.message(TravelStates.waiting_for_destination)
async def process_dest(message: types.Message, state: FSMContext):
    await state.update_data(dest_city=message.text)
    airports = await get_airports(message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"ax_{a['iata']}")] for a in airports])
    await message.answer(f"📍 Select arrival airport in <b>{message.text}</b>:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("ax_"))
async def set_dest_iata(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("ax_", "")
    await state.update_data(dest_iata=iata)
    await callback.message.edit_text(f"🛬 Destination: <b>{iata}</b>", parse_mode="HTML")
    await callback.message.answer("📅 Departure date? (e.g. May 20)")
    await state.set_state(TravelStates.waiting_for_date)

@dp.message(TravelStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    await state.update_data(dep_date=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Return flight ✅", callback_data="r_yes")],
        [InlineKeyboardButton(text="One-way ✈️", callback_data="r_no")]
    ])
    await message.answer("🔄 Add a return ticket?", reply_markup=kb)

@dp.callback_query(F.data == "r_yes")
async def r_yes(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📅 Return date? (e.g. May 30)")
    await state.set_state(TravelStates.waiting_for_return_date)

@dp.callback_query(F.data == "r_no")
async def r_no(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(return_date=None)
    await callback.message.answer("💰 Flight budget (e.g. $200)?")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_return_date)
async def process_ret_date(message: types.Message, state: FSMContext):
    await state.update_data(return_date=message.text)
    await message.answer("💰 Flight budget (e.g. $400)?")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_budget)
async def process_final(message: types.Message, state: FSMContext):
    await state.update_data(budget=message.text)
    data = await state.get_data()
    await message.answer("💎 <b>Crafting your elite travel guide...</b>", parse_mode="HTML")
    
    ret_info = f"Return date: {data['return_date']}" if data.get('return_date') else "One-way"
    
    prompt = (
        f"Elite Travel Concierge Mode. Find flights from {data['dep_iata']} to {data['dest_iata']} on {data['dep_date']}. "
        f"{ret_info}. Budget: {data['budget']}. "
        "Strict Formatting Rules:\n"
        "1. Use ONLY HTML (<b>, <code>, <a>). NO Markdown symbols like ** or dots at start of lines.\n"
        "2. Use many travel emojis.\n"
        "3. Sections: FLIGHTS, HOTELS, DINING. Use empty lines between sections.\n"
        "4. Flights: Include Airline, REALISTIC total price, and Duration.\n"
        "5. Hotels: 3 tiers (Smart, Comfort, Luxury). Include PRICE PER NIGHT. Name in <code>.\n"
        "6. Dining: 3 tiers. Include AVG CHECK per person. Name in <code>.\n"
        "7. Hide long URLs inside <a href='...'>[Link]</a> tags."
    )
    
    res = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.3-70b-versatile").choices[0].message.content

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 New Search", callback_data="restart")]])
    await message.answer(res, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    await state.clear()

@dp.callback_query(F.data == "restart")
async def restart(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Ready for a new search! Type /start")

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
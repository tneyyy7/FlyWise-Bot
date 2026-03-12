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

# --- 1. SETTINGS ---
load_dotenv("keys.env")
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
dp = Dispatcher()
client = Groq(api_key=os.getenv("GROQ_KEY"))

# --- 2. STATES ---
class TravelStates(StatesGroup):
    waiting_for_departure = State()
    waiting_for_airport_dep = State()
    waiting_for_destination = State()
    waiting_for_airport_dest = State()
    waiting_for_date = State()
    waiting_for_return_choice = State()
    waiting_for_return_date = State()
    waiting_for_budget = State()

# --- 3. AIRPORT SEARCH ---
async def get_airports(city):
    prompt = f"List 3 major airports in {city}. JSON format: {{'airports': [{{'name': '...', 'iata': '...'}}]}}"
    try:
        res = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}], 
            model="llama-3.3-70b-versatile", 
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content).get('airports', [])
    except: return []

# --- 4. HANDLERS ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "🌟 <b>Welcome to FlyWise</b> 🌟\n\n"
        "I'll help you plan your trip: find tickets, hotels, and great places to eat.\n\n"
        "✈️ <b>Where are you flying from?</b>"
    )
    await message.answer(welcome_text, parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_departure)

@dp.message(TravelStates.waiting_for_departure)
async def process_dep(message: types.Message, state: FSMContext):
    await state.update_data(dep_city=message.text)
    airports = await get_airports(message.text)
    if not airports:
        await message.answer("Couldn't find airports. Enter IATA code manually (e.g., WAW):")
        await state.set_state(TravelStates.waiting_for_airport_dep)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"ad_{a['iata']}")] for a in airports])
        await message.answer(f"📍 Select departure airport in <b>{message.text}</b>:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("ad_"))
async def set_dep_iata(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("ad_", "")
    await state.update_data(dep_iata=iata)
    await callback.message.edit_text(f"🛫 Departure: <b>{iata}</b>", parse_mode="HTML")
    await callback.message.answer("🌍 <b>Got it. Where do you want to fly?</b>", parse_mode="HTML")
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
    await callback.message.answer("📅 <b>When are you leaving?</b>\n(e.g., May 20)", parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_date)

@dp.message(TravelStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    await state.update_data(dep_date=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Yes, return flight ✅", callback_data="r_yes")],
        [InlineKeyboardButton(text="No, one-way ✈️", callback_data="r_no")]
    ])
    await message.answer("🔄 Add a return ticket?", reply_markup=kb)

@dp.callback_query(F.data == "r_yes")
async def r_yes(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📅 <b>When are you flying back?</b>\n(e.g., May 30)", parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_return_date)

@dp.callback_query(F.data == "r_no")
async def r_no(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(return_date=None)
    await callback.message.answer("💰 <b>Flight budget (e.g., $300)?</b>", parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_return_date)
async def process_ret_date(message: types.Message, state: FSMContext):
    await state.update_data(return_date=message.text)
    await message.answer("💰 <b>Total flight budget (e.g., $500)?</b>", parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_budget)
async def process_final(message: types.Message, state: FSMContext):
    await state.update_data(budget=message.text)
    data = await state.get_data()
    await message.answer("💎 <b>Crafting your travel itinerary...</b>", parse_mode="HTML")
    
    ret_info = f"Return date: {data['return_date']}" if data.get('return_date') else "One-way"
    
    # FINAL PROMPT (VISUAL & LOGIC IMPROVEMENTS)
    prompt = (
        f"Create a travel guide from {data['dep_iata']} to {data['dest_iata']} on {data['dep_date']}. "
        f"{ret_info}. Budget: {data['budget']}. "
        "Strict Formatting Rules:\n"
        "1. Use ONLY HTML tags (<b>, <code>, <a>). NO Markdown stars (**).\n"
        "2. Add many emojis to make it colorful. ✈️🏨🍴🌅🏙️\n"
        "3. Sections: FLIGHT OPTIONS, HOTELS, RESTAURANTS. Use double empty lines between sections.\n"
        "4. Flights: 2 options. Include: Airline, Price, Departure Time, Arrival Time, and Duration.\n"
        "5. Hotels: 3 tiers (Smart Budget, Value Comfort, Premium Luxury). ONLY the hotel name must be in <code>. Include price/night and Booking link.\n"
        "6. Restaurants: 3 tiers (Smart Budget, Value Comfort, Premium Luxury). ONLY the restaurant name must be in <code>. Include avg check. "
        f"CRITICAL: All restaurant and hotel links must be for {data['dest_city']}.\n"
        "7. Format with spacing for easy reading."
    )
    
    res = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.3-70b-versatile").choices[0].message.content

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 New Search", callback_data="restart")]])
    await message.answer(res, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    await state.clear()

@dp.callback_query(F.data == "restart")
async def restart(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Ready for a new adventure! Type /start")
    await callback.answer()

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
import os
import asyncio
import json
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from groq import Groq
from geopy.geocoders import Nominatim

# --- 1. НАСТРОЙКИ ---
load_dotenv("keys.env")
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
dp = Dispatcher()
client = Groq(api_key=os.getenv("GROQ_KEY"))
geolocator = Nominatim(user_agent="flywise_bot")

# --- 2. СОСТОЯНИЯ (FSM) ---
class TravelStates(StatesGroup):
    waiting_for_departure = State()
    waiting_for_airport_dep = State()
    waiting_for_destination = State()
    waiting_for_airport_dest = State()
    waiting_for_date = State()
    waiting_for_return_choice = State()
    waiting_for_return_date = State()
    waiting_for_budget = State()

# --- 3. ФУНКЦИИ ПОМОЩНИКИ ---
async def get_airports(city):
    """Просим ИИ найти аэропорты в городе"""
    prompt = f"List major commercial airports in {city}. Return ONLY a JSON list of objects with 'name' and 'iata'. Example: [{{'name': 'Heathrow', 'iata': 'LHR'}}]. No other text."
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile",
        response_format={"type": "json_object"}
    )
    data = json.loads(chat_completion.choices[0].message.content)
    # Ищем ключ, так как ИИ может вернуть его под разными именами (airports, list и т.д.)
    for key in data:
        if isinstance(data[key], list):
            return data[key]
    return []

# --- 4. ПРИВЕТСТВИЕ И ЛОКАЦИЯ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Send My Location", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "🌍 **Welcome to FlyWise!**\n\nWhere are you flying from?\nClick the button below or type the city name.",
        parse_mode="Markdown",
        reply_markup=kb
    )
    await state.set_state(TravelStates.waiting_for_departure)

@dp.message(TravelStates.waiting_for_departure)
async def process_departure(message: types.Message, state: FSMContext):
    city_name = ""
    if message.location:
        location = geolocator.reverse(f"{message.location.latitude}, {message.location.longitude}")
        address = location.raw.get('address', {})
        city_name = address.get('city') or address.get('town') or address.get('village')
    else:
        city_name = message.text

    await state.update_data(dep_city=city_name)
    await message.answer(f"Searching for airports in {city_name}...", reply_markup=types.ReplyKeyboardRemove())
    
    airports = await get_airports(city_name)
    if not airports:
        await message.answer("I couldn't find specific airports. Please type your departure airport IATA code (e.g., WAW):")
        await state.set_state(TravelStates.waiting_for_airport_dep)
        return

    buttons = [[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"air_dep_{a['iata']}")] for a in airports]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Please select your departure airport:", reply_markup=keyboard)
    await state.set_state(TravelStates.waiting_for_airport_dep)

@dp.callback_query(F.data.startswith("air_dep_"))
async def select_dep_airport(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("air_dep_", "")
    await state.update_data(dep_iata=iata)
    await callback.message.edit_text(f"Departure airport set to: **{iata}**", parse_mode="Markdown")
    await callback.message.answer("Now, where do you want to go? (Type the city name)")
    await state.set_state(TravelStates.waiting_for_destination)

# --- 5. ПУНКТ НАЗНАЧЕНИЯ ---
@dp.message(TravelStates.waiting_for_destination)
async def process_destination(message: types.Message, state: FSMContext):
    city_name = message.text
    await state.update_data(dest_city=city_name)
    
    airports = await get_airports(city_name)
    if not airports:
        await message.answer(f"Please type the IATA code for {city_name} (e.g., LHR):")
        await state.set_state(TravelStates.waiting_for_airport_dest)
        return

    buttons = [[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"air_dest_{a['iata']}")] for a in airports]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(f"Select airport in {city_name}:", reply_markup=keyboard)
    await state.set_state(TravelStates.waiting_for_airport_dest)

@dp.callback_query(F.data.startswith("air_dest_"))
async def select_dest_airport(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("air_dest_", "")
    await state.update_data(dest_iata=iata)
    await callback.message.edit_text(f"Destination set to: **{iata}**", parse_mode="Markdown")
    await callback.message.answer("What is your departure date? (e.g., March 25)")
    await state.set_state(TravelStates.waiting_for_date)

# --- 6. ДАТЫ И ОБРАТНЫЙ БИЛЕТ ---
@dp.message(TravelStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    await state.update_data(dep_date=message.text)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Yes, please! ✅", callback_data="return_yes")],
        [InlineKeyboardButton(text="No, one-way only ✈️", callback_data="return_no")]
    ])
    await message.answer("Do you need a return flight?", reply_markup=kb)
    await state.set_state(TravelStates.waiting_for_return_choice)

@dp.callback_query(F.data == "return_yes")
async def return_yes(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Great! When do you want to fly back? (e.g., April 5)")
    await state.set_state(TravelStates.waiting_for_return_date)

@dp.callback_query(F.data == "return_no")
async def return_no(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(return_date=None)
    await callback.message.edit_text("Got it. One-way trip.")
    await callback.message.answer("What is your total budget for flights (e.g., $500)?")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_return_date)
async def process_return_date(message: types.Message, state: FSMContext):
    await state.update_data(return_date=message.text)
    await message.answer("What is your total budget for flights (e.g., $800)?")
    await state.set_state(TravelStates.waiting_for_budget)

# --- 7. ФИНАЛЬНЫЙ ПОИСК (Упрощенно для теста логики) ---
@dp.message(TravelStates.waiting_for_budget)
async def process_budget(message: types.Message, state: FSMContext):
    data = await state.get_data()
    # Тут будет вызов ИИ для поиска (как в прошлой версии), 
    # но теперь с учетом return_date, если она есть.
    summary = (
        f"✅ Trip Configured!\n"
        f"From: {data['dep_city']} ({data['dep_iata']})\n"
        f"To: {data['dest_city']} ({data['dest_iata']})\n"
        f"Departure: {data['dep_date']}\n"
        f"Return: {data.get('return_date') or 'One-way'}\n"
        f"Budget: {message.text}"
    )
    await message.answer(summary)
    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
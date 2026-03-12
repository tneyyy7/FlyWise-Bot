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
import requests

# --- 1. НАСТРОЙКИ ---
load_dotenv("keys.env")
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
dp = Dispatcher()
client = Groq(api_key=os.getenv("GROQ_KEY"))
geolocator = Nominatim(user_agent="flywise_bot")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

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
    waiting_for_extra_services = State()

# --- 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def get_airports(city):
    prompt = f"List major commercial airports in {city}. Return ONLY a JSON list of objects with 'name' and 'iata'. Example: [{{'name': 'Heathrow', 'iata': 'LHR'}}] "
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile",
        response_format={"type": "json_object"}
    )
    data = json.loads(chat_completion.choices[0].message.content)
    for key in data:
        if isinstance(data[key], list): return data[key]
    return []

def get_weather(city):
    if not WEATHER_API_KEY: return "Weather API key missing."
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
    res = requests.get(url).json()
    if res.get("cod") != 200: return "Weather data unavailable."
    temp = res["main"]["temp"]
    desc = res["weather"][0]["description"]
    return f"🌡 {temp}°C, {desc.capitalize()}"

# --- 4. ХЭНДЛЕРЫ ДИАЛОГА ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Send My Location", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("🌍 **Welcome to FlyWise!**\nWhere are you flying from?", parse_mode="Markdown", reply_markup=kb)
    await state.set_state(TravelStates.waiting_for_departure)

@dp.message(TravelStates.waiting_for_departure)
async def process_departure(message: types.Message, state: FSMContext):
    city = ""
    if message.location:
        loc = geolocator.reverse(f"{message.location.latitude}, {message.location.longitude}")
        city = loc.raw.get('address', {}).get('city') or loc.raw.get('address', {}).get('town')
    else: city = message.text
    await state.update_data(dep_city=city)
    airports = await get_airports(city)
    if not airports:
        await message.answer(f"Type IATA code for {city}:", reply_markup=types.ReplyKeyboardRemove())
        await state.set_state(TravelStates.waiting_for_airport_dep)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"air_dep_{a['iata']}")] for a in airports])
        await message.answer(f"Select airport in {city}:", reply_markup=kb)

@dp.callback_query(F.data.startswith("air_dep_"))
async def select_dep_airport(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("air_dep_", "")
    await state.update_data(dep_iata=iata)
    await callback.message.edit_text(f"Departure: **{iata}**", parse_mode="Markdown")
    await callback.message.answer("Where to? (City name)")
    await state.set_state(TravelStates.waiting_for_destination)

@dp.message(TravelStates.waiting_for_destination)
async def process_destination(message: types.Message, state: FSMContext):
    await state.update_data(dest_city=message.text)
    airports = await get_airports(message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"air_dest_{a['iata']}")] for a in airports])
    await message.answer(f"Select airport in {message.text}:", reply_markup=kb)
    await state.set_state(TravelStates.waiting_for_airport_dest)

@dp.callback_query(F.data.startswith("air_dest_"))
async def select_dest_airport(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("air_dest_", "")
    await state.update_data(dest_iata=iata)
    await callback.message.edit_text(f"Destination: **{iata}**", parse_mode="Markdown")
    await callback.message.answer("Departure date? (e.g. March 25)")
    await state.set_state(TravelStates.waiting_for_date)

@dp.message(TravelStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    await state.update_data(dep_date=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Yes, please! ✅", callback_data="ret_yes")],
        [InlineKeyboardButton(text="No, one-way ✈️", callback_data="ret_no")]
    ])
    await message.answer("Need a return flight?", reply_markup=kb)

@dp.callback_query(F.data == "ret_yes")
async def ret_yes(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Return date? (e.g. April 5)")
    await state.set_state(TravelStates.waiting_for_return_date)

@dp.callback_query(F.data == "ret_no")
async def ret_no(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(return_date=None)
    await callback.message.edit_text("One-way trip.")
    await callback.message.answer("Total budget for flights?")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_return_date)
async def process_return_date(message: types.Message, state: FSMContext):
    await state.update_data(return_date=message.text)
    await message.answer("Total budget for flights?")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_budget)
async def process_budget(message: types.Message, state: FSMContext):
    await state.update_data(budget=message.text)
    data = await state.get_data()
    
    await message.answer("⏳ **Searching for the best options...**", parse_mode="Markdown")
    
    # --- ИИ ПОИСК ---
    prompt = (
        f"Find 2 flight options from {data['dep_iata']} to {data['dest_iata']} on {data['dep_date']}. "
        f"Return: {data.get('return_date', 'One-way')}. Budget: {data['budget']}. "
        "Also suggest 2 hotels and 2 restaurants. Be concise, use emojis. No apologies."
    )
    response = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile"
    ).choices[0].message.content

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛅️ Get Weather", callback_data="get_weather")],
        [InlineKeyboardButton(text="📄 Export to PDF (Coming soon)", callback_data="get_pdf")],
        [InlineKeyboardButton(text="🔄 Start Over", callback_data="restart")]
    ])
    
    await message.answer(response, reply_markup=kb)
    # Мы не вызываем state.clear(), чтобы кнопки погоды и PDF могли достать данные!
    await state.set_state(TravelStates.waiting_for_extra_services)

@dp.callback_query(F.data == "get_weather")
async def show_weather(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    weather_info = get_weather(data['dest_city'])
    await callback.message.answer(f"🌤 **Current weather in {data['dest_city']}:**\n{weather_info}", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "restart")
async def restart(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Let's start again! Type /start")
    await callback.answer()

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
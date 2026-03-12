
import os
import asyncio
import json
import requests
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from groq import Groq
from fpdf import FPDF

# --- 1. НАСТРОЙКИ ---
load_dotenv("keys.env")
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
dp = Dispatcher()
client = Groq(api_key=os.getenv("GROQ_KEY"))
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

# --- 3. ФУНКЦИИ (Генерация PDF и Погода) ---
def create_pdf(content, filename="Travel_Itinerary.pdf"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    # Очищаем текст от эмодзи, так как стандартные шрифты PDF их не любят
    clean_text = content.encode('ascii', 'ignore').decode('ascii')
    pdf.multi_cell(0, 10, txt=clean_text)
    return pdf.output(dest='S')

def get_weather(city):
    if not WEATHER_API_KEY: return "Error: No API Key found in keys.env"
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
    try:
        res = requests.get(url).json()
        if res.get("cod") != 200: return f"Error: {res.get('message', 'Unknown error')}"
        return f"🌡 {res['main']['temp']}°C, {res['weather'][0]['description'].capitalize()}"
    except: return "Service unavailable"

async def get_airports(city):
    prompt = f"List major commercial airports in {city}. Return ONLY a JSON list of objects with 'name' and 'iata'. Example: [{{'name': 'Heathrow', 'iata': 'LHR'}}] "
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        data = json.loads(chat_completion.choices[0].message.content)
        for key in data:
            if isinstance(data[key], list): return data[key]
    except: return []
    return []

# --- 4. ЛОГИКА ДИАЛОГА ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🌍 **Welcome to FlyWise!**\n\nWhere are you flying from? (Enter city name)", parse_mode="Markdown")
    await state.set_state(TravelStates.waiting_for_departure)

@dp.message(TravelStates.waiting_for_departure)
async def process_departure(message: types.Message, state: FSMContext):
    await state.update_data(dep_city=message.text)
    airports = await get_airports(message.text)
    if not airports:
        await message.answer(f"IATA code for {message.text}?")
        await state.set_state(TravelStates.waiting_for_airport_dep)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"air_dep_{a['iata']}")] for a in airports])
        await message.answer(f"Select airport in {message.text}:", reply_markup=kb)

@dp.callback_query(F.data.startswith("air_dep_"))
async def select_dep_airport(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("air_dep_", "")
    await state.update_data(dep_iata=iata)
    await callback.message.edit_text(f"🛫 Departure: **{iata}**", parse_mode="Markdown")
    await callback.message.answer("Where to? (Enter city name)")
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
    await callback.message.edit_text(f"🛬 Destination: **{iata}**", parse_mode="Markdown")
    await callback.message.answer("Departure date? (e.g. March 25)")
    await state.set_state(TravelStates.waiting_for_date)

@dp.message(TravelStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    await state.update_data(dep_date=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Yes, return flight ✅", callback_data="ret_yes")],
        [InlineKeyboardButton(text="No, one-way ✈️", callback_data="ret_no")]
    ])
    await message.answer("Do you need a return ticket?", reply_markup=kb)

@dp.callback_query(F.data == "ret_yes")
async def ret_yes(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Return date? (e.g. April 5)")
    await state.set_state(TravelStates.waiting_for_return_date)

@dp.callback_query(F.data == "ret_no")
async def ret_no(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(return_date=None)
    await callback.message.edit_text("Total budget for flights?")
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
    await message.answer("💎 **FlyWise is crafting your perfect itinerary...**", parse_mode="Markdown")
    
    # --- УЛУЧШЕННЫЙ ПРОМПТ ---
    ret_info = f"Return date: {data['return_date']}" if data.get('return_date') else "One-way flight"
    prompt = (
        f"You are an elite travel concierge. Find 2 detailed flight options from {data['dep_iata']} to {data['dest_iata']} on {data['dep_date']}. "
        f"{ret_info}. Budget: {data['budget']}. "
        "For each option include: Airline, departure/arrival times, and a simulated booking link. "
        "Also suggest 2 luxury hotels and 2 top-rated restaurants with descriptions. "
        "Format beautifully with bold text and emojis. End with a wish for a good trip."
    )
    
    response = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile"
    ).choices[0].message.content

    await state.update_data(last_itinerary=response) # Сохраняем для PDF
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌤 Get Weather Forecast", callback_data="get_weather")],
        [InlineKeyboardButton(text="📥 Export PDF Itinerary", callback_data="get_pdf")],
        [InlineKeyboardButton(text="🔄 New Search", callback_data="restart")]
    ])
    await message.answer(response, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(TravelStates.waiting_for_extra_services)

@dp.callback_query(F.data == "get_weather")
async def show_weather(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    weather_info = get_weather(data['dest_city'])
    await callback.message.answer(f"🏙 **Weather in {data['dest_city']}:**\n{weather_info}", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "get_pdf")
async def send_pdf(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    itinerary = data.get('last_itinerary', "No itinerary found.")
    pdf_data = create_pdf(itinerary)
    
    document = BufferedInputFile(pdf_data, filename=f"FlyWise_{data['dest_city']}.pdf")
    await callback.message.answer_document(document, caption="📂 Here is your professional travel guide!")
    await callback.answer()

@dp.callback_query(F.data == "restart")
async def restart(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Let's plan a new trip! Type /start")
    await callback.answer()

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
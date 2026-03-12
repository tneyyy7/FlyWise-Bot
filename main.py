import os
import asyncio
import json
import requests
from datetime import datetime
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
    waiting_for_selection = State() # Выбор конкретного варианта
    waiting_for_pdf_options = State() # Что включить в PDF

# --- 3. ФУНКЦИИ (Погода и PDF) ---
def get_detailed_weather(city, travel_date):
    """Получаем прогноз на конкретные даты"""
    if not WEATHER_API_KEY: return "Weather API key missing."
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_API_KEY}&units=metric"
    try:
        data = requests.get(url).json()
        if data.get("cod") != "200": return "Weather data temporarily unavailable."
        
        forecast_text = f"📅 **Weather Forecast for {city}:**\n"
        daily_data = {}
        
        for entry in data['list']:
            date = entry['dt_txt'].split(' ')[0]
            temp = entry['main']['temp']
            if date not in daily_data:
                daily_data[date] = {'min': temp, 'max': temp, 'desc': entry['weather'][0]['description']}
            else:
                daily_data[date]['min'] = min(daily_data[date]['min'], temp)
                daily_data[date]['max'] = max(daily_data[date]['max'], temp)
        
        # Берем первые 3-4 дня для краткости
        for date, val in list(daily_data.items())[:4]:
            forecast_text += f"• {date}: `{val['min']}°C` - `{val['max']}°C` ({val['desc']})\n"
        return forecast_text
    except: return "Service busy. Try again later."

def generate_pdf_pro(data, include_options):
    """Генерация крутого PDF на основе выбранных пунктов"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "FlyWise Personal Travel Itinerary", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", size=12)
    # Очистка текста от спецсимволов для PDF
    text = f"Destination: {data.get('dest_city')}\nDates: {data.get('dep_date')} - {data.get('return_date') or 'One way'}\n\n"
    
    if 'flights' in include_options:
        text += f"--- FLIGHT DETAILS ---\n{data.get('selected_flight', 'Not selected')}\n\n"
    if 'hotels' in include_options:
        text += f"--- ACCOMMODATION & DINING ---\n{data.get('last_itinerary_raw', '')}\n"
        
    clean_text = text.encode('ascii', 'ignore').decode('ascii')
    pdf.multi_cell(0, 10, txt=clean_text)
    return pdf.output(dest='S')

async def fetch_airports(city):
    prompt = f"List major commercial airports in {city}. JSON format: {{'airports': [{{'name': '...', 'iata': '...'}}]}}"
    try:
        res = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.3-70b-versatile", response_format={"type": "json_object"})
        return json.loads(res.choices[0].message.content).get('airports', [])
    except: return []

# --- 4. ХЭНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🌍 **Welcome to FlyWise!**\n\nEnter your departure city:")
    await state.set_state(TravelStates.waiting_for_departure)

@dp.message(TravelStates.waiting_for_departure)
async def process_dep(message: types.Message, state: FSMContext):
    await state.update_data(dep_city=message.text)
    airports = await fetch_airports(message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"ad_{a['iata']}")] for a in airports])
    await message.answer(f"Select airport in {message.text}:", reply_markup=kb)

@dp.callback_query(F.data.startswith("ad_"))
async def set_dep_iata(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("ad_", "")
    await state.update_data(dep_iata=iata)
    await callback.message.edit_text(f"🛫 From: **{iata}**", parse_mode="Markdown")
    await callback.message.answer("Where are you heading to?")
    await state.set_state(TravelStates.waiting_for_destination)

@dp.message(TravelStates.waiting_for_destination)
async def process_dest(message: types.Message, state: FSMContext):
    await state.update_data(dest_city=message.text)
    airports = await fetch_airports(message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"ax_{a['iata']}")] for a in airports])
    await message.answer(f"Select airport in {message.text}:", reply_markup=kb)

@dp.callback_query(F.data.startswith("ax_"))
async def set_dest_iata(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("ax_", "")
    await state.update_data(dest_iata=iata)
    await callback.message.edit_text(f"🛬 To: **{iata}**", parse_mode="Markdown")
    await callback.message.answer("Departure date? (e.g. March 25)")
    await state.set_state(TravelStates.waiting_for_date)

@dp.message(TravelStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    await state.update_data(dep_date=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Return flight ✅", callback_data="r_yes")],
        [InlineKeyboardButton(text="One-way ✈️", callback_data="r_no")]
    ])
    await message.answer("Need a return ticket?", reply_markup=kb)

@dp.callback_query(F.data == "r_yes")
async def r_yes(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Return date? (e.g. April 5)")
    await state.set_state(TravelStates.waiting_for_return_date)

@dp.callback_query(F.data == "r_no")
async def r_no(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(return_date=None)
    await callback.message.answer("What is your total budget?")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_return_date)
async def process_ret_date(message: types.Message, state: FSMContext):
    await state.update_data(return_date=message.text)
    await message.answer("What is your total budget?")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_budget)
async def process_search(message: types.Message, state: FSMContext):
    await state.update_data(budget=message.text)
    data = await state.get_data()
    await message.answer("💎 **Generating Elite Travel Guide...**")
    
    prompt = (
        f"Act as a professional travel concierge. Source 2 flight options from {data['dep_iata']} to {data['dest_iata']} on {data['dep_date']}. "
        f"Return: {data.get('return_date', 'One-way')}. Budget: {data['budget']}. "
        "Structure: \n"
        "1. Flights (Include airline, exact times, and a Google Flights search link).\n"
        "2. Hotels (3 tiers: 'Smart Budget', 'Value Comfort', 'Premium Luxury'). "
        "Include the hotel name in `<code>Name</code>` for easy copy and a Booking.com search link.\n"
        "3. Restaurants (3 tiers as above). Include names in `<code>Name</code>` for easy copy.\n"
        "Use emojis, be professional and clear."
    )
    
    response = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.3-70b-versatile").choices[0].message.content
    await state.update_data(last_itinerary_raw=response)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛅️ Detailed Forecast", callback_data="view_weather")],
        [InlineKeyboardButton(text="📥 Custom PDF Export", callback_data="prep_pdf")],
        [InlineKeyboardButton(text="🔄 Reset", callback_data="restart")]
    ])
    await message.answer(response, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "view_weather")
async def show_weather_detailed(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    forecast = get_detailed_weather(data['dest_city'], data['dep_date'])
    await callback.message.answer(forecast, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "prep_pdf")
async def start_pdf_config(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Flights + Hotels + Restaurants", callback_data="pdf_full")],
        [InlineKeyboardButton(text="Only Hotels & Food", callback_data="pdf_no_flights")]
    ])
    await callback.message.answer("What would you like to include in your PDF?", reply_markup=kb)

@dp.callback_query(F.data.startswith("pdf_"))
async def finalize_pdf(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    options = ['hotels'] if 'no_flights' in callback.data else ['flights', 'hotels']
    pdf_bytes = generate_pdf_pro(data, options)
    
    doc = BufferedInputFile(pdf_bytes, filename=f"FlyWise_{data['dest_city']}.pdf")
    await callback.message.answer_document(doc, caption="💼 Your customized travel document is ready!")
    await callback.answer()

@dp.callback_query(F.data == "restart")
async def restart(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Ready for a new adventure? Type /start")

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
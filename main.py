import os
import asyncio
import json
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
    waiting_for_selection = State()

# --- 3. ФУНКЦИИ ---
def generate_custom_pdf(selected_data):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "FlyWise: Your Luxury Travel Itinerary", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=12)
    
    content = "YOUR TRIP DETAILS:\n\n"
    for key, value in selected_data.items():
        if value:
            content += f"--- {key.upper()} ---\n{value}\n\n"
    
    clean_text = content.encode('ascii', 'ignore').decode('ascii')
    pdf.multi_cell(0, 10, txt=clean_text)
    return pdf.output(dest='S')

async def get_airports(city):
    prompt = f"List major airports in {city}. JSON: {{'airports': [{{'name': '...', 'iata': '...'}}]}}"
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
    await message.answer("✈️ <b>Welcome to FlyWise Luxury Concierge.</b>\n\nWhere are you flying from?", parse_mode="HTML")
    await state.set_state(TravelStates.waiting_for_departure)

@dp.message(TravelStates.waiting_for_departure)
async def process_dep(message: types.Message, state: FSMContext):
    await state.update_data(dep_city=message.text)
    airports = await get_airports(message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"ad_{a['iata']}")] for a in airports])
    await message.answer(f"Select departure airport in {message.text}:", reply_markup=kb)

@dp.callback_query(F.data.startswith("ad_"))
async def set_dep_iata(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("ad_", "")
    await state.update_data(dep_iata=iata)
    await callback.message.edit_text(f"🛫 From: <b>{iata}</b>", parse_mode="HTML")
    await callback.message.answer("What is your destination city?")
    await state.set_state(TravelStates.waiting_for_destination)

@dp.message(TravelStates.waiting_for_destination)
async def process_dest(message: types.Message, state: FSMContext):
    await state.update_data(dest_city=message.text)
    airports = await get_airports(message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a['name']} ({a['iata']})", callback_data=f"ax_{a['iata']}")] for a in airports])
    await message.answer(f"Select arrival airport in {message.text}:", reply_markup=kb)

@dp.callback_query(F.data.startswith("ax_"))
async def set_dest_iata(callback: types.CallbackQuery, state: FSMContext):
    iata = callback.data.replace("ax_", "")
    await state.update_data(dest_iata=iata)
    await callback.message.edit_text(f"🛬 To: <b>{iata}</b>", parse_mode="HTML")
    await callback.message.answer("Departure date? (e.g. June 15)")
    await state.set_state(TravelStates.waiting_for_date)

@dp.message(TravelStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    await state.update_data(dep_date=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Yes, return flight ✅", callback_data="r_yes")],
        [InlineKeyboardButton(text="No, one-way ✈️", callback_data="r_no")]
    ])
    await message.answer("Do you need a return ticket?", reply_markup=kb)

@dp.callback_query(F.data == "r_yes")
async def r_yes(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Return date? (e.g. June 25)")
    await state.set_state(TravelStates.waiting_for_return_date)

@dp.callback_query(F.data == "r_no")
async def r_no(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(return_date=None)
    await callback.message.answer("Total budget for flights?")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_return_date)
async def process_ret_date(message: types.Message, state: FSMContext):
    await state.update_data(return_date=message.text)
    await message.answer("Total budget for flights?")
    await state.set_state(TravelStates.waiting_for_budget)

@dp.message(TravelStates.waiting_for_budget)
async def process_search(message: types.Message, state: FSMContext):
    await state.update_data(budget=message.text)
    data = await state.get_data()
    await message.answer("💎 <b>FlyWise is tailoring your elite experience...</b>", parse_mode="HTML")
    
    ret_info = f"Return date: {data['return_date']}" if data.get('return_date') else "One-way"
    prompt = (
        f"Travel Concierge. Find 2 flights from {data['dep_iata']} to {data['dest_iata']} on {data['dep_date']}. "
        f"{ret_info}. Budget: {data['budget']}. "
        "Strict HTML structure:\n\n"
        "<b>1. FLIGHT OPTIONS</b>\n"
        "• Option 1: [Airline] - [Price]. Times: [Time]. <a href='https://www.google.com/flights'>[Book]</a>\n"
        "• Option 2: [Airline] - [Price]. Times: [Time]. <a href='https://www.google.com/flights'>[Book]</a>\n\n"
        "<b>2. LUXURY STAYS</b>\n"
        "• Smart Budget: <code>[Hotel Name]</code>. <a href='https://www.booking.com'>[Link]</a>\n"
        "• Value Comfort: <code>[Hotel Name]</code>. <a href='https://www.booking.com'>[Link]</a>\n"
        "• Premium Luxury: <code>[Hotel Name]</code>. <a href='https://www.booking.com'>[Link]</a>\n\n"
        "<b>3. DINING</b>\n"
        "• 3 Tiers (Budget/Mid/Luxury). Use <code>[Name]</code> for names.\n\n"
        "Hide URLs, use bold tags, add spacing."
    )
    
    response = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.3-70b-versatile").choices[0].message.content
    await state.update_data(raw_res=response)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Add Flight 1 to PDF", callback_data="add_f1"), InlineKeyboardButton(text="✅ Add Flight 2 to PDF", callback_data="add_f2")],
        [InlineKeyboardButton(text="🏠 Include All Hotels", callback_data="add_h"), InlineKeyboardButton(text="🍴 Include All Food", callback_data="add_r")],
        [InlineKeyboardButton(text="📥 GENERATE PDF", callback_data="gen_pdf")],
        [InlineKeyboardButton(text="🔄 New Search", callback_data="restart")]
    ])
    
    await message.answer(response, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    await state.set_state(TravelStates.waiting_for_selection)

@dp.callback_query(F.data.startswith("add_"))
async def select_item(callback: types.CallbackQuery, state: FSMContext):
    tag = callback.data.replace("add_", "")
    data = await state.get_data()
    picks = data.get("picks", {})
    picks[tag] = True
    await state.update_data(picks=picks)
    await callback.answer(f"Added to your custom PDF list!")

@dp.callback_query(F.data == "gen_pdf")
async def final_pdf(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("picks"):
        await callback.answer("Select at least one option first!", show_alert=True)
        return
    
    # Собираем данные для PDF (упрощенная версия для примера)
    selected = {"Trip Summary": f"Destination: {data['dest_city']}\nFlight: {data['dep_iata']} -> {data['dest_iata']}"}
    pdf_file = generate_custom_pdf(selected)
    
    doc = BufferedInputFile(pdf_file, filename=f"FlyWise_{data['dest_city']}.pdf")
    await callback.message.answer_document(doc, caption="💼 Your bespoke travel guide is ready.")
    await callback.answer()

@dp.callback_query(F.data == "restart")
async def restart(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Type /start to begin.")

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
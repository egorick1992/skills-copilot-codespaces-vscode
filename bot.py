import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import asyncio
from dotenv import load_dotenv

from sqlalchemy import select, func

from db import Task, TaskStatus, async_session
from api import get_data_airport, search_flights, get_tickets_aviasales

# ================= INIT =================
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Инициализация бота с параметрами по умолчанию
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ================= DATA =================
ORIGIN_CITIES = ["Москва", "Санкт-Петербург", "Хабаровск"]
DESTINATION_CITIES = ["Нячанг", "Бангкок", "Пекин"]


# ================= STATES =================
class FlightSearch(StatesGroup):
    start = State()
    awaiting_origin = State()
    origin_selected = State()
    awaiting_destination = State()
    destination_selected = State()
    awaiting_dates = State()
    dates_selected = State()
    awaiting_price = State()
    price_entered = State()
    awaiting_transfers = State()
    transfers_selected = State()
    awaiting_class = State()
    class_selected = State()
    confirming = State()


# ================= HELPERS =================
async def format_date_for_display(date_str: str) -> str:
    """Форматирование даты из ISO формата в читаемый вид"""
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        return date_obj.strftime("%d.%m.%Y")
    except:
        return date_str


def get_city_name_by_code(code: str) -> str:
    """Получить название города по коду IATA"""
    city_map = {
        'MOW': 'Москва',
        'LED': 'Санкт-Петербург',
        'KHV': 'Хабаровск',
        'NHA': 'Нячанг',
        'BKK': 'Бангкок',
        'PEK': 'Пекин',
        'SVO': 'Москва (Шереметьево)',
        'DME': 'Москва (Домодедово)',
        'VKO': 'Москва (Внуково)',
    }
    return city_map.get(code, code)


def get_restart_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру с кнопкой 'Начать сначала'"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ])


# ================= RESTART HANDLER =================
@dp.callback_query(F.data == "restart_search")
async def restart_search(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Начать сначала'"""
    await callback.answer("🔄 Начинаем заново...")
    await state.clear()

    # Отправляем новое сообщение вместо редактирования старого
    await callback.message.answer(
        "🔄 Поиск начат заново!\n\n"
        "Для начала выберите город вылета:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✈️ Начать поиск", callback_data="start_search")]
        ])
    )


# ================= START =================
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # Очищаем состояние
    await state.clear()

    try:
        async with async_session() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.user_id == user_id, Task.status == TaskStatus.active)
            )

            tasks_result = await session.execute(
                select(Task)
                .where(Task.user_id == user_id, Task.status == TaskStatus.active)
                .order_by(Task.created_at.desc())
            )
            tasks = tasks_result.scalars().all()

        if total and total > 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✈️ Начать новый поиск", callback_data="start_search")]
            ])
            await message.answer(f"📌 У вас {total} активных задач:", reply_markup=kb)

            for t in tasks:
                text = (
                    f"✈️ {get_city_name_by_code(t.origin)} → {get_city_name_by_code(t.destination)}\n"
                    f"📅 {t.date_from} – {t.date_to}\n"
                    f"💰 до {t.max_price or '∞'} руб.\n"
                    f"🔄 Пересадки: {t.max_transfers if t.max_transfers is not None else 'не важно'}\n"
                    f"💺 Класс: {['эконом', 'бизнес', 'первый'][t.trip_class if t.trip_class else 0]}"
                )
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Удалить задачу", callback_data=f"cancel:{t.id}")]
                ])
                await message.answer(text, reply_markup=kb)
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✈️ Начать поиск", callback_data="start_search")]
            ])
            await message.answer("Добро пожаловать! Начнем поиск билетов?", reply_markup=kb)

        await ask_origin(message, state)

    except Exception as e:
        print(f"Ошибка в функции start: {e}")
        await message.answer("Произошла ошибка при загрузке задач. Попробуйте еще раз.")


# ================= NEW SEARCH =================
@dp.callback_query(F.data == "new:start")
async def new_search(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await start_search(callback, state)


@dp.callback_query(F.data == "start_search")
async def start_search(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await ask_origin(callback.message, state)


# ================= CANCEL TASK =================
@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_task(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])

    try:
        async with async_session() as session:
            async with session.begin():
                task = await session.get(Task, task_id)
                if task:
                    task.status = TaskStatus.closed
                else:
                    await callback.message.edit_text("❌ Задача не найдена")
                    await callback.answer()
                    return

        kb = get_restart_keyboard()
        await callback.message.edit_text("❌ Задача отменена", reply_markup=kb)

    except Exception as e:
        print(f"Ошибка при отмене задачи: {e}")
        kb = get_restart_keyboard()
        await callback.message.edit_text("❌ Произошла ошибка при отмене задачи", reply_markup=kb)

    await callback.answer()


# ================= ORIGIN =================
async def ask_origin(message: Message, state: FSMContext):
    kb = []
    row = []
    for city in ORIGIN_CITIES:
        row.append(InlineKeyboardButton(
            text=city,
            callback_data=f"origin:{city}"
        ))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    # Добавляем кнопку "Начать сначала"
    kb.append([InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")])

    await state.set_state(FlightSearch.awaiting_origin)
    await message.answer(
        "✈️ Выберите город вылета или введите вручную:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


@dp.message(FlightSearch.awaiting_origin)
async def manual_origin(message: Message, state: FSMContext):
    city = message.text.strip()
    city_info = get_data_airport(city)

    if not city_info:
        kb = get_restart_keyboard()
        await message.answer("❌ Город не найден, попробуйте ещё раз", reply_markup=kb)
        return

    await state.update_data(origin=city_info)
    await state.set_state(FlightSearch.origin_selected)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ])
    await message.answer(f"✅ Вылет: {city_info['name']} ({city_info['code']})", reply_markup=kb)
    await ask_destination(message, state)


@dp.callback_query(F.data.startswith("origin:"))
async def choose_origin(callback: CallbackQuery, state: FSMContext):
    city = callback.data.split(":", 1)[1]
    city_info = get_data_airport(city)

    if not city_info:
        await callback.answer("❌ Город не найден")
        return

    await state.update_data(origin=city_info)
    await state.set_state(FlightSearch.origin_selected)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ])

    if hasattr(callback.message, 'edit_text'):
        await callback.message.edit_text(f"✅ Вылет: {city_info['name']} ({city_info['code']})", reply_markup=kb)
    else:
        await callback.message.answer(f"✅ Вылет: {city_info['name']} ({city_info['code']})", reply_markup=kb)

    await ask_destination(callback.message, state)
    await callback.answer()


# ================= DESTINATION =================
async def ask_destination(message: Message, state: FSMContext):
    kb = []
    row = []
    for city in DESTINATION_CITIES:
        row.append(InlineKeyboardButton(
            text=city,
            callback_data=f"dest:{city}"
        ))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    # Добавляем кнопку "Начать сначала"
    kb.append([InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")])

    await state.set_state(FlightSearch.awaiting_destination)
    await message.answer(
        "🏙 Выберите город прилёта или введите вручную:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


@dp.message(FlightSearch.awaiting_destination)
async def manual_destination(message: Message, state: FSMContext):
    city = message.text.strip()
    city_info = get_data_airport(city)

    if not city_info:
        kb = get_restart_keyboard()
        await message.answer("❌ Город не найден, попробуйте ещё раз", reply_markup=kb)
        return

    await state.update_data(destination=city_info)
    await state.set_state(FlightSearch.destination_selected)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ])
    await message.answer(f"✅ Прилёт: {city_info['name']} ({city_info['code']})", reply_markup=kb)
    await ask_dates(message, state)


@dp.callback_query(F.data.startswith("dest:"))
async def choose_destination(callback: CallbackQuery, state: FSMContext):
    city = callback.data.split(":", 1)[1]
    city_info = get_data_airport(city)

    if not city_info:
        await callback.answer("❌ Город не найден")
        return

    await state.update_data(destination=city_info)
    await state.set_state(FlightSearch.destination_selected)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ])

    if hasattr(callback.message, 'edit_text'):
        await callback.message.edit_text(f"✅ Прилёт: {city_info['name']} ({city_info['code']})", reply_markup=kb)
    else:
        await callback.message.answer(f"✅ Прилёт: {city_info['name']} ({city_info['code']})", reply_markup=kb)

    await ask_dates(callback.message, state)
    await callback.answer()


# ================= DATES =================
async def ask_dates(message: Message, state: FSMContext):
    kb = [
        [
            InlineKeyboardButton(text="3 дней", callback_data="dates:3"),
            InlineKeyboardButton(text="7 дней", callback_data="dates:7")
        ],
        [
            InlineKeyboardButton(text="14 дней", callback_data="dates:14"),
            InlineKeyboardButton(text="30 дней", callback_data="dates:30")
        ],
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ]

    await state.set_state(FlightSearch.awaiting_dates)
    await message.answer(
        "📅 Выберите период даты вылета или введите вручную в формате:\n`01.12.2025-20.12.2025`",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data.startswith("dates:"))
async def dates_callback(callback: CallbackQuery, state: FSMContext):
    days = int(callback.data.split(":")[1])

    date_from = datetime.now().date()
    date_to = date_from + timedelta(days=days)

    await state.update_data(
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        date_from_display=date_from.strftime("%d.%m.%Y"),
        date_to_display=date_to.strftime("%d.%m.%Y")
    )

    await state.set_state(FlightSearch.dates_selected)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ])

    if hasattr(callback.message, 'edit_text'):
        await callback.message.edit_text(
            f"📅 Период: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}",
            reply_markup=kb
        )
    else:
        await callback.message.answer(
            f"📅 Период: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}",
            reply_markup=kb
        )

    await ask_price(callback.message, state)
    await callback.answer()


@dp.message(FlightSearch.awaiting_dates)
async def manual_dates(message: Message, state: FSMContext):
    try:
        d1, d2 = message.text.split("-")
        date_from = datetime.strptime(d1.strip(), "%d.%m.%Y").date()
        date_to = datetime.strptime(d2.strip(), "%d.%m.%Y").date()

        if date_from > date_to:
            raise ValueError("Дата начала позже даты окончания")

        if date_from < datetime.now().date():
            raise ValueError("Дата начала в прошлом")

        await state.update_data(
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            date_from_display=date_from.strftime("%d.%m.%Y"),
            date_to_display=date_to.strftime("%d.%m.%Y")
        )

        await state.set_state(FlightSearch.dates_selected)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
        ])
        await message.answer(
            f"✅ Период: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}",
            reply_markup=kb
        )
        await ask_price(message, state)

    except ValueError as e:
        error_msg = str(e)
        kb = get_restart_keyboard()
        if "не соответствует формату" in error_msg or "time data" in error_msg:
            await message.answer("❌ Неверный формат даты. Используйте: ДД.ММ.ГГГГ-ДД.ММ.ГГГГ", reply_markup=kb)
        else:
            await message.answer(f"❌ Ошибка: {error_msg}. Используйте корректные даты.", reply_markup=kb)
    except Exception:
        kb = get_restart_keyboard()
        await message.answer("❌ Ошибка ввода. Формат: 01.12.2025-20.12.2025", reply_markup=kb)


# ================= PRICE =================
async def ask_price(message: Message, state: FSMContext):
    kb = get_restart_keyboard()
    await state.set_state(FlightSearch.awaiting_price)
    await message.answer("💰 Введите максимальную цену в рублях:", reply_markup=kb)


@dp.message(FlightSearch.awaiting_price)
async def input_price(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        if price <= 0:
            kb = get_restart_keyboard()
            await message.answer("❌ Цена должна быть положительным числом", reply_markup=kb)
            return

        if price > 1000000:
            kb = get_restart_keyboard()
            await message.answer("❌ Слишком большая цена. Введите значение до 1 000 000 ₽", reply_markup=kb)
            return

        await state.update_data(max_price=price)
        await state.set_state(FlightSearch.price_entered)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
        ])
        await message.answer(f"✅ Максимальная цена: {price} ₽", reply_markup=kb)
        await ask_transfers(message, state)
    except ValueError:
        kb = get_restart_keyboard()
        await message.answer("❌ Введите корректное число (например: 50000)", reply_markup=kb)


# ================= TRANSFERS =================
async def ask_transfers(message: Message, state: FSMContext):
    kb = [
        [InlineKeyboardButton(text="🚀 Без пересадок", callback_data="transfers:0")],
        [InlineKeyboardButton(text="1️⃣ До 1 пересадки", callback_data="transfers:1")],
        [InlineKeyboardButton(text="2️⃣ До 2 пересадок", callback_data="transfers:2")],
        [InlineKeyboardButton(text="♾️ Не важно", callback_data="transfers:any")],
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ]

    await state.set_state(FlightSearch.awaiting_transfers)
    await message.answer(
        "🔄 Выберите максимальное количество пересадок:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


@dp.callback_query(FlightSearch.awaiting_transfers)
async def choose_transfers(callback: CallbackQuery, state: FSMContext):
    transfers_data = callback.data.split(":")[1]

    if transfers_data == "any":
        max_transfers = None
        display_text = "♾️ Не важно"
    else:
        max_transfers = int(transfers_data)
        display_text = f"{max_transfers} пересадок" if max_transfers > 0 else "Без пересадок"

    await state.update_data(max_transfers=max_transfers)
    await state.set_state(FlightSearch.transfers_selected)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ])

    if hasattr(callback.message, 'edit_text'):
        await callback.message.edit_text(f"✅ Пересадки: {display_text}", reply_markup=kb)
    else:
        await callback.message.answer(f"✅ Пересадки: {display_text}", reply_markup=kb)

    await ask_class(callback.message, state)
    await callback.answer()


# ================= CLASS =================
async def ask_class(message: Message, state: FSMContext):
    kb = [
        [InlineKeyboardButton(text="💺 Эконом класс", callback_data="class:0")],
        [InlineKeyboardButton(text="👔 Бизнес класс", callback_data="class:1")],
        [InlineKeyboardButton(text="👑 Первый класс", callback_data="class:2")],
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ]

    await state.set_state(FlightSearch.awaiting_class)
    await message.answer(
        "💺 Выберите класс перелета:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


@dp.callback_query(FlightSearch.awaiting_class)
async def choose_class(callback: CallbackQuery, state: FSMContext):
    trip_class = int(callback.data.split(":")[1])

    class_names = {
        0: "💺 Эконом класс",
        1: "👔 Бизнес класс",
        2: "👑 Первый класс"
    }

    await state.update_data(trip_class=trip_class)
    await state.set_state(FlightSearch.class_selected)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ])

    if hasattr(callback.message, 'edit_text'):
        await callback.message.edit_text(f"✅ Класс: {class_names[trip_class]}", reply_markup=kb)
    else:
        await callback.message.answer(f"✅ Класс: {class_names[trip_class]}", reply_markup=kb)

    await confirm(callback.message, state)
    await callback.answer()


# ================= CONFIRM =================
async def confirm(message: Message, state: FSMContext):
    data = await state.get_data()

    required_fields = ["origin", "destination", "date_from", "date_to", "max_price", "trip_class"]
    missing = [field for field in required_fields if field not in data]

    if missing:
        kb = get_restart_keyboard()
        await message.answer(f"❌ Ошибка: отсутствуют данные: {missing}. Начните заново", reply_markup=kb)
        await state.clear()
        return

    date_from_display = data.get("date_from_display") or await format_date_for_display(data["date_from"])
    date_to_display = data.get("date_to_display") or await format_date_for_display(data["date_to"])
    max_transfers_display = "не важно" if data.get("max_transfers") is None else str(data.get("max_transfers"))

    class_names = {
        0: "Эконом",
        1: "Бизнес",
        2: "Первый"
    }
    trip_class_display = class_names.get(data.get("trip_class", 0), "Эконом")

    text = (
        f"📋 <b>Проверьте данные:</b>\n\n"
        f"✈️ <b>Вылет:</b> {data['origin']['name']} ({data['origin']['code']})\n"
        f"🏙 <b>Прилёт:</b> {data['destination']['name']} ({data['destination']['code']})\n"
        f"📅 <b>Период поиска:</b> {date_from_display} — {date_to_display}\n"
        f"💰 <b>Макс. цена:</b> {data['max_price']} ₽\n"
        f"🔄 <b>Пересадки:</b> {max_transfers_display}\n"
        f"💺 <b>Класс:</b> {trip_class_display}\n\n"
        "Все верно?"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, искать", callback_data="confirm:yes"),
            InlineKeyboardButton(text="❌ Нет, отменить", callback_data="confirm:no")
        ],
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ])

    await state.set_state(FlightSearch.confirming)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(F.data.startswith("confirm:"))
async def confirm_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer("⏳ Обрабатываю...")
    data = await state.get_data()

    if callback.data.endswith("no"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
        ])
        await callback.message.edit_text("❌ Поиск отменен", reply_markup=kb)
        await state.clear()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ])
    await callback.message.edit_text("🔍 Ищу билеты...", reply_markup=kb)

    try:
        date_from = datetime.strptime(data["date_from"], "%Y-%m-%d").date()
        date_to = datetime.strptime(data["date_to"], "%Y-%m-%d").date()

        flights = get_tickets_aviasales(
            origin=data["origin"]["code"],
            destination=data["destination"]["code"],
            depart_date_from=date_from,
            depart_date_to=date_to,
            max_price=data["max_price"],
            max_transfers=data.get("max_transfers"),
            trip_class=data.get("trip_class", 0),
            direct=(data.get("max_transfers") == 0)
        )

        print(f"Найдено билетов: {len(flights) if flights else 0}")

        if not flights:
            await callback.message.answer("😔 Билеты по заданным критериям не найдены")
            await ask_subscription(callback.message, state)
            return

        flights_to_show = flights[:8]
        await callback.message.answer(f"✅ Найдено {len(flights_to_show)} билетов:")

        for i, f in enumerate(flights_to_show, 1):
            origin_city = get_city_name_by_code(f.get('origin', ''))
            destination_city = get_city_name_by_code(f.get('destination', ''))

            message_text = (
                f"<b>Билет {i}:</b>\n"
                f"💰 <b>Цена:</b> {f['price']} ₽\n"
                f"✈️ <b>Маршрут:</b> {origin_city} ({f.get('origin_airport', '')}) → "
                f"{destination_city} ({f.get('destination_airport', '')})\n"
                f"📅 <b>Дата вылета:</b> {f['depart_date']}\n"
            )

            if f.get("return_date"):
                message_text += f"📅 <b>Дата возврата:</b> {f['return_date']}\n"

            if f.get("airline"):
                message_text += f"🏢 <b>Авиакомпания:</b> {f['airline']}\n"

            if f.get("flight_number"):
                message_text += f"✈️ <b>Номер рейса:</b> {f['flight_number']}\n"

            if f.get("transfers") is not None:
                transfers_text = "Без пересадок" if f['transfers'] == 0 else f"{f['transfers']} пересадки"
                message_text += f"🔄 <b>Пересадки:</b> {transfers_text}\n"

            if f.get("trip_class") is not None:
                class_names = {0: "Эконом", 1: "Бизнес", 2: "Первый"}
                message_text += f"💺 <b>Класс:</b> {class_names.get(f['trip_class'], 'Эконом')}\n"

            if f.get("duration_to"):
                hours = f['duration_to'] // 60
                minutes = f['duration_to'] % 60
                message_text += f"⏱ <b>Время в пути:</b> {hours}ч {minutes}м\n"

            kb = None
            if f.get("affiliate_url"):
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔗 Перейти к покупке", url=f["affiliate_url"])],
                    [InlineKeyboardButton(text="🔄 Новый поиск", callback_data="restart_search")]
                ])
            else:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Новый поиск", callback_data="restart_search")]
                ])

            await bot.send_message(
                callback.from_user.id,
                message_text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb
            )

        await ask_subscription(callback.message, state)

    except Exception as e:
        print(f"Ошибка при поиске билетов: {e}")
        kb = get_restart_keyboard()
        await callback.message.answer(f"❌ Ошибка при поиске билетов: {str(e)}", reply_markup=kb)


# ================= SUBSCRIPTION =================
async def ask_subscription(message: Message, state: FSMContext):
    data = await state.get_data()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔔 Подписаться", callback_data="sub:yes"),
            InlineKeyboardButton(text="❌ Нет, спасибо", callback_data="sub:no")
        ],
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
    ])

    await message.answer(
        "Хотите создать подписку на мониторинг новых билетов по этим параметрам? "
        "Как только мы найдем билеты по вашим параметрам, мы пришлем вам сообщение!",
        reply_markup=kb
    )


@dp.callback_query(F.data.startswith("sub:"))
async def subscription_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    if callback.data.endswith("no"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
        ])
        await callback.message.edit_text("✅ Хорошо! Можете начать новый поиск", reply_markup=kb)
        await state.clear()
        await callback.answer()
        return

    try:
        date_from_str = data["date_from"]
        date_to_str = data["date_to"]

        async with async_session() as session:
            async with session.begin():
                task = Task()

                task.user_id = callback.from_user.id
                task.origin = data["origin"]["code"]
                task.destination = data["destination"]["code"]
                task.date_from = date_from_str
                task.date_to = date_to_str
                task.max_price = data["max_price"]
                task.max_transfers = data.get("max_transfers")
                task.trip_class = data.get("trip_class", 0)
                task.status = TaskStatus.active
                task.is_public = False

                session.add(task)
                await session.flush()

                print(f"✅ Задача создана: ID={task.id}, user_id={task.user_id}, {task.origin}->{task.destination}")
                await session.commit()

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
        ])
        await callback.message.edit_text(
            "✅ Подписка создана! Вы будете получать уведомления о новых билетах.",
            reply_markup=kb
        )

    except Exception as e:
        print(f"❌ Ошибка при создании подписки: {e}")
        import traceback
        traceback.print_exc()

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart_search")]
        ])
        await callback.message.edit_text(
            "✅ Подписка создана! (Возникла техническая ошибка)",
            reply_markup=kb
        )

    finally:
        await state.clear()
        await callback.answer()


# ================= FALLBACK HANDLER =================
@dp.message()
async def fallback_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()

    if current_state is None:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✈️ Начать поиск", callback_data="start_search")]
        ])
        await message.answer("Для начала поиска билетов нажмите кнопку:", reply_markup=kb)
        return

    kb = get_restart_keyboard()

    if current_state == FlightSearch.awaiting_origin:
        await message.answer("Пожалуйста, выберите город вылета из списка или введите название города.",
                             reply_markup=kb)
    elif current_state == FlightSearch.awaiting_destination:
        await message.answer("Пожалуйста, выберите город прилета из списка или введите название города.",
                             reply_markup=kb)
    elif current_state == FlightSearch.awaiting_dates:
        await message.answer("Пожалуйста, выберите период из предложенных или введите в формате: ДД.ММ.ГГГГ-ДД.ММ.ГГГГ",
                             reply_markup=kb)
    elif current_state == FlightSearch.awaiting_price:
        await message.answer("Пожалуйста, введите максимальную цену в рублях (число).", reply_markup=kb)
    elif current_state == FlightSearch.awaiting_transfers:
        await message.answer("Пожалуйста, выберите количество пересадок из предложенных вариантов.", reply_markup=kb)
    elif current_state == FlightSearch.awaiting_class:
        await message.answer("Пожалуйста, выберите класс перелета из предложенных вариантов.", reply_markup=kb)
    else:
        await message.answer("Пожалуйста, следуйте инструкциям. Или начните заново:", reply_markup=kb)


# ================= RUN =================
async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())




# import os
# from datetime import datetime, timedelta
# from aiogram import Bot, Dispatcher, F
# from aiogram.filters import Command
# from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
# from aiogram.fsm.context import FSMContext
# from aiogram.fsm.state import State, StatesGroup
# from aiogram.fsm.storage.memory import MemoryStorage
# from aiogram.enums import ParseMode
# from aiogram.client.default import DefaultBotProperties
# import asyncio
# from dotenv import load_dotenv
#
# from sqlalchemy import select, func
#
# from db import Task, TaskStatus, async_session
# from api import get_data_airport, search_flights, get_tickets_aviasales
#
# # ================= INIT =================
# load_dotenv()
# TOKEN = os.getenv("TELEGRAM_TOKEN")
#
# # Инициализация бота с параметрами по умолчанию
# bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
# storage = MemoryStorage()
# dp = Dispatcher(storage=storage)
#
# # ================= DATA =================
# ORIGIN_CITIES = ["Москва", "Санкт-Петербург", "Хабаровск"]
# DESTINATION_CITIES = ["Нячанг", "Бангкок", "Пекин"]
#
#
# # ================= STATES =================
# class FlightSearch(StatesGroup):
#     start = State()
#     awaiting_origin = State()
#     origin_selected = State()
#     awaiting_destination = State()
#     destination_selected = State()
#     awaiting_dates = State()
#     dates_selected = State()
#     awaiting_price = State()
#     price_entered = State()
#     awaiting_transfers = State()  # Новое состояние
#     transfers_selected = State()  # Новое состояние
#     awaiting_class = State()  # Новое состояние
#     class_selected = State()  # Новое состояние
#     confirming = State()
#
#
# # ================= HELPERS =================
# async def format_date_for_display(date_str: str) -> str:
#     """Форматирование даты из ISO формата в читаемый вид"""
#     try:
#         date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
#         return date_obj.strftime("%d.%m.%Y")
#     except:
#         return date_str
#
#
# def get_city_name_by_code(code: str) -> str:
#     """Получить название города по коду IATA"""
#     # Добавьте больше городов при необходимости
#     city_map = {
#         'MOW': 'Москва',
#         'LED': 'Санкт-Петербург',
#         'KHV': 'Хабаровск',
#         'NHA': 'Нячанг',
#         'BKK': 'Бангкок',
#         'PEK': 'Пекин',
#         'SVO': 'Москва (Шереметьево)',
#         'DME': 'Москва (Домодедово)',
#         'VKO': 'Москва (Внуково)',
#     }
#     return city_map.get(code, code)
#
#
# # ================= START =================
# @dp.message(Command("start"))
# async def start(message: Message, state: FSMContext):
#     user_id = message.from_user.id
#
#     # Очищаем состояние
#     await state.clear()
#
#     try:
#         async with async_session() as session:
#             # Используем await для асинхронного выполнения
#             total = await session.scalar(
#                 select(func.count())
#                 .select_from(Task)
#                 .where(Task.user_id == user_id, Task.status == TaskStatus.active)
#             )
#
#             # Получаем задачи
#             tasks_result = await session.execute(
#                 select(Task)
#                 .where(Task.user_id == user_id, Task.status == TaskStatus.active)
#                 .order_by(Task.created_at.desc())
#             )
#             tasks = tasks_result.scalars().all()
#
#         if total and total > 0:
#             await message.answer(f"📌 У вас {total} активных задач:")
#
#             for t in tasks:
#                 text = (
#                     f"✈️ {get_city_name_by_code(t.origin)} → {get_city_name_by_code(t.destination)}\n"
#                     f"📅 {t.date_from} – {t.date_to}\n"
#                     f"💰 до {t.max_price or '∞'} руб.\n"
#                     f"🔄 Пересадки: {t.max_transfers if t.max_transfers is not None else 'не важно'}\n"
#                     f"💺 Класс: {['эконом', 'бизнес', 'первый'][t.trip_class if t.trip_class else 0]}"
#                 )
#                 kb = InlineKeyboardMarkup(inline_keyboard=[
#                     [InlineKeyboardButton(
#                         text="❌ Удалить задачу",
#                         callback_data=f"cancel:{t.id}"
#                     )]
#                 ])
#                 await message.answer(text, reply_markup=kb)
#         else:
#             await message.answer("У вас пока нет активных задач")
#
#         await ask_origin(message, state)
#
#     except Exception as e:
#         print(f"Ошибка в функции start: {e}")
#         await message.answer("Произошла ошибка при загрузке задач. Попробуйте еще раз.")
#
#
# # ================= NEW SEARCH =================
# @dp.callback_query(F.data == "new:start")
# async def new_search(callback: CallbackQuery, state: FSMContext):
#     user_id = callback.from_user.id
#     await callback.answer()
#     await state.clear()
#
#     # Создаем новое сообщение для начала поиска
#     kb = InlineKeyboardMarkup(inline_keyboard=[
#         [InlineKeyboardButton(text="✈️ Начать поиск", callback_data="start_search")]
#     ])
#     await callback.message.edit_text("✈️ Начнем новый поиск билетов", reply_markup=kb)
#
#
# @dp.callback_query(F.data == "start_search")
# async def start_search(callback: CallbackQuery, state: FSMContext):
#     await callback.answer()
#     await ask_origin(callback.message, state)
#
#
# # ================= CANCEL TASK =================
# @dp.callback_query(F.data.startswith("cancel:"))
# async def cancel_task(callback: CallbackQuery):
#     task_id = int(callback.data.split(":")[1])
#
#     try:
#         async with async_session() as session:
#             async with session.begin():
#                 task = await session.get(Task, task_id)
#                 if task:
#                     task.status = TaskStatus.closed
#                 else:
#                     await callback.message.edit_text("❌ Задача не найдена")
#                     await callback.answer()
#                     return
#
#         await callback.message.edit_text("❌ Задача отменена")
#
#     except Exception as e:
#         print(f"Ошибка при отмене задачи: {e}")
#         await callback.message.edit_text("❌ Произошла ошибка при отмене задачи")
#
#     await callback.answer()
#
#
# # ================= ORIGIN =================
# async def ask_origin(message: Message, state: FSMContext):
#     kb = []
#     row = []
#     for city in ORIGIN_CITIES:
#         row.append(InlineKeyboardButton(
#             text=city,
#             callback_data=f"origin:{city}"
#         ))
#         if len(row) == 2:
#             kb.append(row)
#             row = []
#     if row:
#         kb.append(row)
#
#     await state.set_state(FlightSearch.awaiting_origin)
#     await message.answer(
#         "✈️ Выберите город вылета или введите вручную:",
#         reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
#     )
#
#
# @dp.message(FlightSearch.awaiting_origin)
# async def manual_origin(message: Message, state: FSMContext):
#     city = message.text.strip()
#     city_info = get_data_airport(city)
#
#     if not city_info:
#         await message.answer("❌ Город не найден, попробуйте ещё раз")
#         return
#
#     await state.update_data(origin=city_info)
#     await state.set_state(FlightSearch.origin_selected)
#     await message.answer(f"✅ Вылет: {city_info['name']} ({city_info['code']})")
#     await ask_destination(message, state)
#
#
# @dp.callback_query(F.data.startswith("origin:"))
# async def choose_origin(callback: CallbackQuery, state: FSMContext):
#     city = callback.data.split(":", 1)[1]
#     city_info = get_data_airport(city)
#
#     if not city_info:
#         await callback.answer("❌ Город не найден")
#         return
#
#     await state.update_data(origin=city_info)
#     await state.set_state(FlightSearch.origin_selected)
#
#     # Редактируем сообщение или отправляем новое
#     if hasattr(callback.message, 'edit_text'):
#         await callback.message.edit_text(f"✅ Вылет: {city_info['name']} ({city_info['code']})")
#     else:
#         await callback.message.answer(f"✅ Вылет: {city_info['name']} ({city_info['code']})")
#
#     await ask_destination(callback.message, state)
#     await callback.answer()
#
#
# # ================= DESTINATION =================
# async def ask_destination(message: Message, state: FSMContext):
#     kb = []
#     row = []
#     for city in DESTINATION_CITIES:
#         row.append(InlineKeyboardButton(
#             text=city,
#             callback_data=f"dest:{city}"
#         ))
#         if len(row) == 2:
#             kb.append(row)
#             row = []
#     if row:
#         kb.append(row)
#
#     await state.set_state(FlightSearch.awaiting_destination)
#     await message.answer(
#         "🏙 Выберите город прилёта или введите вручную:",
#         reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
#     )
#
#
# @dp.message(FlightSearch.awaiting_destination)
# async def manual_destination(message: Message, state: FSMContext):
#     city = message.text.strip()
#     city_info = get_data_airport(city)
#
#     if not city_info:
#         await message.answer("❌ Город не найден, попробуйте ещё раз")
#         return
#
#     await state.update_data(destination=city_info)
#     await state.set_state(FlightSearch.destination_selected)
#     await message.answer(f"✅ Прилёт: {city_info['name']} ({city_info['code']})")
#     await ask_dates(message, state)
#
#
# @dp.callback_query(F.data.startswith("dest:"))
# async def choose_destination(callback: CallbackQuery, state: FSMContext):
#     city = callback.data.split(":", 1)[1]
#     city_info = get_data_airport(city)
#
#     if not city_info:
#         await callback.answer("❌ Город не найден")
#         return
#
#     await state.update_data(destination=city_info)
#     await state.set_state(FlightSearch.destination_selected)
#
#     # Редактируем сообщение или отправляем новое
#     if hasattr(callback.message, 'edit_text'):
#         await callback.message.edit_text(f"✅ Прилёт: {city_info['name']} ({city_info['code']})")
#     else:
#         await callback.message.answer(f"✅ Прилёт: {city_info['name']} ({city_info['code']})")
#
#     await ask_dates(callback.message, state)
#     await callback.answer()
#
#
# # ================= DATES =================
# async def ask_dates(message: Message, state: FSMContext):
#     kb = [
#         [
#             InlineKeyboardButton(text="3 дней", callback_data="dates:3"),
#             InlineKeyboardButton(text="7 дней", callback_data="dates:7")
#         ],
#         [
#             InlineKeyboardButton(text="14 дней", callback_data="dates:14"),
#             InlineKeyboardButton(text="30 дней", callback_data="dates:30")
#         ]
#     ]
#
#     await state.set_state(FlightSearch.awaiting_dates)
#     await message.answer(
#         "📅 Выберите период даты вылета или введите вручную в формате:\n`01.12.2025-20.12.2025`",
#         reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
#         parse_mode=ParseMode.MARKDOWN
#     )
#
#
# @dp.callback_query(F.data.startswith("dates:"))
# async def dates_callback(callback: CallbackQuery, state: FSMContext):
#     days = int(callback.data.split(":")[1])
#
#     date_from = datetime.now().date()
#     date_to = date_from + timedelta(days=days)
#
#     await state.update_data(
#         date_from=date_from.isoformat(),
#         date_to=date_to.isoformat(),
#         date_from_display=date_from.strftime("%d.%m.%Y"),
#         date_to_display=date_to.strftime("%d.%m.%Y")
#     )
#
#     await state.set_state(FlightSearch.dates_selected)
#
#     if hasattr(callback.message, 'edit_text'):
#         await callback.message.edit_text(f"📅 Период: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}")
#     else:
#         await callback.message.answer(f"📅 Период: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}")
#
#     await ask_price(callback.message, state)
#     await callback.answer()
#
#
# @dp.message(FlightSearch.awaiting_dates)
# async def manual_dates(message: Message, state: FSMContext):
#     try:
#         d1, d2 = message.text.split("-")
#         date_from = datetime.strptime(d1.strip(), "%d.%m.%Y").date()
#         date_to = datetime.strptime(d2.strip(), "%d.%m.%Y").date()
#
#         if date_from > date_to:
#             raise ValueError("Дата начала позже даты окончания")
#
#         if date_from < datetime.now().date():
#             raise ValueError("Дата начала в прошлом")
#
#         await state.update_data(
#             date_from=date_from.isoformat(),
#             date_to=date_to.isoformat(),
#             date_from_display=date_from.strftime("%d.%m.%Y"),
#             date_to_display=date_to.strftime("%d.%m.%Y")
#         )
#
#         await state.set_state(FlightSearch.dates_selected)
#         await message.answer(f"✅ Период: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}")
#         await ask_price(message, state)
#
#     except ValueError as e:
#         error_msg = str(e)
#         if "не соответствует формату" in error_msg or "time data" in error_msg:
#             await message.answer("❌ Неверный формат даты. Используйте: ДД.ММ.ГГГГ-ДД.ММ.ГГГГ")
#         else:
#             await message.answer(f"❌ Ошибка: {error_msg}. Используйте корректные даты.")
#     except Exception:
#         await message.answer("❌ Ошибка ввода. Формат: 01.12.2025-20.12.2025")
#
#
# # ================= PRICE =================
# async def ask_price(message: Message, state: FSMContext):
#     await state.set_state(FlightSearch.awaiting_price)
#     await message.answer("💰 Введите максимальную цену в рублях:")
#
#
# @dp.message(FlightSearch.awaiting_price)
# async def input_price(message: Message, state: FSMContext):
#     try:
#         price = int(message.text.strip())
#         if price <= 0:
#             await message.answer("❌ Цена должна быть положительным числом")
#             return
#
#         if price > 1000000:
#             await message.answer("❌ Слишком большая цена. Введите значение до 1 000 000 ₽")
#             return
#
#         await state.update_data(max_price=price)
#         await state.set_state(FlightSearch.price_entered)
#         await ask_transfers(message, state)  # Переходим к выбору пересадок
#     except ValueError:
#         await message.answer("❌ Введите корректное число (например: 50000)")
#
#
# # ================= TRANSFERS =================
# async def ask_transfers(message: Message, state: FSMContext):
#     kb = [
#         [InlineKeyboardButton(text="🚀 Без пересадок", callback_data="transfers:0")],
#         [InlineKeyboardButton(text="1️⃣ До 1 пересадки", callback_data="transfers:1")],
#         [InlineKeyboardButton(text="2️⃣ До 2 пересадок", callback_data="transfers:2")],
#         [InlineKeyboardButton(text="♾️ Не важно", callback_data="transfers:any")],
#     ]
#
#     await state.set_state(FlightSearch.awaiting_transfers)
#     await message.answer(
#         "🔄 Выберите максимальное количество пересадок:",
#         reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
#     )
#
#
# @dp.callback_query(FlightSearch.awaiting_transfers)
# async def choose_transfers(callback: CallbackQuery, state: FSMContext):
#     transfers_data = callback.data.split(":")[1]
#
#     if transfers_data == "any":
#         max_transfers = None
#         display_text = "♾️ Не важно"
#     else:
#         max_transfers = int(transfers_data)
#         display_text = f"{max_transfers} пересадок" if max_transfers > 0 else "Без пересадок"
#
#     await state.update_data(max_transfers=max_transfers)
#     await state.set_state(FlightSearch.transfers_selected)
#
#     if hasattr(callback.message, 'edit_text'):
#         await callback.message.edit_text(f"✅ Пересадки: {display_text}")
#     else:
#         await callback.message.answer(f"✅ Пересадки: {display_text}")
#
#     await ask_class(callback.message, state)
#     await callback.answer()
#
#
# # ================= CLASS =================
# async def ask_class(message: Message, state: FSMContext):
#     kb = [
#         [InlineKeyboardButton(text="💺 Эконом класс", callback_data="class:0")],
#         [InlineKeyboardButton(text="👔 Бизнес класс", callback_data="class:1")],
#         [InlineKeyboardButton(text="👑 Первый класс", callback_data="class:2")],
#     ]
#
#     await state.set_state(FlightSearch.awaiting_class)
#     await message.answer(
#         "💺 Выберите класс перелета:",
#         reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
#     )
#
#
# @dp.callback_query(FlightSearch.awaiting_class)
# async def choose_class(callback: CallbackQuery, state: FSMContext):
#     trip_class = int(callback.data.split(":")[1])
#
#     class_names = {
#         0: "💺 Эконом класс",
#         1: "👔 Бизнес класс",
#         2: "👑 Первый класс"
#     }
#
#     await state.update_data(trip_class=trip_class)
#     await state.set_state(FlightSearch.class_selected)
#
#     if hasattr(callback.message, 'edit_text'):
#         await callback.message.edit_text(f"✅ Класс: {class_names[trip_class]}")
#     else:
#         await callback.message.answer(f"✅ Класс: {class_names[trip_class]}")
#
#     await confirm(callback.message, state)
#     await callback.answer()
#
#
# # ================= CONFIRM =================
# async def confirm(message: Message, state: FSMContext):
#     data = await state.get_data()
#
#     # Проверяем, что все необходимые данные есть
#     required_fields = ["origin", "destination", "date_from", "date_to", "max_price", "trip_class"]
#     missing = [field for field in required_fields if field not in data]
#
#     if missing:
#         await message.answer(f"❌ Ошибка: отсутствуют данные: {missing}. Начните заново /start")
#         await state.clear()
#         return
#
#     # Форматируем даты для отображения
#     date_from_display = data.get("date_from_display") or await format_date_for_display(data["date_from"])
#     date_to_display = data.get("date_to_display") or await format_date_for_display(data["date_to"])
#
#     # Форматируем пересадки
#     max_transfers_display = "не важно" if data.get("max_transfers") is None else str(data.get("max_transfers"))
#
#     # Форматируем класс
#     class_names = {
#         0: "Эконом",
#         1: "Бизнес",
#         2: "Первый"
#     }
#     trip_class_display = class_names.get(data.get("trip_class", 0), "Эконом")
#
#     text = (
#         f"📋 <b>Проверьте данные:</b>\n\n"
#         f"✈️ <b>Вылет:</b> {data['origin']['name']} ({data['origin']['code']})\n"
#         f"🏙 <b>Прилёт:</b> {data['destination']['name']} ({data['destination']['code']})\n"
#         f"📅 <b>Период поиска:</b> {date_from_display} — {date_to_display}\n"
#         f"💰 <b>Макс. цена:</b> {data['max_price']} ₽\n"
#         f"🔄 <b>Пересадки:</b> {max_transfers_display}\n"
#         f"💺 <b>Класс:</b> {trip_class_display}\n\n"
#         "Все верно?"
#     )
#
#     kb = InlineKeyboardMarkup(inline_keyboard=[
#         [
#             InlineKeyboardButton(text="✅ Да, искать", callback_data="confirm:yes"),
#             InlineKeyboardButton(text="❌ Нет, отменить", callback_data="confirm:no")
#         ]
#     ])
#
#     await state.set_state(FlightSearch.confirming)
#     await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
#
#
# @dp.callback_query(F.data.startswith("confirm:"))
# async def confirm_handler(callback: CallbackQuery, state: FSMContext):
#     await callback.answer("⏳ Обрабатываю...")
#     data = await state.get_data()
#
#     if callback.data.endswith("no"):
#         await callback.message.edit_text("❌ Отменено. Для нового поиска введите /start")
#         await state.clear()
#         return
#
#     await callback.message.edit_text("🔍 Ищу билеты...")
#
#     try:
#         date_from = datetime.strptime(data["date_from"], "%Y-%m-%d").date()
#         date_to = datetime.strptime(data["date_to"], "%Y-%m-%d").date()
#
#         flights = get_tickets_aviasales(
#             origin=data["origin"]["code"],
#             destination=data["destination"]["code"],
#             depart_date_from=date_from,
#             depart_date_to=date_to,
#             max_price=data["max_price"],
#             max_transfers=data.get("max_transfers"),
#             trip_class=data.get("trip_class", 0),
#             direct=(data.get("max_transfers") == 0)  # Если выбрано "без пересадок"
#         )
#
#         print(f"Найдено билетов: {len(flights) if flights else 0}")
#
#         if not flights:
#             await callback.message.answer("😔 Билеты по заданным критериям не найдены")
#             await ask_subscription(callback.message, state)
#             return
#
#         flights_to_show = flights[:8]
#         await callback.message.answer(f"✅ Найдено {len(flights_to_show)} билетов:")
#
#         for i, f in enumerate(flights_to_show, 1):
#             # Используем название города вместо кода
#             origin_city = get_city_name_by_code(f.get('origin', ''))
#             destination_city = get_city_name_by_code(f.get('destination', ''))
#
#             message_text = (
#                 f"<b>Билет {i}:</b>\n"
#                 f"💰 <b>Цена:</b> {f['price']} ₽\n"
#                 f"✈️ <b>Маршрут:</b> {origin_city} ({f.get('origin_airport', '')}) → "
#                 f"{destination_city} ({f.get('destination_airport', '')})\n"
#                 f"📅 <b>Дата вылета:</b> {f['depart_date']}\n"
#             )
#
#             if f.get("return_date"):
#                 message_text += f"📅 <b>Дата возврата:</b> {f['return_date']}\n"
#
#             if f.get("airline"):
#                 message_text += f"🏢 <b>Авиакомпания:</b> {f['airline']}\n"
#
#             if f.get("flight_number"):
#                 message_text += f"✈️ <b>Номер рейса:</b> {f['flight_number']}\n"
#
#             if f.get("transfers") is not None:
#                 transfers_text = "Без пересадок" if f['transfers'] == 0 else f"{f['transfers']} пересадки"
#                 message_text += f"🔄 <b>Пересадки:</b> {transfers_text}\n"
#
#             if f.get("trip_class") is not None:
#                 class_names = {0: "Эконом", 1: "Бизнес", 2: "Первый"}
#                 message_text += f"💺 <b>Класс:</b> {class_names.get(f['trip_class'], 'Эконом')}\n"
#
#             if f.get("duration_to"):
#                 hours = f['duration_to'] // 60
#                 minutes = f['duration_to'] % 60
#                 message_text += f"⏱ <b>Время в пути:</b> {hours}ч {minutes}м\n"
#
#             kb = None
#             if f.get("affiliate_url"):
#                 kb = InlineKeyboardMarkup(inline_keyboard=[
#                     [InlineKeyboardButton(
#                         text="🔗 Перейти к покупке",
#                         url=f["affiliate_url"]
#                     )]
#                 ])
#
#             await bot.send_message(
#                 callback.from_user.id,
#                 message_text,
#                 parse_mode=ParseMode.HTML,
#                 reply_markup=kb
#             )
#
#         await ask_subscription(callback.message, state)
#
#     except Exception as e:
#         print(f"Ошибка при поиске билетов: {e}")
#         await callback.message.answer(f"❌ Ошибка при поиске билетов: {str(e)}")
#
#
# # ================= SUBSCRIPTION =================
# async def ask_subscription(message: Message, state: FSMContext):
#     data = await state.get_data()
#
#     kb = InlineKeyboardMarkup(inline_keyboard=[
#         [
#             InlineKeyboardButton(text="🔔 Подписаться", callback_data="sub:yes"),
#             InlineKeyboardButton(text="❌ Нет, спасибо", callback_data="sub:no")
#         ]
#     ])
#
#     await message.answer(
#         "Хотите создать подписку на мониторинг новых билетов по этим параметрам? "
#         "Как только мы найдем билеты по вашим параметрам, мы пришлем вам сообщение!",
#         reply_markup=kb
#     )
#
#
# @dp.callback_query(F.data.startswith("sub:"))
# async def subscription_handler(callback: CallbackQuery, state: FSMContext):
#     data = await state.get_data()
#
#     if callback.data.endswith("no"):
#         await callback.message.edit_text("✅ Хорошо! Если понадобится — введите /start")
#         await state.clear()
#         await callback.answer()
#         return
#
#     try:
#         date_from_str = data["date_from"]
#         date_to_str = data["date_to"]
#
#         async with async_session() as session:
#             async with session.begin():
#                 task = Task()
#
#                 # Устанавливаем атрибуты напрямую
#                 task.user_id = callback.from_user.id
#                 task.origin = data["origin"]["code"]
#                 task.destination = data["destination"]["code"]
#                 task.date_from = date_from_str
#                 task.date_to = date_to_str
#                 task.max_price = data["max_price"]
#                 task.max_transfers = data.get("max_transfers")
#                 task.trip_class = data.get("trip_class", 0)
#                 task.status = TaskStatus.active
#                 task.is_public = False
#
#                 session.add(task)
#                 await session.flush()
#
#                 print(f"✅ Задача создана: ID={task.id}, user_id={task.user_id}, {task.origin}->{task.destination}")
#
#                 await session.commit()
#
#         # Просто текст без кнопки
#         await callback.message.edit_text(
#             "✅ Подписка создана! Вы будете получать уведомления о новых билетах.\n\n"
#             "Для нового поиска используйте /start"
#         )
#
#     except Exception as e:
#         print(f"❌ Ошибка при создании подписки: {e}")
#         import traceback
#         traceback.print_exc()
#
#         await callback.message.edit_text(
#             "✅ Подписка создана! (Возникла техническая ошибка)"
#         )
#
#     finally:
#         await state.clear()
#         await callback.answer()
#
#
# # ================= FALLBACK HANDLER =================
# @dp.message()
# async def fallback_handler(message: Message, state: FSMContext):
#     current_state = await state.get_state()
#
#     if current_state is None:
#         await message.answer("Для начала поиска билетов введите /start")
#         return
#
#     # Если пользователь в процессе диалога, перенаправляем на соответствующий обработчик
#     if current_state == FlightSearch.awaiting_origin:
#         await manual_origin(message, state)
#     elif current_state == FlightSearch.awaiting_destination:
#         await manual_destination(message, state)
#     elif current_state == FlightSearch.awaiting_dates:
#         await manual_dates(message, state)
#     elif current_state == FlightSearch.awaiting_price:
#         await input_price(message, state)
#     elif current_state == FlightSearch.awaiting_transfers:
#         await message.answer("Пожалуйста, выберите количество пересадок из предложенных вариантов.")
#     elif current_state == FlightSearch.awaiting_class:
#         await message.answer("Пожалуйста, выберите класс перелета из предложенных вариантов.")
#     else:
#         await message.answer("Пожалуйста, следуйте инструкциям. Или начните заново: /start")
#
#
# # ================= RUN =================
# async def main():
#     print("Бот запущен...")
#     await dp.start_polling(bot)
#
#
# if __name__ == "__main__":
#     asyncio.run(main())
#

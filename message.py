from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import logging
logging.basicConfig(level=logging.INFO)
from bot import bot
from api import get_data_airport


async def send_flight_user(user_id, flights, max_show=5, bot_instance=None):
    """
    Отправляет пользователю список найденных билетов.

    :param user_id: ID пользователя
    :param flights: список билетов (каждый словарь с ключами price, origin, destination, depart_date и т.д.)
    :param max_show: сколько билетов показывать
    :param bot_instance: экземпляр бота (передавать, если есть проблемы с импортом)
    """
    # Используем переданный бот или импортированный
    current_bot = bot_instance or bot
    if not current_bot:
        raise ValueError("Bot instance is required")

    if not flights:
        await current_bot.send_message(user_id, "😔 Билеты не найдены по вашим параметрам.")
        return

    for i, f in enumerate(flights[:max_show], 1):
        # Получаем русские названия городов через функцию get_data_airport
        origin_city_data = get_data_airport(f['origin'])
        destination_city_data = get_data_airport(f['destination'])

        # Формируем названия городов
        origin_name = origin_city_data.get('name', f['origin']) if origin_city_data else f['origin']
        destination_name = destination_city_data.get('name', f['destination']) if destination_city_data else f[
            'destination']

        # Формируем строку маршрута
        origin_str = f"{origin_name}"
        if f.get('origin_airport'):
            origin_str += f" ({f['origin_airport']})"
        elif f.get('origin'):
            origin_str += f" ({f['origin']})"

        destination_str = f"{destination_name}"
        if f.get('destination_airport'):
            destination_str += f" ({f['destination_airport']})"
        elif f.get('destination'):
            destination_str += f" ({f['destination']})"

        message_text = (
            f"*Билет {i}:*\n"
            f"💰 *Цена:* {f['price']} ₽\n"
            f"✈️ *Маршрут:* {origin_str} → {destination_str}\n"
            f"📅 *Дата вылета:* {f['depart_date']}\n"
        )

        if f.get("return_date"):
            message_text += f"📅 *Дата возврата:* {f['return_date']}\n"
        if f.get("airline"):
            message_text += f"🏢 *Авиакомпания:* {f['airline']}\n"
        if f.get("flight_number"):
            message_text += f"✈️ *Номер рейса:* {f['flight_number']}\n"
        if f.get("transfers") is not None:
            transfers_text = "Прямой рейс" if f['transfers'] == 0 else f"{f['transfers']} пересадки"
            message_text += f"🔄 *Пересадки:* {transfers_text}\n"

        kb = None
        if f.get("affiliate_url"):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔗 Купить билет",
                    url=f["affiliate_url"]
                )]
            ])

        await current_bot.send_message(
            user_id,
            message_text,
            parse_mode="Markdown",
            reply_markup=kb
        )

    # Кнопка "Новый поиск" после отправки всех билетов
    kb_new = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔄 Новый поиск", callback_data="new:start")]
    ])
    await current_bot.send_message(user_id, "Вы можете начать новый поиск:", reply_markup=kb_new)


async def send_flight_public(user_id, flights, max_show=1, bot_instance=None):
    if not flights:
        return

    current_bot = bot_instance or bot
    if not current_bot:
        raise ValueError("Bot instance is required")

    for i, f in enumerate(flights[:max_show], 1):
        # Получаем русские названия городов через функцию get_data_airport
        origin_city_data = get_data_airport(f['origin'])
        destination_city_data = get_data_airport(f['destination'])

        # Формируем названия городов
        origin_name = origin_city_data.get('name', f['origin']) if origin_city_data else f['origin']
        destination_name = destination_city_data.get('name', f['destination']) if destination_city_data else f[
            'destination']

        # Формируем строку маршрута
        origin_str = f"{origin_name}"
        if f.get('origin_airport'):
            origin_str += f" ({f['origin_airport']})"
        elif f.get('origin'):
            origin_str += f" ({f['origin']})"

        destination_str = f"{destination_name}"
        if f.get('destination_airport'):
            destination_str += f" ({f['destination_airport']})"
        elif f.get('destination'):
            destination_str += f" ({f['destination']})"

        message_text = (
            f"*Билет {i}:*\n"
            f"💰 *Цена:* {f['price']} ₽\n"
            f"✈️ *Маршрут:* {origin_str} → {destination_str}\n"
            f"📅 *Дата вылета:* {f['depart_date']}\n"
        )

        if f.get("return_date"):
            message_text += f"📅 *Дата возврата:* {f['return_date']}\n"
        if f.get("airline"):
            message_text += f"🏢 *Авиакомпания:* {f['airline']}\n"
        if f.get("flight_number"):
            message_text += f"✈️ *Рейс:* {f['flight_number']}\n"
        if f.get("transfers") is not None:
            transfers_text = "Прямой рейс" if f['transfers'] == 0 else f"{f['transfers']} пересадки"
            message_text += f"🔄 *Пересадки:* {transfers_text}\n"

        kb = None
        if f.get("affiliate_url"):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔗 Купить билет",
                    url=f["affiliate_url"]
                )]
            ])

        await current_bot.send_message(
            chat_id=user_id,
            text=message_text,
            reply_markup=kb,
            parse_mode="Markdown"
        )
#
# async def send_flight_user(user_id, flights, max_show=5, bot_instance=None):
#     """
#     Отправляет пользователю список найденных билетов.
#
#     :param user_id: ID пользователя
#     :param flights: список билетов (каждый словарь с ключами price, origin, destination, depart_date и т.д.)
#     :param max_show: сколько билетов показывать
#     :param bot_instance: экземпляр бота (передавать, если есть проблемы с импортом)
#     """
#     # Используем переданный бот или импортированный
#     current_bot = bot_instance or bot
#     if not current_bot:
#         raise ValueError("Bot instance is required")
#
#     if not flights:
#         await current_bot.send_message(user_id, "😔 Билеты не найдены по вашим параметрам.")
#         return
#
#     for i, f in enumerate(flights[:max_show], 1):
#         message_text = (
#             f"*Билет {i}:*\n"
#             f"💰 Цена: {f['price']} ₽\n"
#             f"✈️ Маршрут: {f['origin']} ({f.get('origin_airport')}) → "
#             f"{f['destination']} ({f.get('destination_airport')})\n"
#             f"📅 Дата вылета: {f['depart_date']}\n"
#         )
#         if f.get("return_date"):
#             message_text += f"📅 Дата возврата: {f['return_date']}\n"
#         if f.get("airline"):
#             message_text += f"Авиакомпания: {f['airline']}\n"
#         if f.get("flight_number"):
#             message_text += f"Номер рейса: {f['flight_number']}\n"
#         if f.get("transfers") is not None:
#             message_text += f"Пересадки: {f['transfers']}\n"
#
#         kb = None
#         if f.get("affiliate_url"):
#             kb = InlineKeyboardMarkup(inline_keyboard=[
#                 [InlineKeyboardButton(
#                     text="🔗 Купить билет",
#                     url=f["affiliate_url"]
#                 )]
#             ])
#
#         await current_bot.send_message(
#             user_id,
#             message_text,
#             parse_mode="Markdown",
#             reply_markup=kb
#         )
#
#
#     kb_new = InlineKeyboardMarkup(inline_keyboard=[
#         [InlineKeyboardButton("🔄 Новый поиск", callback_data="new:start")]
#     ])
#     await current_bot.send_message(user_id, "Вы можете начать новый поиск:", reply_markup=kb_new)
#
#
# async def send_flight_public(user_id, flights, max_show=1, bot_instance=None):
#     if not flights:
#         return
#
#     current_bot = bot_instance or bot
#     if not current_bot:
#         raise ValueError("Bot instance is required")
#
#     for i, f in enumerate(flights[:max_show], 1):
#         message_text = (
#             f"*Билет {i}:*\n"
#             f"💰 *Цена:* {f['price']} ₽\n"
#             f"✈️ *Маршрут:* {f['origin']} ({f.get('origin_airport')}) → "
#             f"{f['destination']} ({f.get('destination_airport')})\n"
#             f"📅 *Дата вылета:* {f['depart_date']}\n"
#         )
#
#         if f.get("return_date"):
#             message_text += f"📅 *Дата возврата:* {f['return_date']}\n"
#         if f.get("airline"):
#             message_text += f"🏢 *Авиакомпания:* {f['airline']}\n"
#         if f.get("flight_number"):
#             message_text += f"✈️ *Рейс:* {f['flight_number']}\n"
#         if f.get("transfers") is not None:
#             message_text += f"🔄 *Пересадки:* {f['transfers']}\n"
#
#         kb = None
#         if f.get("affiliate_url"):
#             kb = InlineKeyboardMarkup(inline_keyboard=[
#                 [InlineKeyboardButton(
#                     text="🔗 Купить билет",
#                     url=f["affiliate_url"]
#                 )]
#             ])
#
#         await current_bot.send_message(
#             chat_id=user_id,
#             text=message_text,
#             reply_markup=kb,
#             parse_mode="Markdown"
#         )

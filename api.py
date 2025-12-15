import requests
import os
from dotenv import load_dotenv
from datetime import date, datetime, timedelta
load_dotenv()

TRAVEL_TOKEN = os.getenv("TRAVEL_TOKEN")
TRAVEL_AVIASALES_MARKER = os.getenv("TRAVEL_AVIASALES_MARKER")
AVIASALES_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


def make_affiliate_link(item):
    """Создание партнерской ссылки"""
    base = "https://www.aviasales.ru"
    link = item["link"]
    if "?" in link:
        return f"{base}{link}&marker={TRAVEL_AVIASALES_MARKER}"
    else:
        return f"{base}{link}?marker={TRAVEL_AVIASALES_MARKER}"


def month_range(date_from, date_to):
    """Возвращает список месяцев YYYY-MM между двумя датами"""
    months = []
    current = date_from.replace(day=1)
    end_date = date_to.replace(day=1)

    while current <= end_date:
        months.append(current.strftime("%Y-%m"))
        # Переход к следующему месяцу
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return months


def get_tickets_aviasales(
        origin,
        destination,
        depart_date_from,
        depart_date_to,
        one_way = True,
        max_price = None,
        return_days = None,
        return_flex_days = 0,
        currency = "rub",
        direct = False,
        max_transfers = None,
        trip_class = 0,  # 0 economy | 1 business | 2 first
):
    def filter_ticket(data):
        """Фильтрация билетов из ответа API"""
        filtered_results = []  # Исправлено имя переменной
        for item in data.get("data", []):
            # Парсим дату вылета
            depart_at = datetime.fromisoformat(item["departure_at"].replace("Z", "+00:00")).date()
            # Проверяем диапазон дат
            if not (depart_date_from <= depart_at <= depart_date_to):
                continue
            # Проверяем класс перелета
            if trip_class != 0 and item.get("trip_class") != trip_class:
                continue
            # Проверяем количество пересадок
            if max_transfers is not None:
                transfers = item.get("transfers", 0)
                if transfers > max_transfers:
                    continue
            # Для билетов туда-обратно
            return_at = None
            if not one_way:
                if not item.get("return_at"):
                    continue
                return_at = datetime.fromisoformat(item["return_at"].replace("Z", "+00:00")).date()
                # Проверяем гибкость дней возврата
                if return_days is not None:
                    expected_return = depart_at + timedelta(days=return_days)
                    if abs((return_at - expected_return).days) > return_flex_days:
                        continue
            # Проверяем максимальную цену
            if max_price and item["price"] > max_price:
                continue
            # Проверяем на прямые рейсы
            if direct and item.get("transfers", 0) > 0:
                continue
            # Формируем данные билета
            ticket_data = {
                "price": item["price"],
                "origin": item.get("origin"),
                "origin_airport": item.get("origin_airport"),
                "destination": item.get("destination"),
                "destination_airport": item.get("destination_airport"),
                "depart_date": depart_at.strftime("%d.%m.%Y"),  # Исправлен формат
                "return_date": return_at.strftime("%d.%m.%Y") if return_at else None,
                "airline": item.get("airline"),
                "flight_number": item.get("flight_number"),
                "transfers": item.get("transfers"),
                "duration": item.get("duration"),
                "duration_to": item.get("duration_to"),
                "duration_back": item.get("duration_back"),
                "return_transfers": item.get("return_transfers"),
                "trip_class": item.get("trip_class"),
                "affiliate_url": make_affiliate_link(item),
            }

            filtered_results.append(ticket_data)

        return filtered_results

    # Собираем результаты
    results = []
    departure_months = month_range(depart_date_from, depart_date_to)

    for i, departure_month in enumerate(departure_months, 1):
        print(f"📊 Запрос месяца {i}/{len(departure_months)}: {departure_month}")

        params = {
            "origin": origin,
            "destination": destination,
            "departure_at": departure_month,
            "one_way": "true" if one_way else "false",
            "sorting": "price",
            "direct": "true" if direct else "false",
            "cy": currency,
            "limit": 100,
            "token": TRAVEL_TOKEN,
            "trip_class": trip_class,
        }
        # Добавляем параметр пересадок если указан
        if max_transfers is not None:
            params["max_transfers"] = max_transfers
        try:
            response = requests.get(AVIASALES_URL, params=params, timeout=15)
            if response.status_code != 200:
                continue
            data = response.json()
            # Проверяем наличие данных
            if not data.get("data"):
                print(f"   ℹ️ Нет данных за {departure_month}")
                continue
            # Фильтруем билеты
            month_results = filter_ticket(data)
            results.extend(month_results)
        except requests.exceptions.Timeout:
            print(f"   ⏰ Таймаут запроса за {departure_month}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Ошибка сети: {e}")
        except Exception as e:
            print(f"   ❌ Неизвестная ошибка: {e}")

    sorted_results = sorted(results, key=lambda x: x["price"])
    return sorted_results

def get_data_airport(citi):
    # iata — код аэропорта ближайшего города
    # name — название города
    # coordinates — координаты
    url = "https://api.travelpayouts.com/data/ru/cities.json"
    resp = requests.get(url)
    cities = resp.json()
    for i in cities:
        if i.get("name") == citi:
            return i
    return None







def create_affiliate_link(origin: str, destination: str, depart_date: str, return_date: str = None) -> str:
    """
    Создаёт партнёрскую ссылку на Aviasales с использованием маркера.

    Параметры:
    - origin: IATA код города вылета (например, 'MOW')
    - destination: IATA код города прилёта (например, 'BKK')
    - depart_date: дата вылета в формате 'YYYY-MM-DD' (например, '2026-01-01')
    - return_date: дата обратного рейса в формате 'YYYY-MM-DD' (необязательно)

    Возвращает ссылку вида:
    https://www.aviasales.ru/search/MOW0101BKK1?marker=123456
    """

    # Преобразуем дату в формат DDMM
    depart_dt = datetime.fromisoformat(depart_date)
    depart_part = depart_dt.strftime("%d%m")

    # Для возвратного билета добавляем 2-й маркер (необязательный)
    if return_date:
        return_dt = datetime.fromisoformat(return_date)
        return_part = return_dt.strftime("%d%m")
        search_code = f"{origin}{depart_part}{destination}{return_part}1"
    else:
        search_code = f"{origin}{depart_part}{destination}1"

    url = f"https://www.aviasales.ru/search/{search_code}?marker={TRAVEL_AVIASALES_MARKER}"
    return url

def flight_prices(origin, destination, depart_date, currency="rub", max_price=None):
    url = "https://api.travelpayouts.com/v2/prices/latest"

    params = {
        "origin": origin,
        "destination": destination,
        "depart_date": depart_date,  # YYYY-MM-DD
        "currency": currency,
        "limit": 1,
        "token": TRAVEL_TOKEN
    }

    print(f"flight_prices params: {params}")

    r = requests.get(url, params=params)
    print(f"status  {r}")
    try:
        data = r.json()
        print(f"data  {data}")
    except Exception as e:
        print(f"JSON error: {e}")
        return False

    if not data.get("data"):
        return False

    result = []

    for ticket in data["data"]:
        price = ticket.get("value")

        # фильтрация по цене
        if max_price is not None and price is not None and price > max_price:
            continue

        affiliate = create_affiliate_link(
            origin=ticket["origin"],
            destination=ticket["destination"],
            depart_date=ticket["depart_date"],
            return_date=None  # one-way
        )

        ticket["affiliate_url"] = affiliate
        result.append(ticket)

    return result if result else False


def search_flights(origin, destination, date_from, date_to, max_price=None):
    print(f"search_flights {origin} → {destination} | {date_from} - {date_to}")

    # если пришли строки — преобразуем
    if isinstance(date_from, str):
        date_from = datetime.strptime(date_from, "%Y-%m-%d").date()
    if isinstance(date_to, str):
        date_to = datetime.strptime(date_to, "%Y-%m-%d").date()

    all_flights = []
    current_date = date_from

    while current_date <= date_to:
        flights = flight_prices(
            origin=origin,
            destination=destination,
            depart_date=current_date.isoformat(),
            max_price=max_price
        )

        if flights:
            for f in flights:
                all_flights.append({
                    "price": f.get("value"),
                    "origin": f.get("origin"),
                    "destination": f.get("destination"),
                    "depart_date": f.get("depart_date"),
                    "gate": f.get("gate"),
                    "affiliate_url": f.get("affiliate_url")
                })

        current_date += timedelta(days=1)

    # сортировка по цене
    all_flights.sort(key=lambda x: x["price"] if x["price"] is not None else 10**9)

    return all_flights






if __name__ == "__main__":
    # test_flight_prices()
    # print(flight_prices(origin="MOW", destination="BKK", depart_date='2025-12-20', currency="rub", max_price=40000))
    print(get_tickets_aviasales(
        origin="MOW",
        destination="NHA",
        depart_date_from='2025-12-14',
        depart_date_to='2025-12-28',
        one_way=False,
        max_price=90000,
        return_days=16,
        return_flex_days=5,
    ))
    # [{'depart_date': '2026-06-07', 'origin': 'MOW', 'destination': 'BKK', 'gate': 'Kupi.com',
    #   'return_date': '2026-06-07', 'found_at': '2025-12-11T12:40:31', 'trip_class': 0, 'value': 66661,
    #   'number_of_changes': 2, 'duration': 2240, 'distance': 7058, 'show_to_affiliates': True, 'actual': True,
    #   'affiliate_url': None},

    # print(create_affiliate_link(origin="MOW", destination='BKK', depart_date='2026-01-01'))
    # print(get_data_airport(citi='Москва'))
# TRAVEL_TOKEN = os.getenv("TRAVEL_TOKEN")
# TRAVEL_AVIASALES_MARKER = os.getenv("TRAVEL_AVIASALES_MARKER")
# AVIASALES_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
#
# def make_affiliate_link(item):
#     base = "https://www.aviasales.ru"
#     link = item["link"]
#     if "?" in link:
#         return f"{base}{link}&marker={TRAVEL_AVIASALES_MARKER}"
#     else:
#         return f"{base}{link}?marker={TRAVEL_AVIASALES_MARKER}"
#
# def month_range(date_from, date_to):
#     """Возвращает список месяцев YYYY-MM"""
#     months = []
#     current = date_from.replace(day=1)
#     while current <= date_to:
#         months.append(current.strftime("%Y-%m"))
#         if current.month == 12:
#             current = current.replace(year=current.year + 1, month=1)
#         else:
#             current = current.replace(month=current.month + 1)
#     return months
#
#
# def parse_date(d: str) -> date:
#     return datetime.fromisoformat(d).date()
#
# def get_tickets_aviasales(
#     origin,
#     destination,
#     depart_date_from,
#     depart_date_to,
#     one_way=True,
#     max_price=None,
#     return_days=None,
#     return_flex_days=0,
#     currency="rub",
#     direct=False,
#     max_transfers = None,
#     trip_class = 0,  # 0 economy | 1 business | 2 first
# ):
#
#     def filter_ticket(data):
#         result = []
#
#         for item in data.get("data", []):
#             depart_at = datetime.fromisoformat(item["departure_at"]).date()
#
#             if not (depart_date_from <= depart_at <= depart_date_to):
#                 continue
#
#             return_at = None
#             if not one_way:
#                 if not item.get("return_at"):
#                     continue
#
#                 return_at = datetime.fromisoformat(item["return_at"]).date()
#                 expected_return = depart_at + timedelta(days=return_days)
#
#                 if abs((return_at - expected_return).days) > return_flex_days:
#                     continue
#
#             if max_price and item["price"] > max_price:
#                 continue
#
#             results.append({
#                 "price": item["price"],
#                 "origin": item.get("origin"),
#                 "origin_airport": item.get("origin_airport"),
#                 "destination": item.get("destination"),
#                 "destination_airport": item.get("destination_airport"),
#                 "depart_date": depart_at.strftime("%d.%m.%y"),
#                 "return_date": return_at.strftime("%d.%m.%y") if return_at else None,
#                 "airline": item.get("airline"),
#                 "flight_number": item.get("flight_number"),
#                 "transfers": item.get("transfers"),
#                 "duration": item.get("duration"),
#                 "duration_to": item.get("duration_to"),
#                 "duration_back": item.get("duration_back"),
#                 "return_transfers": item.get("return_transfers"),
#                 "affiliate_url": make_affiliate_link(item),
#             })
#
#         return result
#
#
#     results = []
#     departure_months = month_range(depart_date_from, depart_date_to)
#
#     for departure_month in departure_months:
#         params = {
#             "origin": origin,
#             "destination": destination,
#             "departure_at": departure_month,
#             "one_way": "true" if one_way else "false",
#             "sorting": "price",
#             "direct": "true" if direct else "false",
#             "cy": currency,
#             "limit": 100,
#             "token": TRAVEL_TOKEN,
#         }
#
#         r = requests.get(AVIASALES_URL, params=params, timeout=10)
#         if r.status_code != 200:
#             print(r)
#             continue
#
#         data = r.json()
#         print(data)
#         results.extend(filter_ticket(data))
#
#     return sorted(results, key=lambda x: x["price"])
#
#



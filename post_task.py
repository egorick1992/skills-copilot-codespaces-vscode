import argparse
import asyncio
from datetime import datetime

from db import async_session, Task, TaskStatus
from api import get_tickets_aviasales
from message import send_flight_public

# python3 post_task.py MOW BKK 2025-12-15 2026-12-30 40000 --return-days 14 --flex-days 3 --retry-interval 43200
# python3 post_task.py MOW BKK 2025-12-15 2026-12-30 40000

# python3 post_task.py MOW CXP 2025-12-20 2026-01-09 100000  --publish
def parse_args():
    parser = argparse.ArgumentParser(
        description="Создание или немедленная публикация задачи поиска авиабилетов"
    )

    # positional
    parser.add_argument("origin", help="Город вылета (например MOW)")
    parser.add_argument("destination", help="Город прилета (например BKK)")
    parser.add_argument("date_from", help="Дата начала (YYYY-MM-DD)")
    parser.add_argument("date_to", help="Дата окончания (YYYY-MM-DD)")
    parser.add_argument("max_price", type=int, help="Максимальная цена")

    # optional
    parser.add_argument("--max_transfers", type=int, default=0, help="Кол-во пересадок")
    parser.add_argument("--return-days", type=int, default=0, help="Количество дней возврата")
    parser.add_argument("--flex-days", type=int, default=0, help="Гибкость дат ± дни")
    parser.add_argument(
        "--retry-interval",
        type=int,
        default=86400,
        help="Интервал повторной проверки (сек)"
    )

    parser.add_argument(
        "--user-id",
        default="-1003460603210",
        help="ID пользователя или канала"
    )

    parser.add_argument(
        "--publish",
        action="store_true",
        help="Опубликовать сразу, не создавая задачу"
    )

    return parser.parse_args()


def parse_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Неверный формат даты: {date_str}, нужен YYYY-MM-DD")


async def main():
    args = parse_args()

    date_from = parse_date(args.date_from)
    date_to = parse_date(args.date_to)

    async with async_session() as session:
        if args.publish:
            flights = get_tickets_aviasales(
                origin=args.origin,
                destination=args.destination,
                depart_date_from=date_from,
                depart_date_to=date_to,
                max_price=args.max_price,
                return_days=args.return_days,
                return_flex_days =args.flex_days,
                max_transfers=args.max_transfers
            )

            if flights:
                await send_flight_public(args.user_id, flights=flights)
                print(f"✅ Публикация {args.origin}->{args.destination} выполнена")
            else:
                print("😔 Билеты не найдены")

        else:
            try:
                task = Task()
                # Устанавливаем атрибуты напрямую
                task.user_id = args.user_id
                task.origin = args.origin
                task.destination = args.destination
                task.date_from = args.date_from  # строки в ISO формате
                task.date_to = args.date_to  # строки в ISO формате
                task.max_price = args.max_price
                task.return_days = args.return_days if args.return_days > 0 else None
                task.flex_days = args.flex_days
                task.retry_interval = args.retry_interval
                task.max_transfers = args.max_transfers
                task.is_public = True
                task.status = TaskStatus.active

                session.add(task)
                await session.commit()
            except ValueError as e:
                print(e)

            print(f"✅ Публичный таск {args.origin}->{args.destination} создан")


if __name__ == "__main__":
    asyncio.run(main())

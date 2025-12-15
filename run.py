import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from db import Task, TaskStatus, async_session
from api import get_tickets_aviasales
from message import send_flight_public, send_flight_user

CHECK_INTERVAL = 300  # 20 минут
CHECK_LAST = 6000


async def monitor_tasks():
    while True:
        try:
            now = datetime.utcnow()
            async with async_session() as session:
                # Проверяем задачи done, которые нужно снова сделать active
                result_done = await session.execute(select(Task).where(Task.status == TaskStatus.done))
                tasks_done = result_done.scalars().all()
                for task_done in tasks_done:
                    if task_done.last_checked_at + timedelta(seconds=task_done.retry_interval) <= now:
                        task_done.status = TaskStatus.active

                # Проверяем активные задачи
                result_active = await session.execute(select(Task).where(Task.status == TaskStatus.active))
                tasks_active = result_active.scalars().all()
                for task in tasks_active:
                    date_to_obj = datetime.strptime(task.date_to, "%Y-%m-%d").date()
                    today = now.date()
                    if date_to_obj < today:
                        task.status = TaskStatus.closed
                        continue

                    if task.last_checked_at and now <= task.last_checked_at + timedelta(seconds=CHECK_LAST):
                        continue

                    try:
                        flights = get_tickets_aviasales(
                            origin=task.origin,
                            destination=task.destination,
                            depart_date_from=datetime.fromisoformat(task.date_from).date(),
                            depart_date_to=datetime.fromisoformat(task.date_to).date(),
                            max_price=task.max_price,
                            return_days=task.return_days or None,
                            return_flex_days=task.flex_days or 0,
                            max_transfers=task.max_transfers or None,
                            trip_class=task.trip_class or 0,  # 0 economy | 1 business | 2 first
                        )

                        task.last_checked_at = datetime.utcnow()

                        if flights:
                            if task.is_public:
                                await send_flight_public(task.user_id, flights, max_show = 1)
                            else:
                                await send_flight_user(task.user_id, flights, max_show = 5)
                            task.status = TaskStatus.done

                    except Exception as e:
                        logging.exception(f"Ошибка при проверке задачи {task.id}: {e}")

                await session.commit()

        except Exception as e:
            logging.exception(f"Ошибка в цикле monitor_tasks: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

# Запуск мониторинга в основном приложении
if __name__ == "__main__":
    asyncio.run(monitor_tasks())

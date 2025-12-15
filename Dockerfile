FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Создаем папку для базы данных
RUN mkdir -p /app/data

# Делаем скрипты исполняемыми
RUN chmod +x /app/*.py

# Точка входа - запускаем bash для интерактивного использования
CMD ["/bin/bash"]
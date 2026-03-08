FROM python:3.9-slim

# Instala dependências de sistema para Geoprocessamento e Banco de Dados
RUN apt-get update && apt-get install -y \
    libgeos-dev \
    libpq-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia e instala as dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código fonte
COPY . .

# Inicia o servidor usando a porta dinâmica do Cloud Run ($PORT)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
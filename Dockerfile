FROM python:3.9-slim

# Instala dependências de sistema para Geoprocessamento e Compilação
RUN apt-get update && apt-get install -y \
    libgeos-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia e instala as dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código do seu projeto para o container
COPY . .

# Inicia o servidor FastAPI
# O Cloud Run passará a porta automaticamente através da variável de ambiente $PORT
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
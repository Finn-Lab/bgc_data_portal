FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    python3-dev \
    libffi-dev \
    libssl-dev \
    make \
    git \
    libxrender1 \
    libxext6 \
    libsm6 \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 LTS for frontend build
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements-web.txt .
RUN pip install --upgrade pip && pip install -r requirements-web.txt

COPY . .

# Build the React frontend (outputs to /app/static/dashboard/)
WORKDIR /app/frontend
RUN npm install && npm run build
WORKDIR /app

EXPOSE 8000
ENV PYTHONUNBUFFERED=0

RUN python manage.py collectstatic --noinput || true

RUN chgrp -R 1347 /app && chmod -R g+w /app

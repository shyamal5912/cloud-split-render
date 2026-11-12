FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/streaming ./server/streaming
RUN useradd -m app
USER app
EXPOSE 9000
CMD ["python", "server/streaming/server.py", "--port", "9000"]

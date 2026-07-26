FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# 容器内无需打开浏览器，直接以 0.0.0.0 暴露端口
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

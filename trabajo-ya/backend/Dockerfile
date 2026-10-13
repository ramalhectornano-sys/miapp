FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY start.sh /app/start.sh
RUN chmod 755 /app/start.sh && useradd --system --uid 10001 backend
USER backend
EXPOSE 8000
CMD ["/app/start.sh"]

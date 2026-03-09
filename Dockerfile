FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ocr_chat_api.py ./

EXPOSE 7860

CMD [
  "streamlit",
  "run",
  "app.py",
  "--server.port=7860",
  "--server.address=0.0.0.0",
  "--server.enableCORS=false",
  "--server.enableXsrfProtection=false"
]

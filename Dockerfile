# Hugging Face Space (sdk: docker) runs Streamlit inside a container.
# The Streamlit hosted SDK was deprecated by HF; this is the official
# migration path and serves the same read-only app on port 7860.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY data data

EXPOSE 7860
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]

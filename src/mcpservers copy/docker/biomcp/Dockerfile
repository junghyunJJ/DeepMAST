FROM python:3.13-slim
RUN pip install --no-cache-dir biomcp-python==0.7.1
EXPOSE 8000
CMD ["biomcp", "run", "--mode", "streamable_http", "--host", "0.0.0.0", "--port", "8000"]

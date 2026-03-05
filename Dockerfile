FROM python:3.12-slim

WORKDIR /app

# Keep deps minimal + fast
RUN pip install --no-cache-dir fastapi uvicorn pyyaml jsonschema

# Copy the FastAPI app, schemas, dist, etc into the image
COPY app/ /app/

EXPOSE 8787

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]

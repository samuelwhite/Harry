FROM python:3.12-slim

WORKDIR /app

# Keep deps minimal + fast
RUN pip install --no-cache-dir fastapi uvicorn pyyaml jsonschema

# Copy the Python package root and its runtime siblings explicitly.
COPY app/app /app/app/
COPY app/schemas /app/schemas/
COPY app/dist /app/dist/
COPY app/harry /app/harry/
COPY app/capabilities.yml /app/capabilities.yml
COPY app/run_brain.py /app/run_brain.py

# Copy the installer/runtime source that feeds the served artifacts.
COPY agent/ /app/agent/
COPY installers/ /app/installers/
COPY downloads/ /app/downloads/
COPY scripts/ /app/scripts/

EXPOSE 8787

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]

FROM python:3.12-slim

WORKDIR /app

# Keep deps minimal + fast
RUN pip install --no-cache-dir fastapi uvicorn pyyaml jsonschema

# Copy the app plus the installer/runtime source that feeds the served artifacts.
COPY app/ /app/app/
COPY agent/ /app/agent/
COPY installers/ /app/installers/
COPY downloads/ /app/downloads/
COPY scripts/ /app/scripts/

# Keep the runtime-served Windows artifacts in sync with the current source tree.
RUN python /app/scripts/sync_windows_artifacts.py --root /app

EXPOSE 8787

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]

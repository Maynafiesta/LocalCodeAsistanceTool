FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml ./
COPY codeassist ./codeassist
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && useradd --uid 10001 --create-home assistant
USER assistant
EXPOSE 8080
# Exactly one worker: admission counters are process-local.
CMD ["uvicorn", "codeassist.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]

# Build context must be the repo root, e.g.:
#   docker build -f Backend/Dockerfile -t dtlab-backend .
# This is required because the backend invokes the OpenDSS -> pandapower
# conversion pipeline in ../Conversion/Nando_final as a subprocess
# (see Backend/main.py: NANDO_ROOT = Path(__file__).parent.parent / "Conversion" / "Nando_final").

FROM python:3.10.11-slim AS builder

# libpq-dev + gcc: needed to compile psycopg2 (non-binary) into the venv below.
# None of this ships in the final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY Backend/requirements.txt Backend/requirements.txt
RUN pip install --no-cache-dir -r Backend/requirements.txt


FROM python:3.10.11-slim

# libpq5: runtime client lib for psycopg2 (libpq-dev's compiler is not needed here)
# libgomp1: OpenMP runtime needed by numba/LightSim2Grid
# curl: container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY Backend Backend
COPY Conversion Conversion

WORKDIR /app/Backend

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

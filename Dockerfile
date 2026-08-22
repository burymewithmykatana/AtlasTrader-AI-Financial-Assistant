FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system atlas && adduser --system --ingroup atlas atlas

COPY pyproject.toml README.md ./

RUN python -m pip install --upgrade pip && python - <<'PY'
import subprocess
import sys
import tomllib

with open("pyproject.toml", "rb") as project_file:
    project = tomllib.load(project_file)

requirements = project["build-system"]["requires"] + project["project"]["dependencies"]
subprocess.check_call([sys.executable, "-m", "pip", "install", *requirements])
PY

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

RUN python -m pip install --no-deps --no-build-isolation .

USER atlas
EXPOSE 8000

CMD ["uvicorn", "atlas_trader.main:app", "--host", "0.0.0.0", "--port", "8000"]

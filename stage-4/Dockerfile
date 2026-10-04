FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace
COPY stage-2/requirements.txt stage-2/requirements.txt
RUN python -m pip install --no-cache-dir -r stage-2/requirements.txt

COPY stage-2/app stage-2/app
COPY stage-3/static stage-3/static

WORKDIR /workspace/stage-2
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

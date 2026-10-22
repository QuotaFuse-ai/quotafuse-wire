FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    QF_WIRE_DATA_DIR=/data \
    QF_WIRE_HOST=0.0.0.0

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY config ./config
COPY prompts ./prompts
COPY compatibility ./compatibility

RUN pip install --upgrade pip && pip install .

RUN mkdir -p /data/archive

EXPOSE 8790 8791

CMD ["qfw", "serve", "--host", "0.0.0.0", "--port", "8790"]

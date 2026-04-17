FROM ghcr.io/astral-sh/uv:alpine

WORKDIR /app

COPY . .

RUN uv sync --frozen

CMD ["uv", "run", "main.py"]
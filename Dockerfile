# syntax=docker/dockerfile:1.7
FROM python:3.15-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --prefix=/install .

FROM python:3.15-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /install /usr/local
COPY alembic.ini ./
COPY migrations ./migrations
USER app
EXPOSE 8080 9100
CMD ["python", "-m", "flightbot.bot"]

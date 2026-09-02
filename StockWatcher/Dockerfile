# Playwright's own image already carries the chromium system libraries, which
# are a long and easy-to-get-wrong list (libnss3, libatk, libasound2, ...).
# Starting from it is far more reliable than apt-getting them onto python:slim.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STOCKWATCHER_STATE_BACKEND=azure_table

WORKDIR /app

# Dependencies first: this layer is cached unless pyproject.toml changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[azure,browser]"

# Only chromium; the base image ships all three engines and the others are
# ~500MB of dead weight in a job that runs hourly.
RUN playwright install chromium

COPY config ./config

# The job writes nothing except (optionally) a local sqlite file.
RUN useradd --create-home --uid 10001 watcher \
    && mkdir -p /app/data \
    && chown -R watcher:watcher /app
USER watcher

ENTRYPOINT ["stockwatcher"]
CMD ["run"]

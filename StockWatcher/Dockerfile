# Playwright's own image already carries the chromium system libraries, which
# are a long and easy-to-get-wrong list (libnss3, libatk, libasound2, ...).
# Starting from it is far more reliable than apt-getting them onto python:slim.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

# Must match the base image tag above.  pyproject floats `playwright>=1.44`,
# and a newer resolve would expect a browser revision this image does not have.
ARG PLAYWRIGHT_VERSION=1.55.0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STOCKWATCHER_STATE_BACKEND=azure_table \
    STOCKWATCHER_ENABLE_BROWSER_STORES=1

WORKDIR /app

# Dependencies first: this layer is cached unless pyproject.toml changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[azure,browser]" \
    && pip install --no-cache-dir "playwright==${PLAYWRIGHT_VERSION}"

# Only chromium; the base image ships all three engines and the others are
# ~500MB of dead weight in a job that runs hourly.  Installs into
# PLAYWRIGHT_BROWSERS_PATH (/ms-playwright), which the base image sets, so the
# unprivileged user below can still read it.
RUN playwright install chromium

COPY config ./config

# The job writes nothing except (optionally) a local sqlite file.
RUN useradd --create-home --uid 10001 watcher \
    && mkdir -p /app/data \
    && chown -R watcher:watcher /app
USER watcher

ENTRYPOINT ["stockwatcher"]
CMD ["run"]

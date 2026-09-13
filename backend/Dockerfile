# Slim image for Render's free web-service tier. Multi-stage isn't needed
# here: there's no compilation step for this dependency set once we install
# build tools for psycopg2's C extension, and keeping a single stage keeps
# the Render build simple to reason about for a personal/portfolio deploy.
FROM python:3.12-slim

WORKDIR /app

# libpq-dev + gcc: required to build psycopg2 (not psycopg2-binary) wheels
# on some platforms; kept even though requirements.txt currently pins
# psycopg2-binary, so switching to the source package later doesn't also
# require touching this file.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render sets $PORT at runtime; default to 8000 for local `docker run`.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]

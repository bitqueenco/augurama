# Operator reference image; Docker build/native provider execution are release gates.
FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 director
WORKDIR /app
COPY requirements.lock ./
RUN pip install --requirement requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-deps . && mkdir -p /data && chown -R director:director /data
USER director
ENV DD_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8765
ENTRYPOINT ["dreamina-director"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]

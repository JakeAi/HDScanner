FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/hdscanner
COPY . .
# Preserve source-relative GraphQL files and use the validated UI version.
RUN pip install --no-cache-dir -e ".[dashboard]" "nicegui==3.16.0"

ENV PYTHONUNBUFFERED=1
WORKDIR /data
EXPOSE 8080
ENTRYPOINT ["hd"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]

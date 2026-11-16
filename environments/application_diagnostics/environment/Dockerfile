# taskforge dev container (Lattice API platform job runner)
FROM python:3.12.8-slim-bookworm@sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux procps curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.4.1 asciinema==2.4.0

WORKDIR /app
COPY app /app
RUN python -m taskforge.cli init-db --replace \
    && mkdir -p /opt/taskforge_pristine /var/lib/ops-observe/received \
    && cp data/taskforge.db /opt/taskforge_pristine/taskforge.db \
    && chmod -R 777 /var/lib/ops-observe

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["sleep", "infinity"]

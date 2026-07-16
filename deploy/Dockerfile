# BoardRoom backend + KiCad tooling in one container.
#
# Base: the official KiCad image (Ubuntu-based) — ships kicad-cli and the KiCad
# python bindings, which is exactly the risky part of containerizing this app.
# Target: Alibaba Cloud ECS (docker run) — too heavy for Function Compute.
#
# Build from the REPO ROOT:  docker build -f deploy/Dockerfile -t boardroom .
# Run:  docker run -p 8000:8000 -e DASHSCOPE_API_KEY=... -v boardroom-data:/data boardroom

FROM kicad/kicad:10.0

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip python3-venv git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer first so code edits don't re-install everything.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/backend/requirements.txt

# TODO(deploy-engineer): install the Seeed-Studio kicad-mcp-server into the same
# venv and set KICAD_MCP_COMMAND accordingly (mcp/client.py reads it).

COPY . /app

ENV PATH="/opt/venv/bin:${PATH}" \
    BOARDROOM_SESSIONS_DIR=/data/sessions \
    KICAD_CLI=/usr/bin/kicad-cli

RUN mkdir -p /data/sessions && chown -R kicad:kicad /data /app
USER kicad

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

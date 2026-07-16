# Deploying BoardRoom to Alibaba Cloud

Target: one **ECS instance** running the Docker image (KiCad + backend). Function
Compute was ruled out — the KiCad base image is too heavy for it.

## Image

```bash
# from the repo root
docker build -f deploy/Dockerfile -t boardroom .
docker run -d -p 8000:8000 \
  -e DASHSCOPE_API_KEY=$DASHSCOPE_API_KEY \
  -e OSS_ENDPOINT=... -e OSS_BUCKET=... \
  -e OSS_ACCESS_KEY_ID=... -e OSS_ACCESS_KEY_SECRET=... \
  -v boardroom-data:/data boardroom
```

OSS vars are optional — without them reviews stay on the instance disk
(`/data/sessions`); with them, signed reviews and renders are published to the
bucket via [alibaba/oss_store.py](alibaba/oss_store.py).

## One-time Alibaba Cloud setup (manual, Lluís)

1. ECS instance (2 vCPU / 4 GB is enough; Ubuntu 22.04; open port 8000 in the
   security group, restrict source to your IP for the hackathon).
2. Install Docker (`curl -fsSL https://get.docker.com | sh`).
3. RAM user with an AccessKey scoped to one OSS bucket; export the four OSS_* vars.
4. `git clone https://github.com/lluisestape-upc/boardroom && cd boardroom`, then the
   build/run commands above.

## Verify

```bash
./deploy/smoke.sh http://<ecs-ip>:8000 /app/fixtures/stickhub
```

`fixtures/` is gitignored — copy a KiCad project onto the instance (or into the
image) before running smoke against it. The KiCad demo "stickhub" board is the
standard smoke target.

## Deployment proof (submission requirement)

Linkable code files demonstrating Alibaba Cloud services:
- [deploy/alibaba/oss_store.py](alibaba/oss_store.py) — OSS via the official `oss2` SDK
- [backend/app/qwen_client.py](../backend/app/qwen_client.py) — Qwen models via
  Model Studio (DashScope international endpoint)

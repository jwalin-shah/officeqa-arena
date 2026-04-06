FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    curl git rsync wget ca-certificates gnupg lsb-release \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu jammy stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# uv (handles Python version install too)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Goose binary (x86_64 linux)
RUN curl -fsSL https://github.com/block/goose/releases/download/v1.29.1/goose-x86_64-unknown-linux-gnu.tar.bz2 \
    -o /tmp/goose.tar.bz2 \
    && tar -xjf /tmp/goose.tar.bz2 -C /usr/local/bin \
    && rm /tmp/goose.tar.bz2

COPY arena-cli-latest.tar.gz /tmp/arena-cli-latest.tar.gz
COPY bootstrap.sh /workspace/bootstrap.sh
RUN chmod +x /workspace/bootstrap.sh

# Suppress arena auto-update (0.1.0 tar is incompatible with 0.3.2 harbor)
ENV ARENA_NO_AUTO_UPDATE=1

WORKDIR /workspace

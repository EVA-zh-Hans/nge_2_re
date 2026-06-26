FROM --platform=linux/amd64 ubuntu:24.04

LABEL maintainer="xeonliu"
LABEL description="Translation Project for PSP Evangelion 2: Another Cases with custom PSPDEV setup"

# Avoid prompts from apt
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
# pngquant is for image pallette conversion
# openssl is for pspdecrypt
# freetype is for pgftool
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    pkgconf \
    libreadline8 \
    libusb-0.1-4 \
    libgpgme11 \
    libarchive-tools \
    fakeroot \
    curl \
    wget \
    unzip \
    git \
    python3 \
    python3-pip \
    python3-venv \
    bash \
    pngquant \
    openssl \
    xdelta3 \
    zlib1g-dev \
    libssl-dev \
    libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash pspdev \
    && apt-get update && apt-get install -y sudo \
    && usermod -aG sudo pspdev \
    && echo "pspdev ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER pspdev
WORKDIR /home/pspdev

# Download and install PSP SDK
RUN wget -O pspdev-ubuntu-x86_64.tar.gz "https://github.com/pspdev/pspdev/releases/latest/download/pspdev-ubuntu-latest-x86_64.tar.gz" \
    && tar -xvf pspdev-ubuntu-x86_64.tar.gz \
    && rm pspdev-ubuntu-x86_64.tar.gz

# Set up environment variables
ENV PSPDEV="/home/pspdev/pspdev"
ENV PATH="$PATH:$PSPDEV/bin"

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Verify PSP SDK installation
RUN psp-config --pspdev-path

# Set up shell environment
RUN echo 'export PSPDEV="$HOME/pspdev"' >> ~/.bashrc \
    && echo 'export PATH="$PATH:$PSPDEV/bin"' >> ~/.bashrc \
    && echo 'source $HOME/.local/bin/env' >> ~/.bashrc

# Default command
CMD ["/bin/bash"]

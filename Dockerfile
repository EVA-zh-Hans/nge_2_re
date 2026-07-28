ARG PSPDEV_BUILD_PLATFORM=linux/amd64
FROM --platform=${PSPDEV_BUILD_PLATFORM} ubuntu:24.04

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
ENV PATH="/home/pspdev/.local/bin:$PSPDEV/bin:$PATH"

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Cache the fixed staff-roll fonts in the image. The repository is bind-mounted
# at runtime, so the workflow copies these assets into the mounted workspace.
RUN mkdir -p /home/pspdev/nge-assets/font /tmp/font-downloads \
    && curl -fL --retry 3 \
        -o /tmp/font-downloads/SourceHanSerifSC.zip \
        https://github.com/adobe-fonts/source-han-serif/releases/download/2.003R/09_SourceHanSerifSC.zip \
    && curl -fL --retry 3 \
        -o /tmp/font-downloads/SourceHanSansSC.zip \
        https://github.com/adobe-fonts/source-han-sans/releases/download/2.005R/09_SourceHanSansSC.zip \
    && serif_font_entry="$(unzip -Z1 /tmp/font-downloads/SourceHanSerifSC.zip | sed -n '/\/SourceHanSerifSC-Heavy\.otf$/p' | head -n 1)" \
    && sans_font_entry="$(unzip -Z1 /tmp/font-downloads/SourceHanSansSC.zip | sed -n '/\/SourceHanSansSC-Medium\.otf$/p' | head -n 1)" \
    && test -n "$serif_font_entry" \
    && test -n "$sans_font_entry" \
    && unzip -p /tmp/font-downloads/SourceHanSerifSC.zip "$serif_font_entry" \
        > /home/pspdev/nge-assets/font/SourceHanSerifSC-Heavy.otf \
    && unzip -p /tmp/font-downloads/SourceHanSansSC.zip "$sans_font_entry" \
        > /home/pspdev/nge-assets/font/SourceHanSansSC-Medium.otf \
    && test -s /home/pspdev/nge-assets/font/SourceHanSerifSC-Heavy.otf \
    && test -s /home/pspdev/nge-assets/font/SourceHanSansSC-Medium.otf \
    && rm -rf /tmp/font-downloads

# Pre-install the locked Python dependencies into a shared virtual environment.
# The project source stays bind-mounted and does not need to enter this layer.
ENV UV_PROJECT_ENVIRONMENT="/home/pspdev/.venv"
COPY --chown=pspdev:pspdev pyproject.toml uv.lock /home/pspdev/project-deps/
RUN cd /home/pspdev/project-deps \
    && uv sync --locked --no-install-project \
    && uv cache clean

# Verify PSP SDK installation
RUN psp-config --pspdev-path

# Set up shell environment
RUN echo 'export PSPDEV="$HOME/pspdev"' >> ~/.bashrc \
    && echo 'export PATH="$PATH:$PSPDEV/bin"' >> ~/.bashrc \
    && echo 'source $HOME/.local/bin/env' >> ~/.bashrc

# Default command
CMD ["/bin/bash"]

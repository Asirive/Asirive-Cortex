# Building Picamera2 from Source for Python 3.11 on RPi5 (Debian Trixie)

Since Debian Trixie defaults to Python 3.13, and ProjectCortex requires Python 3.11 (for PyTorch), we cannot use the system `python3-picamera2` package. We must build `picamera2` from source and link it to our custom Python 3.11 environment.

## Prerequisites

Ensure you are using the **Pyenv Python 3.11** environment.

```bash
# Verify python version
source ~/ProjectCortex/.venv/bin/activate
python --version  # Should be 3.11.x
```

## Step 1: Install Build Dependencies

We need the system build tools and the development headers for `libcamera`.

```bash
sudo apt update
sudo apt install -y \
    meson \
    ninja-build \
    pkg-config \
    libcamera-dev \
    libcamera-tools \
    python3-dev \
    git \
    build-essential
```

## Step 2: Clone Picamera2 Repository

Clone the official Raspberry Pi repository.

```bash
cd ~
git clone https://github.com/raspberrypi/picamera2.git
cd picamera2
```

## Step 3: Configure Build for Python 3.11

We need to tell `meson` to use our **Virtual Environment's Python** instead of the system default (3.13).

1.  **Activate your venv** (if not already):
    ```bash
    source ~/ProjectCortex/.venv/bin/activate
    ```

2.  **Configure with Meson**:
    The trick is pointing `python.platlibdir` to our venv's site-packages.

    ```bash
    # Wipe any old build
    rm -rf build

    # Configure
    meson setup build \
        -Dpython=enabled \
        -Dinstall-libcamera=disabled \
        -Dauto_features=enabled \
        --prefix=$(python -c "import sys; print(sys.prefix)") \
        --libdir=$(python -c "import sys; print('lib/python3.11/site-packages')")
    ```

    *Note: If meson complains about missing dependencies, double check `sudo apt install libcamera-dev`.*

## Step 4: Compile and Install

```bash
# Compile
ninja -C build

# Install (This installs directly into your ACTIVE venv because of the prefix above)
ninja -C build install
```

## Step 5: Verify

```bash
cd ~/ProjectCortex
python -c "import picamera2; print('Picamera2 Version:', picamera2.__version__)"
```

If this prints a version number without error, **SUCCESS!**

## Step 6: Run ProjectCortex

```bash
python -m rpi5 all
```

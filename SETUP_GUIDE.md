# 🛠️ AutoYT Setup Guide

The automated setup encountered issues because your Python version (**3.14**) is too new and lacks pre-compiled binary packages for critical dependencies like `psycopg2`, `numpy`, and `opencv`.

To run this project, please follow these steps:

## 1. Install Prerequisites

### 🐍 Python 3.11 or 3.12 (Critical)
*   Python 3.14 is currently in pre-release/early stages. Most data science and database libraries do not support it yet without complex compilation tools.
*   **Action**: Download and install **Python 3.11** from [python.org](https://www.python.org/downloads/windows/).

### 🐳 Docker Desktop
*   Required for the Database (PostgreSQL) and Message Broker (Redis).
*   **Action**: Download and install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/).

### 🎬 FFmpeg
*   Required for video editing capabilities.
*   **Action**: 
    *   Install via Winget: `winget install Gyan.FFmpeg`
    *   Or download from [ffmpeg.org](https://ffmpeg.org/download.html), extract it, and add the `bin` folder to your System PATH.

## 2. Reset Environment

Once you have installed Python 3.11:

1.  **Delete the existing virtual environment**:
    ```powershell
    Remove-Item -Recurse -Force .venv
    ```

2.  **Create a new one with Python 3.11**:
    ```powershell
    py -3.11 -m venv .venv
    ```

3.  **Install Dependencies**:
    ```powershell
    .\.venv\Scripts\python -m pip install -r requirements.txt
    ```

## 3. Start Infrastructure

with Docker Desktop running:

```powershell
docker compose up -d postgres redis
```

## 4. Run the Application

You can now start the API and Worker as described in the README:

**Start API:**
```powershell
.\.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Start Worker:**
```powershell
.\.venv\Scripts\celery -A workers.celery_app worker --loglevel=INFO --pool=solo
```
*(Note: `--pool=solo` is often required for Celery on Windows)*

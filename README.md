# 🤖 AutoYT: AI-Powered Shorts Factory

AutoYT is an enterprise-grade automation pipeline that autonomously discovers, analyzes, and edits viral short-form content. It leverages GPT-4 Vision for content analysis and a custom video composition engine to generate high-retention "Ranking" videos for YouTube Shorts, TikTok, and Instagram Reels.

## 🚀 Architecture

The system operates on a 4-Stage Pipeline:

1.  **Discovery Layer** (`/api/v1/discovery`)
    *   Scrapes trending content from YouTube, TikTok, and Instagram using Apify and official APIs.
    *   Calculates "Viral Score" based on view velocity and engagement rates.
2.  **Analysis Layer** (`/api/v1/analysis`)
    *   **Intelligent Downloader:** Batched `yt-dlp` wrapper with rate limiting.
    *   **Vision Engine:** Uses GPT-4 Vision to analyze frames for quality, safety, watermarks, and viral potential.
    *   **Selection Logic:** Weighted ranking algorithm (`Trending * 0.4 + Quality * 0.3 + Relevance * 0.3`).
3.  **Editing Layer** (`/api/v1/rendering`)
    *   **Audio Engine:** Google Cloud TTS with "Audio Ducking" (auto-lowering music volume).
    *   **Compositor:** MoviePy-based engine for 9:16 resizing, dynamic overlays, and transitions.
4.  **Delivery**
    *   Production-ready MP4 output with comprehensive metadata.

---

## 🛠️ Prerequisites

*   **Python 3.10+**
*   **Redis** (Message Broker for Celery)
*   **PostgreSQL** (Application Database)
*   **FFmpeg** (Required for video processing)
    *   *Windows:* Download build and add `bin` to System PATH.
    *   *Linux/Mac:* `apt install ffmpeg` / `brew install ffmpeg`

## ⚙️ Configuration

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-org/autoyt.git
    cd autoyt
    ```

2.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Environment Setup:**
    Create a `.env` file in the root directory (copy from `.env.example`).
    ```env
    # Core
    APP_ENV=production
    DEBUG=False
    SECRET_KEY=your_production_secret

    # Database & Redis
    DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/autoyt
    REDIS_URL=redis://localhost:6379/0

    # AI & APIs
    OPENAI_API_KEY=sk-...
    GOOGLE_APPLICATION_CREDENTIALS=path/to/google-creds.json
    APIFY_API_TOKEN=apify_...
    ```

---

## 🚦 Startup Instructions

For a production environment, we recommend running the API and Workers as separate services (e.g., using `supervisord`, `systemd`, or Docker).

### 1. Start Support Services
Ensure Redis and PostgreSQL are running.
```bash
# Example (if using Docker for infra)
docker run -d -p 6379:6379 redis
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=pass postgres
```

### 2. Start the API Server
The API handles incoming requests and triggers background jobs.
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```
*   `--workers 4`: Scale based on CPU cores for production.

### 3. Start the Celery Worker
The worker processes heavy tasks (Discovery, Analysis, Rendering).
```bash
celery -A workers.celery_app worker --loglevel=INFO --concurrency=2 -Q discovery,analysis,video_processing
```
*   `--concurrency`: Limit based on available RAM (Video rendering is memory intensive).
*   `-Q`: Listen to specific queues.

---

## 📡 API Usage Guide

### 1. Create a Job
Initialize a new automation campaign.
```http
POST /api/v1/jobs/
{
  "niche": "gaming",
  "config": {
    "platforms": ["youtube", "tiktok"],
    "min_views": 10000
  }
}
```

### 2. Trigger Discovery
Start finding content.
```http
POST /api/v1/discovery/{job_id}/start
```

### 3. Trigger Analysis
Analyze found videos with GPT-4.
```http
POST /api/v1/analysis/{job_id}/analyze
{
  "niche": "gaming highlights",
  "limit": 20
}
```

### 4. Render Video
Compile the top results into a Ranking Short.
```http
POST /api/v1/rendering/{job_id}/render
{
  "voice_style": "energetic",
  "include_intro": true
}
```

---

## 📦 Directory Structure

```
autoyt/
├── app/
│   ├── api/            # FastAPI Routes
│   ├── core/           # Core Logic (Analyzer, Editor, Downloader)
│   ├── models/         # SQLAlchemy Models
│   ├── schemas/        # Pydantic Models
│   └── tasks/          # Celery Distributed Tasks
├── workers/            # Celery App Configuration
├── storage/            # Local Asset Storage (Temp/Output)
└── tests/              # Pytest Suite
```

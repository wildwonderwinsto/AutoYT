# 🧪 AutoYT Testing Guide

This guide explains how to test the AutoYT application to verify it's functioning correctly.

## 📋 Prerequisites Check

Before testing, ensure you have:

1. **Python 3.11 or 3.12** (not 3.14 - see SETUP_GUIDE.md)
2. **Docker Desktop** running (for PostgreSQL and Redis)
3. **FFmpeg** installed and in PATH
4. **Virtual environment** activated
5. **Dependencies installed**: `pip install -r requirements.txt`
6. **Environment file** (`.env`) configured

## 🔍 Quick Health Check

### 1. Check Python Version
```powershell
python --version
# Should show Python 3.11.x or 3.12.x (NOT 3.14)
```

### 2. Check Dependencies
```powershell
python -c "import fastapi, celery, sqlalchemy, openai; print('Dependencies OK')"
```

### 3. Check FFmpeg
```powershell
ffmpeg -version
# Should show FFmpeg version info
```

### 4. Check Infrastructure (Docker)
```powershell
docker ps
# Should show postgres and redis containers running
```

## 🧪 Running Tests

### Unit Tests (Pytest)

Run all tests:
```powershell
pytest
```

Run specific test file:
```powershell
pytest tests/test_analyzer.py
pytest tests/test_discovery.py
pytest tests/test_editor.py
```

Run with coverage:
```powershell
pytest --cov=app --cov-report=html
```

Run with verbose output:
```powershell
pytest -v
```

### Integration Tests

Test database connection:
```powershell
python -c "from app.core.database import engine; import asyncio; asyncio.run(engine.connect())"
```

Test Redis connection:
```powershell
python -c "import redis; r = redis.from_url('redis://localhost:6379/0'); print(r.ping())"
```

## 🚀 Manual API Testing

### 1. Start the Services

**Terminal 1 - Start Infrastructure:**
```powershell
docker compose up -d postgres redis
```

**Terminal 2 - Start API Server:**
```powershell
.\.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 3 - Start Celery Worker:**
```powershell
.\.venv\Scripts\celery -A workers.celery_app worker --loglevel=INFO --pool=solo
```

### 2. Test Health Endpoint

Open browser or use curl:
```powershell
# Browser: http://localhost:8000/health
# Or PowerShell:
Invoke-RestMethod -Uri http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "environment": "development",
  "version": "1.0.0"
}
```

### 3. Test API Documentation

Open browser:
```
http://localhost:8000/docs
```

This shows the interactive Swagger UI where you can test all endpoints.

### 4. Test Job Creation

Using PowerShell:
```powershell
$body = @{
    user_id = "test_user"
    job_type = "discovery"
    config = @{
        platforms = @("youtube")
        min_views = 1000
    }
} | ConvertTo-Json

Invoke-RestMethod -Uri http://localhost:8000/api/v1/jobs/ -Method POST -Body $body -ContentType "application/json"
```

Or using curl (if available):
```bash
curl -X POST "http://localhost:8000/api/v1/jobs/" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "job_type": "discovery",
    "config": {
      "platforms": ["youtube"],
      "min_views": 1000
    }
  }'
```

### 5. Test Celery Worker

Test if Celery worker is responding:
```powershell
python -c "from workers.celery_app import celery_app; result = celery_app.send_task('celery.ping'); print(result.get(timeout=10))"
```

Expected output: `"pong"`

## 🔧 Troubleshooting Tests

### Common Issues

1. **Import Errors**
   - Check virtual environment is activated
   - Verify all dependencies installed: `pip install -r requirements.txt`

2. **Database Connection Errors**
   - Ensure PostgreSQL is running: `docker ps | findstr postgres`
   - Check DATABASE_URL in `.env` file
   - Test connection: `docker exec -it shorts_db psql -U user -d shorts_automation`

3. **Redis Connection Errors**
   - Ensure Redis is running: `docker ps | findstr redis`
   - Test connection: `docker exec -it shorts_redis redis-cli ping`

4. **Celery Worker Not Starting**
   - On Windows, use `--pool=solo` flag
   - Check Redis is accessible
   - Verify CELERY_BROKER_URL in config

5. **FFmpeg Not Found**
   - Install FFmpeg: `winget install Gyan.FFmpeg`
   - Add to PATH or restart terminal

6. **Python Version Issues**
   - Python 3.14 is too new - use 3.11 or 3.12
   - Recreate venv: `Remove-Item -Recurse -Force .venv; py -3.11 -m venv .venv`

## 📊 Test Coverage

To see what's tested and what's not:

```powershell
pytest --cov=app --cov-report=term-missing
```

This shows:
- Which files are covered
- Which lines are missing coverage
- Overall coverage percentage

## 🎯 End-to-End Testing Workflow

1. **Create a Job**
   ```powershell
   POST /api/v1/jobs/
   ```

2. **Start Discovery**
   ```powershell
   POST /api/v1/discovery/{job_id}/start
   ```

3. **Check Job Status**
   ```powershell
   GET /api/v1/jobs/{job_id}
   ```

4. **Trigger Analysis**
   ```powershell
   POST /api/v1/analysis/{job_id}/analyze
   ```

5. **Render Video**
   ```powershell
   POST /api/v1/rendering/{job_id}/render
   ```

## 🔍 Monitoring Tests

### Check Logs

API logs appear in terminal where uvicorn is running.

Celery logs appear in terminal where worker is running.

### Use Flower (Celery Monitor)

Start Flower:
```powershell
.\.venv\Scripts\celery -A workers.celery_app flower --port=5555
```

Open browser: `http://localhost:5555`

This shows:
- Active tasks
- Task history
- Worker status
- Task results

## ✅ Verification Checklist

- [ ] Python version is 3.11 or 3.12
- [ ] All dependencies installed
- [ ] FFmpeg is in PATH
- [ ] Docker containers running (postgres, redis)
- [ ] API server starts without errors
- [ ] Celery worker starts without errors
- [ ] Health endpoint returns 200
- [ ] API docs accessible at /docs
- [ ] Can create a job via API
- [ ] Celery ping task works
- [ ] Unit tests pass
- [ ] Database connection works
- [ ] Redis connection works

## 🐛 Debug Mode

Enable debug logging by setting in `.env`:
```
DEBUG=True
LOG_LEVEL=DEBUG
```

This provides more detailed error messages and stack traces.

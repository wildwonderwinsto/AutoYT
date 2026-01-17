# 🎨 Frontend UI Guide

## Quick Start

The frontend is a **Next.js** application that provides the user interface for AutoYT.

### Access the UI

1. **Open your web browser**
2. **Navigate to**: `http://localhost:3000`

The frontend should be running on port 3000.

## Starting the Frontend

If the frontend isn't running, start it with:

```powershell
cd frontend
npm run dev
```

Or from the project root:
```powershell
cd frontend; npm run dev
```

The server will start on `http://localhost:3000` by default.

## Current Frontend Status

The frontend is currently a **basic Next.js template**. It shows:
- A welcome page with Next.js branding
- Links to documentation and templates

## What's Available

### Frontend Structure
```
frontend/
├── src/
│   └── app/
│       ├── page.tsx      # Main page
│       ├── layout.tsx    # Root layout
│       └── globals.css   # Global styles
└── public/              # Static assets
```

### API Integration

The frontend can connect to the backend API at:
- **API Base URL**: `http://localhost:8000`
- **API Docs**: `http://localhost:8000/docs`

## Next Steps for Frontend Development

To build a proper UI for AutoYT, you'll want to:

1. **Create pages for:**
   - Dashboard/Home page
   - Job creation and management
   - Video discovery browser
   - Analysis results viewer
   - Video rendering/editing interface

2. **Add API integration:**
   - Connect to `http://localhost:8000/api/v1/` endpoints
   - Use fetch or axios for API calls
   - Handle async operations and loading states

3. **Add UI components:**
   - Forms for job creation
   - Tables for listing jobs/videos
   - Video previews
   - Progress indicators for long-running tasks

## Development Commands

```powershell
# Start development server (with hot reload)
cd frontend
npm run dev

# Build for production
npm run build

# Start production server
npm start

# Run linter
npm run lint
```

## Troubleshooting

### Port Already in Use
If port 3000 is already in use:
```powershell
# Kill the process using port 3000 (Windows)
netstat -ano | findstr :3000
taskkill /PID <PID> /F

# Or run on a different port
cd frontend
$env:PORT=3001; npm run dev
```

### Dependencies Not Installed
```powershell
cd frontend
npm install
```

### Backend Not Connected
Make sure the backend API is running:
```powershell
# Check if API is running
Invoke-RestMethod -Uri http://localhost:8000/health

# If not, start it:
.\.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Current Services

When everything is running, you should have:

- ✅ **Frontend**: `http://localhost:3000` (Next.js)
- ✅ **Backend API**: `http://localhost:8000` (FastAPI)
- ✅ **API Docs**: `http://localhost:8000/docs` (Swagger UI)
- ✅ **Database**: PostgreSQL on port 5432
- ✅ **Redis**: Port 6379
- ⚠️ **Celery Worker**: Start manually if needed

## Example: Connecting Frontend to Backend

In your React components, you can fetch data like this:

```typescript
// Example API call from frontend
const response = await fetch('http://localhost:8000/api/v1/jobs/');
const jobs = await response.json();
```

Or create an API client:

```typescript
// lib/api.ts
const API_BASE = 'http://localhost:8000/api/v1';

export async function getJobs() {
  const res = await fetch(`${API_BASE}/jobs/`);
  return res.json();
}

export async function createJob(jobData: any) {
  const res = await fetch(`${API_BASE}/jobs/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(jobData),
  });
  return res.json();
}
```

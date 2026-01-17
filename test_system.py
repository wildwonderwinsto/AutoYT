#!/usr/bin/env python3
"""
Quick system verification script for AutoYT
Run this to check if the system is properly configured and functioning.
"""

import sys
import asyncio
from pathlib import Path

def check_python_version():
    """Check Python version"""
    version = sys.version_info
    print(f"[OK] Python version: {version.major}.{version.minor}.{version.micro}")
    
    if version.major != 3 or version.minor < 11:
        print("[WARN] Python 3.11+ recommended (you have 3.14 which may have compatibility issues)")
        return False
    if version.minor == 14:
        print("[WARN] Python 3.14 is too new - use 3.11 or 3.12 for best compatibility")
        return False
    return True

def check_imports():
    """Check if critical imports work"""
    print("\nChecking dependencies...")
    critical_imports = [
        ("fastapi", "FastAPI"),
        ("celery", "Celery"),
        ("sqlalchemy", "SQLAlchemy"),
        ("redis", "Redis"),
        ("openai", "OpenAI"),
        ("moviepy", "MoviePy"),
        ("cv2", "OpenCV"),
        ("numpy", "NumPy"),
    ]
    
    failed = []
    for module_name, display_name in critical_imports:
        try:
            __import__(module_name)
            print(f"  [OK] {display_name}")
        except ImportError as e:
            print(f"  [FAIL] {display_name} - {e}")
            failed.append(display_name)
    
    return len(failed) == 0

def check_env_file():
    """Check if .env file exists"""
    env_path = Path(".env")
    if env_path.exists():
        print("\n[OK] .env file found")
        return True
    else:
        print("\n[WARN] .env file not found - you may need to create one")
        return False

async def check_database():
    """Check database connection"""
    print("\nChecking database connection...")
    try:
        from app.core.database import engine
        from sqlalchemy import text
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            print("  [OK] Database connection successful")
            return True
    except Exception as e:
        print(f"  [FAIL] Database connection failed: {e}")
        print("  -> Make sure PostgreSQL is running: docker compose up -d postgres")
        return False

def check_redis():
    """Check Redis connection"""
    print("\nChecking Redis connection...")
    try:
        import redis
        from app.config import settings
        r = redis.from_url(settings.redis_url)
        r.ping()
        print("  [OK] Redis connection successful")
        return True
    except Exception as e:
        print(f"  [FAIL] Redis connection failed: {e}")
        print("  -> Make sure Redis is running: docker compose up -d redis")
        return False

def check_celery():
    """Check Celery configuration"""
    print("\nChecking Celery configuration...")
    try:
        from workers.celery_app import celery_app
        print(f"  [OK] Celery app configured")
        print(f"  -> Broker: {celery_app.conf.broker_url}")
        print(f"  -> Backend: {celery_app.conf.result_backend}")
        return True
    except Exception as e:
        print(f"  [FAIL] Celery configuration error: {e}")
        return False

def check_ffmpeg():
    """Check if FFmpeg is available"""
    print("\nChecking FFmpeg...")
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            print(f"  [OK] FFmpeg found: {version_line}")
            return True
        else:
            print("  [FAIL] FFmpeg not found in PATH")
            return False
    except FileNotFoundError:
        print("  [FAIL] FFmpeg not found in PATH")
        print("  -> Install FFmpeg: winget install Gyan.FFmpeg")
        return False
    except Exception as e:
        print(f"  [FAIL] Error checking FFmpeg: {e}")
        return False

def check_storage_dirs():
    """Check if storage directories exist"""
    print("\nChecking storage directories...")
    storage_path = Path("storage")
    required_dirs = ["raw_videos", "processed", "temp"]
    
    all_exist = True
    for dir_name in required_dirs:
        dir_path = storage_path / dir_name
        if dir_path.exists():
            print(f"  [OK] {dir_name}/")
        else:
            print(f"  [INFO] {dir_name}/ - will be created on first use")
            dir_path.mkdir(parents=True, exist_ok=True)
    
    return True

async def main():
    """Run all checks"""
    print("=" * 60)
    print("AutoYT System Verification")
    print("=" * 60)
    
    results = []
    
    # Basic checks
    results.append(("Python Version", check_python_version()))
    results.append(("Dependencies", check_imports()))
    results.append(("Environment File", check_env_file()))
    results.append(("Storage Directories", check_storage_dirs()))
    results.append(("FFmpeg", check_ffmpeg()))
    
    # Service checks (may fail if services not running)
    results.append(("Database", await check_database()))
    results.append(("Redis", check_redis()))
    results.append(("Celery Config", check_celery()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} - {name}")
    
    print(f"\n{passed}/{total} checks passed")
    
    if passed == total:
        print("\n[SUCCESS] All checks passed! System is ready.")
        return 0
    else:
        print("\n[WARN] Some checks failed. Review the output above.")
        print("See TESTING_GUIDE.md for troubleshooting help.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

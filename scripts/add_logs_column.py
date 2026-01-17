"""Add logs column to jobs table if it doesn't exist."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import engine


async def add_logs_column():
    """Add logs column to jobs table."""
    try:
        async with engine.begin() as conn:
            # Check if column exists
            result = await conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='jobs' AND column_name='logs'
            """))
            
            if result.fetchone() is None:
                print("Adding 'logs' column to jobs table...")
                await conn.execute(text("""
                    ALTER TABLE jobs 
                    ADD COLUMN logs JSONB DEFAULT '[]'::jsonb
                """))
                print("[OK] Column added successfully!")
            else:
                print("[OK] Column 'logs' already exists")
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        print("\nMake sure:")
        print("1. PostgreSQL is running")
        print("2. Database connection is configured correctly")
        print("3. You have permissions to alter the jobs table")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(add_logs_column())

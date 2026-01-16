#!/usr/bin/env python3
"""Database initialization script"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import engine, Base
from app.models import (
    Job,
    PlatformContent,
    VideoAnalysis,
    DownloadedVideo,
    OutputVideo,
    CustomizationPreset
)


async def init_database():
    """Initialize the database by creating all tables"""
    print("Initializing database...")
    
    async with engine.begin() as conn:
        # Drop all tables (use with caution in production!)
        # await conn.run_sync(Base.metadata.drop_all)
        
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
    
    print("Database initialized successfully!")
    print("\nCreated tables:")
    for table in Base.metadata.tables:
        print(f"  - {table}")


async def verify_connection():
    """Verify database connection"""
    from sqlalchemy import text
    
    print("Verifying database connection...")
    
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            print("Database connection verified!")
            return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False


async def main():
    """Main initialization routine"""
    # Verify connection first
    if not await verify_connection():
        print("\nPlease ensure PostgreSQL is running and DATABASE_URL is configured correctly.")
        sys.exit(1)
    
    # Initialize database
    await init_database()
    
    # Close engine
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

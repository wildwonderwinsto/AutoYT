#!/usr/bin/env python3
"""Seed test data into the database"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
from uuid import uuid4
import random

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import async_session_maker
from app.models.job import Job, JobStatus
from app.models.platform_content import PlatformContent


async def seed_jobs():
    """Seed sample jobs"""
    jobs = [
        {
            "user_id": "test-user-1",
            "job_type": "ranking",
            "status": JobStatus.COMPLETED,
            "config": {
                "niche": "gaming",
                "platforms": ["youtube", "tiktok"],
                "timeframe": "24h",
                "max_videos": 100
            }
        },
        {
            "user_id": "test-user-1",
            "job_type": "compilation",
            "status": JobStatus.PENDING,
            "config": {
                "niche": "cooking",
                "platforms": ["instagram", "tiktok"],
                "timeframe": "7d",
                "max_videos": 50
            }
        },
        {
            "user_id": "test-user-2",
            "job_type": "ranking",
            "status": JobStatus.DISCOVERING,
            "config": {
                "niche": "fitness",
                "platforms": ["youtube"],
                "timeframe": "24h",
                "max_videos": 75
            }
        },
    ]
    
    async with async_session_maker() as session:
        for job_data in jobs:
            job = Job(**job_data)
            session.add(job)
        
        await session.commit()
        print(f"Seeded {len(jobs)} jobs")


async def seed_platform_content():
    """Seed sample platform content"""
    platforms = ["youtube", "tiktok", "instagram"]
    niches = ["gaming", "cooking", "fitness", "comedy", "travel"]
    
    content_items = []
    
    for i in range(50):
        platform = random.choice(platforms)
        niche = random.choice(niches)
        upload_date = datetime.utcnow() - timedelta(hours=random.randint(1, 72))
        
        content_items.append(PlatformContent(
            platform=platform,
            platform_video_id=f"{platform}_{uuid4().hex[:8]}",
            url=f"https://example.com/{platform}/video/{uuid4().hex[:12]}",
            title=f"Amazing {niche} content #{i+1}",
            description=f"This is a sample {niche} video for testing purposes.",
            author=f"creator_{random.randint(1, 20)}",
            views=random.randint(1000, 5000000),
            likes=random.randint(100, 100000),
            comments=random.randint(10, 10000),
            duration_seconds=random.randint(15, 60),
            upload_date=upload_date,
            trending_score=random.uniform(0.3, 0.95),
            metadata={
                "niche": niche,
                "hashtags": [f"#{niche}", "#viral", "#shorts"]
            }
        ))
    
    async with async_session_maker() as session:
        for content in content_items:
            session.add(content)
        
        await session.commit()
        print(f"Seeded {len(content_items)} platform content items")


async def main():
    """Main seeding routine"""
    print("Seeding test data...")
    
    try:
        await seed_jobs()
        await seed_platform_content()
        print("\nTest data seeded successfully!")
    except Exception as e:
        print(f"Seeding failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

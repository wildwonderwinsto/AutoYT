"""Platform API client wrappers"""

from typing import Optional, Dict, Any, List
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import structlog

from app.config import settings

logger = structlog.get_logger()


class YouTubeClient:
    """YouTube Data API client wrapper"""
    
    BASE_URL = "https://www.googleapis.com/youtube/v3"
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.youtube_api_key
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def search_videos(
        self,
        query: str,
        max_results: int = 50,
        video_type: str = "video",
        video_duration: str = "short",
        order: str = "viewCount"
    ) -> List[Dict[str, Any]]:
        """Search for videos with filters"""
        params = {
            "part": "snippet",
            "q": query,
            "type": video_type,
            "videoDuration": video_duration,
            "order": order,
            "maxResults": min(max_results, 50),
            "key": self.api_key
        }
        
        response = await self.client.get(
            f"{self.BASE_URL}/search",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        
        return data.get("items", [])
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_video_details(
        self,
        video_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """Get detailed information for videos"""
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids),
            "key": self.api_key
        }
        
        response = await self.client.get(
            f"{self.BASE_URL}/videos",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        
        return data.get("items", [])
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_channel_videos(
        self,
        channel_id: str,
        max_results: int = 50
    ) -> List[Dict[str, Any]]:
        """Get videos from a specific channel"""
        # First, get the uploads playlist
        params = {
            "part": "contentDetails",
            "id": channel_id,
            "key": self.api_key
        }
        
        response = await self.client.get(
            f"{self.BASE_URL}/channels",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        
        if not data.get("items"):
            return []
        
        uploads_playlist = data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        
        # Get videos from playlist
        params = {
            "part": "snippet",
            "playlistId": uploads_playlist,
            "maxResults": min(max_results, 50),
            "key": self.api_key
        }
        
        response = await self.client.get(
            f"{self.BASE_URL}/playlistItems",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        
        return data.get("items", [])
    
    async def get_trending(
        self,
        region_code: str = "US",
        category_id: str = None
    ) -> List[Dict[str, Any]]:
        """Get trending videos"""
        params = {
            "part": "snippet,statistics",
            "chart": "mostPopular",
            "regionCode": region_code,
            "maxResults": 50,
            "key": self.api_key
        }
        
        if category_id:
            params["videoCategoryId"] = category_id
        
        response = await self.client.get(
            f"{self.BASE_URL}/videos",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        
        return data.get("items", [])


class ApifyClient:
    """Apify API client for social media scraping"""
    
    BASE_URL = "https://api.apify.com/v2"
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.apify_api_key
        self.client = httpx.AsyncClient(timeout=120.0)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    async def run_actor(
        self,
        actor_id: str,
        input_data: Dict[str, Any],
        wait_for_finish: bool = True
    ) -> Dict[str, Any]:
        """Run an Apify actor and optionally wait for completion"""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        response = await self.client.post(
            f"{self.BASE_URL}/acts/{actor_id}/runs",
            json=input_data,
            headers=headers
        )
        response.raise_for_status()
        run_data = response.json()
        
        run_id = run_data["data"]["id"]
        
        if not wait_for_finish:
            return run_data
        
        # Poll for completion
        import asyncio
        max_attempts = 60
        for _ in range(max_attempts):
            status_response = await self.client.get(
                f"{self.BASE_URL}/acts/{actor_id}/runs/{run_id}",
                headers=headers
            )
            status_data = status_response.json()
            
            status = status_data["data"]["status"]
            if status in ["SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"]:
                break
            
            await asyncio.sleep(2)
        
        return status_data
    
    async def get_dataset_items(
        self,
        dataset_id: str,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get items from a dataset"""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        response = await self.client.get(
            f"{self.BASE_URL}/datasets/{dataset_id}/items",
            params={"limit": limit},
            headers=headers
        )
        response.raise_for_status()
        
        return response.json()
    
    async def scrape_tiktok_hashtag(
        self,
        hashtag: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Scrape TikTok videos by hashtag"""
        result = await self.run_actor(
            "clockworks/tiktok-scraper",
            {
                "hashtags": [hashtag],
                "resultsPerPage": limit,
                "shouldDownloadVideos": False
            }
        )
        
        if result["data"]["status"] == "SUCCEEDED":
            dataset_id = result["data"]["defaultDatasetId"]
            return await self.get_dataset_items(dataset_id, limit)
        
        return []
    
    async def scrape_instagram_hashtag(
        self,
        hashtag: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Scrape Instagram reels by hashtag"""
        result = await self.run_actor(
            "apify/instagram-scraper",
            {
                "hashtags": [hashtag],
                "resultsLimit": limit
            }
        )
        
        if result["data"]["status"] == "SUCCEEDED":
            dataset_id = result["data"]["defaultDatasetId"]
            items = await self.get_dataset_items(dataset_id, limit)
            # Filter to video content only
            return [item for item in items if item.get("type") == "Video"]
        
        return []


class S3Client:
    """AWS S3 client wrapper for storage operations"""
    
    def __init__(self):
        import boto3
        
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region
        )
        self.bucket = settings.aws_s3_bucket
    
    def upload_file(
        self,
        local_path: str,
        s3_key: str,
        content_type: str = "video/mp4"
    ) -> str:
        """Upload a file to S3"""
        self.s3.upload_file(
            local_path,
            self.bucket,
            s3_key,
            ExtraArgs={"ContentType": content_type}
        )
        
        return f"s3://{self.bucket}/{s3_key}"
    
    def download_file(
        self,
        s3_key: str,
        local_path: str
    ) -> str:
        """Download a file from S3"""
        self.s3.download_file(self.bucket, s3_key, local_path)
        return local_path
    
    def get_presigned_url(
        self,
        s3_key: str,
        expires_in: int = 3600
    ) -> str:
        """Generate a presigned URL for temporary access"""
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": s3_key},
            ExpiresIn=expires_in
        )
    
    def delete_file(self, s3_key: str) -> bool:
        """Delete a file from S3"""
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=s3_key)
            return True
        except Exception as e:
            logger.error("Failed to delete S3 object", key=s3_key, error=str(e))
            return False

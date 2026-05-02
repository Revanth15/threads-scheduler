import httpx
from typing import Optional
from app.config import settings
import logging

logger = logging.getLogger(__name__)

THREADS_API_BASE = "https://graph.threads.net/v1.0"

class ThreadsAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        self.message = message
        self.status_code = status_code
        super().__init__(message)

class ThreadsClient:
    def __init__(self):
        self.access_token = settings.THREADS_ACCESS_TOKEN
        self.user_id = settings.THREADS_USER_ID
        self.base_url = THREADS_API_BASE

    async def create_text_post(self, text: str) -> dict:
        """Step 1: Create a media container for a text post."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/{self.user_id}/threads",
                params={
                    "media_type": "TEXT",
                    "text": text,
                    "access_token": self.access_token,
                }
            )
            data = response.json()
            if response.status_code != 200:
                raise ThreadsAPIError(
                    f"Failed to create container: {data.get('error', {}).get('message', 'Unknown error')}",
                    response.status_code
                )
            return data  # returns {"id": "container_id"}

    async def publish_post(self, container_id: str) -> dict:
        """Step 2: Publish the media container."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/{self.user_id}/threads_publish",
                params={
                    "creation_id": container_id,
                    "access_token": self.access_token,
                }
            )
            data = response.json()
            if response.status_code != 200:
                raise ThreadsAPIError(
                    f"Failed to publish: {data.get('error', {}).get('message', 'Unknown error')}",
                    response.status_code
                )
            return data  # returns {"id": "post_id"}

    async def post_text(self, text: str) -> str:
        """Full flow: create container then publish. Returns post ID."""
        container = await self.create_text_post(text)
        container_id = container["id"]
        result = await self.publish_post(container_id)
        post_id = result["id"]
        logger.info(f"Successfully posted to Threads. Post ID: {post_id}")
        return post_id

    async def get_post_insights(self, post_id: str) -> dict:
        """Fetch insights/metrics for a specific post."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/{post_id}/insights",
                params={
                    "metric": "views,likes,replies,reposts,quotes",
                    "access_token": self.access_token,
                }
            )
            data = response.json()
            if response.status_code != 200:
                error_message = data.get("error", {}).get("message", "Unknown error")
                if "Application does not have permission for this action" in error_message:
                    error_message = (
                        "Failed to fetch insights: Meta denied access to the insights endpoint. "
                        "Your Threads access token must include `threads_manage_insights` "
                        "(in addition to `threads_basic`), and the Threads account must be "
                        "authorized for this app. If the app is still in Development mode, "
                        "the account must be added as an app role/tester before generating "
                        "a new access token."
                    )
                raise ThreadsAPIError(
                    error_message,
                    response.status_code
                )
            return self._parse_insights(data)

    def _parse_insights(self, data: dict) -> dict:
        metrics = {"views": 0, "likes": 0, "replies": 0, "reposts": 0, "quotes": 0}
        for item in data.get("data", []):
            name = item.get("name")
            values = item.get("values", [])
            if name in metrics and values:
                metrics[name] = values[0].get("value", 0)
        return metrics

    async def get_user_profile(self) -> dict:
        """Get basic user profile info."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/{self.user_id}",
                params={
                    "fields": "id,username,name,threads_profile_picture_url,threads_biography",
                    "access_token": self.access_token,
                }
            )
            data = response.json()
            if response.status_code != 200:
                raise ThreadsAPIError(f"Failed to get profile: {data}")
            return data

    async def test_connection(self) -> bool:
        """Test if the API credentials are valid."""
        try:
            await self.get_user_profile()
            return True
        except ThreadsAPIError:
            return False

threads_client = ThreadsClient()

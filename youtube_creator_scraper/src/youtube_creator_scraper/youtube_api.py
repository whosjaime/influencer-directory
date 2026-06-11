from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode

import requests


class YouTubeAPIError(RuntimeError):
    pass


class YouTubeQuotaExceeded(YouTubeAPIError):
    pass


class YouTubeClient:
    """Small wrapper around the YouTube Data API v3."""

    BASE_URL = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key: Optional[str] = None, sleep_seconds: float = 0.05) -> None:
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        if not self.api_key:
            raise YouTubeAPIError("Missing YouTube API key. Set YOUTUBE_API_KEY before running.")
        self.sleep_seconds = sleep_seconds
        self.quota_exceeded = False

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.quota_exceeded:
            return {"items": []}
        params = {**params, "key": self.api_key}
        url = f"{self.BASE_URL}/{path}?{urlencode(params, doseq=True)}"
        response = requests.get(url, timeout=30)
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        if response.status_code == 429 or "rateLimitExceeded" in response.text or "Quota exceeded" in response.text:
            self.quota_exceeded = True
            raise YouTubeQuotaExceeded(f"YouTube quota exceeded: {response.text[:500]}")
        if response.status_code >= 400:
            raise YouTubeAPIError(f"YouTube API error {response.status_code}: {response.text[:500]}")
        return response.json()

    def search_channels(self, query: str, max_results: int = 50, page_token: Optional[str] = None) -> Dict[str, Any]:
        return self._get(
            "search",
            {
                "part": "snippet",
                "type": "channel",
                "q": query,
                "maxResults": min(max_results, 50),
                "pageToken": page_token or "",
                "safeSearch": "strict",
                "relevanceLanguage": "en",
            },
        )

    def search_recent_videos_for_channel(self, channel_id: str, max_results: int = 25) -> List[Dict[str, Any]]:
        """Fallback recent-upload lookup using YouTube search.list by channelId."""
        data = self._get(
            "search",
            {
                "part": "snippet",
                "type": "video",
                "channelId": channel_id,
                "order": "date",
                "maxResults": min(max_results, 50),
                "safeSearch": "strict",
            },
        )
        return data.get("items", [])

    def get_channels(self, channel_ids: Iterable[str]) -> List[Dict[str, Any]]:
        ids = [cid for cid in channel_ids if cid]
        results: List[Dict[str, Any]] = []
        for i in range(0, len(ids), 50):
            chunk = ids[i : i + 50]
            data = self._get(
                "channels",
                {
                    "part": "snippet,statistics,contentDetails,brandingSettings",
                    "id": ",".join(chunk),
                    "maxResults": 50,
                },
            )
            results.extend(data.get("items", []))
        return results

    def get_playlist_items(self, playlist_id: str, max_results: int = 25) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        while len(items) < max_results:
            try:
                data = self._get(
                    "playlistItems",
                    {
                        "part": "snippet,contentDetails",
                        "playlistId": playlist_id,
                        "maxResults": min(50, max_results - len(items)),
                        "pageToken": page_token or "",
                    },
                )
            except YouTubeAPIError as exc:
                if "playlistNotFound" in str(exc) or "cannot be found" in str(exc):
                    return []
                raise
            items.extend(data.get("items", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return items

    def get_videos(self, video_ids: Iterable[str]) -> List[Dict[str, Any]]:
        ids = [vid for vid in video_ids if vid]
        results: List[Dict[str, Any]] = []
        for i in range(0, len(ids), 50):
            chunk = ids[i : i + 50]
            data = self._get(
                "videos",
                {
                    "part": "snippet,statistics,contentDetails,status",
                    "id": ",".join(chunk),
                    "maxResults": 50,
                },
            )
            results.extend(data.get("items", []))
        return results

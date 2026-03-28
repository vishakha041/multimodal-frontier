"""
Reddit scraper agent.

Scrapes r/sanfrancisco and r/AskSF for posts about things to do,
events, recommendations, and local tips in San Francisco.

No API key or app registration required. Reddit exposes a public JSON
API for any subreddit at https://www.reddit.com/r/{sub}/{listing}.json
The only requirement is a descriptive User-Agent header.

Note: Devvit is Reddit's platform for building apps that run *inside*
Reddit (interactive posts, mini-games). It is not relevant here — we
only need to read public post data into an external system.

Cadence: daily (static agent)
"""

import logging

import aiohttp

from agents.base import BaseAgent
from config import cfg

logger = logging.getLogger(__name__)

# Public JSON API — no authentication required
_API_BASE = "https://www.reddit.com"

# r/AskSF blocks unauthenticated requests even for "hot" (403).
# r/sanfrancisco is larger and works without credentials.
_SUBREDDITS = ["sanfrancisco"]
# "top" with t=day is also blocked without auth — "hot" only.
_LISTINGS = ["hot"]
_LIMIT = 50

_ACTIVITY_KEYWORDS = {
    "things to do", "what to do", "recommend", "recommendation",
    "where to", "best", "visit", "tourist", "weekend", "activity",
    "event", "festival", "restaurant", "bar", "hike", "museum",
    "park", "tour", "concert", "show", "coffee", "food", "eat",
    "explore", "hidden gem", "must see", "locals",
}


class RedditAgent(BaseAgent):
    """Scrapes public Reddit posts about SF activities with no credentials.

    Uses Reddit's unauthenticated JSON API (reddit.com/r/sub/listing.json),
    which is freely accessible for public subreddits. No OAuth, no app
    registration, and no Devvit required.

    Filters posts by activity-related keywords in the title.

    Attributes:
        AGENT_ID: Unique identifier in aperture-nexus.
        IS_LIVE: False — runs once daily.
    """

    AGENT_ID = "reddit-agent"
    AGENT_NAME = "Reddit SF Community Agent"
    IS_LIVE = False
    INTERVAL_SECONDS = 86400  # daily

    async def fetch(self) -> list[dict]:
        """Fetch hot and top posts from r/sanfrancisco and r/AskSF.

        Returns:
            Deduplicated normalized records for activity-relevant posts.
        """
        headers = {
            # Reddit requires a descriptive User-Agent and blocks "top" without auth.
            # We use "hot" only (see _LISTINGS). The Accept header reduces 403 rate.
            "User-Agent": cfg.reddit_user_agent,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
        records: list[dict] = []

        async with aiohttp.ClientSession(headers=headers) as session:
            for subreddit in _SUBREDDITS:
                for listing in _LISTINGS:
                    batch = await self._fetch_listing(session, subreddit, listing)
                    records.extend(batch)

        # Deduplicate by Reddit post ID across subreddit/listing combinations
        seen: set[str] = set()
        unique = []
        for r in records:
            pid = (r.get("raw") or {}).get("id", "")
            if pid and pid not in seen:
                seen.add(pid)
                unique.append(r)

        logger.info("Reddit: fetched %d unique posts", len(unique))
        return unique

    async def _fetch_listing(
        self, session: aiohttp.ClientSession, subreddit: str, listing: str
    ) -> list[dict]:
        """Fetch one listing page from the public Reddit JSON API."""
        url = f"{_API_BASE}/r/{subreddit}/{listing}.json"
        params: dict = {"limit": _LIMIT}
        if listing == "top":
            params["t"] = "day"  # top posts from the past 24 h

        try:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.warning("Reddit: failed r/%s/%s: %s", subreddit, listing, e)
            return []

        posts = data.get("data", {}).get("children", [])
        return [
            self._to_record(child["data"], subreddit)
            for child in posts
            if child.get("kind") == "t3" and self._is_relevant(child.get("data", {}))
        ]

    @staticmethod
    def _is_relevant(post: dict) -> bool:
        """Return True if the post title contains an activity-related keyword."""
        title = post.get("title", "").lower()
        return any(kw in title for kw in _ACTIVITY_KEYWORDS)

    def _to_record(self, post: dict, subreddit: str) -> dict:
        title = post.get("title", "")
        score = post.get("score", 0)
        comments = post.get("num_comments", 0)
        selftext = (post.get("selftext") or "")[:500]

        content = f"[r/{subreddit}] {title}"
        if selftext and selftext not in ("[removed]", "[deleted]"):
            content += f" — {selftext}"
        content += f" (↑{score}, {comments} comments)"

        return self.normalize(
            source="reddit",
            content=content,
            category="community_recommendation",
            title=title,
            url=f"https://reddit.com{post.get('permalink', '')}",
            raw={
                "id": post.get("id"),
                "subreddit": subreddit,
                "score": score,
                "num_comments": comments,
                "author": post.get("author"),
                "created_utc": post.get("created_utc"),
                "flair": post.get("link_flair_text"),
            },
        )

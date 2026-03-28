"""SF City Intelligence scraper agents."""

from agents.sf311 import SF311Agent
from agents.yelp import YelpAgent
from agents.reddit import RedditAgent
from agents.sf_mta import SFMTAAgent
from agents.five_one_one import FiveOneOneAgent
from agents.airnow import AirNowAgent
from agents.mapillary import MapillaryAgent
from agents.wikimedia import WikimediaAgent
from agents.inat import iNaturalistAgent

__all__ = [
    # Text / data agents
    "SF311Agent",
    "YelpAgent",
    "RedditAgent",
    "SFMTAAgent",
    "FiveOneOneAgent",
    "AirNowAgent",
    # Image agents (Yelp also captures photos as URL refs)
    "MapillaryAgent",
    "WikimediaAgent",
    "iNaturalistAgent",
]

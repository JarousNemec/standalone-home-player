"""Pydantic modely pro request body / typované odpovědi."""
from typing import Literal, Optional

from pydantic import BaseModel


class PlayRequest(BaseModel):
    # "playlist"/"album" = konečná fronta (na konci naváže autoradio),
    # "radio"/"song" = rovnou stanice ze seed videa (nekonečné doplňování).
    source: Literal["playlist", "album", "radio", "song"]
    id: str
    startIndex: int = 0


class QueueAddRequest(BaseModel):
    videoId: str
    title: str = ""
    artists: str = ""
    album: Optional[str] = None
    duration: Optional[int] = None
    thumbnail: Optional[str] = None

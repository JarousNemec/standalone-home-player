"""Pydantic modely pro request body / typované odpovědi."""
from typing import Literal, Optional

from pydantic import BaseModel

LikeStatus = Literal["LIKE", "DISLIKE", "INDIFFERENT"]
RepeatMode = Literal["off", "all", "one"]


class TrackModel(BaseModel):
    """Track dict, jak ho posílá klient zpět (tvar z ytmusic.normalize_track)."""
    videoId: str
    title: str = ""
    artists: str = ""
    artistId: Optional[str] = None
    album: Optional[str] = None
    albumId: Optional[str] = None
    duration: Optional[int] = None
    thumbnail: Optional[str] = None
    likeStatus: LikeStatus = "INDIFFERENT"
    setVideoId: Optional[str] = None


class PlayRequest(BaseModel):
    # "playlist"/"album"/"liked"/"library"/"tracks" = konečná fronta (na konci
    # naváže autoradio), "radio"/"song" = rovnou stanice ze seed videa.
    source: Literal["playlist", "album", "radio", "song", "liked", "library", "tracks"]
    id: str = ""
    startIndex: int = 0
    shuffle: bool = False
    tracks: Optional[list[TrackModel]] = None   # jen pro source="tracks"


class QueueAddRequest(TrackModel):
    # "next" = hned za právě hrající skladbu, "end" = na konec fronty
    position: Literal["end", "next"] = "end"


class QueueIndexRequest(BaseModel):
    index: int


class QueueMoveRequest(BaseModel):
    fromIndex: int
    toIndex: int


class QueueClearRequest(BaseModel):
    keepCurrent: bool = True


class ModeRequest(BaseModel):
    """Idempotentní setter — aplikují se jen pole, která nejsou None.

    Absolutní hodnoty schválně: klientů může být víc a dva slepé toggly
    poslané zároveň by se navzájem zrušily.
    """
    shuffle: Optional[bool] = None
    repeat: Optional[RepeatMode] = None
    autoRadio: Optional[bool] = None


class RateRequest(BaseModel):
    videoId: Optional[str] = None   # None → právě hrající skladba
    status: LikeStatus


class PlaylistCreateRequest(BaseModel):
    title: str
    description: str = ""
    videoIds: list[str] = []


class PlaylistItemsRequest(BaseModel):
    """Přidání stačí videoId; odebrání potřebuje i setVideoId."""
    items: list[TrackModel]

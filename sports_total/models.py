"""โครงสร้างข้อมูลที่ใช้ร่วมกัน"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Team:
    id: str
    name: str
    abbr: str = ""
    record: str = ""


@dataclass
class MarketTotal:
    """ราคาสกอร์รวมจากเจ้ามือ (ถ้า ESPN มีให้)"""
    provider: str
    line: float
    over_odds: float | None = None   # ราคาแบบอเมริกัน เช่น -110
    under_odds: float | None = None
    details: str = ""                # เช่น ราคาแฮนดิแคป "LAL -3.5"


@dataclass
class Match:
    event_id: str
    league_key: str
    start: datetime                   # UTC
    state: str                        # pre / in / post
    status_detail: str
    home: Team
    away: Team
    venue: str = ""
    markets: list[MarketTotal] = field(default_factory=list)
    home_score: float | None = None
    away_score: float | None = None

    @property
    def is_pregame(self) -> bool:
        return self.state == "pre"

    @property
    def market(self) -> MarketTotal | None:
        return self.markets[0] if self.markets else None


@dataclass
class GameResult:
    """ผลการแข่งขันที่จบแล้วของทีมหนึ่ง (มุมมองของทีมนั้น)"""
    event_id: str
    date: datetime
    team_id: str
    opponent: str
    is_home: bool
    points_for: float
    points_against: float

    @property
    def total(self) -> float:
        return self.points_for + self.points_against

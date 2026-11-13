"""ข้อมูลจำลองสำหรับทดลองใช้งานแบบออฟไลน์ (คำสั่ง `demo`) และใช้ในชุดทดสอบ

สร้าง JSON ในรูปแบบเดียวกับ ESPN แล้วส่งผ่านตัวแปลงจริง เพื่อให้ทดสอบทั้งระบบได้
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from .espn import parse_scoreboard, parse_team_schedule
from .leagues import League

DEMO_TEAMS = {
    "nba": [("1", "Boston Celtics", "BOS", 118, 109), ("2", "Denver Nuggets", "DEN", 116, 113),
            ("3", "Miami Heat", "MIA", 108, 107), ("4", "Sacramento Kings", "SAC", 120, 119)],
    "epl": [("11", "Arsenal", "ARS", 2.0, 0.8), ("12", "Brentford", "BRE", 1.5, 1.6),
            ("13", "Everton", "EVE", 1.0, 1.2), ("14", "Liverpool", "LIV", 2.2, 1.0)],
    "mlb": [("21", "Los Angeles Dodgers", "LAD", 5.2, 3.9), ("22", "Colorado Rockies", "COL", 4.3, 5.8),
            ("23", "Seattle Mariners", "SEA", 4.0, 3.6), ("24", "New York Yankees", "NYY", 5.0, 4.0)],
    "nfl": [("31", "Kansas City Chiefs", "KC", 25, 19), ("32", "Detroit Lions", "DET", 29, 23),
            ("33", "Cleveland Browns", "CLE", 17, 22), ("34", "Baltimore Ravens", "BAL", 27, 20)],
}
DEMO_LINES = {"nba": (229.5, 214.5), "epl": (2.5, 3.5), "mlb": (9.5, 7.5), "nfl": (47.5, 43.5)}


def _comp(team, home_away, score=None, schedule_style=False):
    tid, name, abbr, *_ = team
    c = {"homeAway": home_away, "team": {"id": tid, "displayName": name, "abbreviation": abbr}}
    if score is not None:
        c["score"] = ({"value": float(score), "displayValue": str(score)}
                      if schedule_style else str(score))
    return c


class DemoClient:
    """จำลอง ESPNClient: มี scoreboard() และ team_games() แบบเดียวกัน"""

    def __init__(self, league: League, seed: int = 2, now: datetime | None = None):
        self.league = league
        self.rng = random.Random(seed)
        self.now = now or datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)
        self.teams = DEMO_TEAMS[league.key]
        self.schedules = {t[0]: self._schedule(t) for t in self.teams}

    def _draw(self, mean: float) -> int:
        if self.league.sport in ("basketball", "football"):
            return max(0, round(self.rng.gauss(mean, mean * 0.11)))
        # นับแบบปัวซอง
        k, p, limit = 0, 1.0, pow(2.718281828, -mean)
        while True:
            p *= self.rng.random()
            if p <= limit:
                return k
            k += 1

    def _schedule(self, team) -> dict:
        events = []
        others = [t for t in self.teams if t[0] != team[0]]
        for i in range(12):
            opp = others[i % len(others)]
            home = i % 2 == 0
            pf = self._draw((team[3] + opp[4]) / 2)
            pa = self._draw((opp[3] + team[4]) / 2)
            dt = self.now - timedelta(days=3 * (i + 1))
            me = _comp(team, "home" if home else "away", pf, True)
            them = _comp(opp, "away" if home else "home", pa, True)
            events.append({
                "id": f"{team[0]}-{i}", "date": dt.strftime("%Y-%m-%dT%H:%MZ"),
                "competitions": [{"competitors": [me, them],
                                  "status": {"type": {"state": "post", "completed": True}}}],
            })
        # นัดในอนาคต (ต้องถูกตัดออก)
        events.append({"id": f"{team[0]}-f", "date": (self.now + timedelta(days=2)).isoformat(),
                       "competitions": [{"competitors": [_comp(team, "home"), _comp(others[0], "away")],
                                         "status": {"type": {"state": "pre", "completed": False}}}]})
        return {"requestedSeason": {"year": 2026}, "events": events}

    def scoreboard_json(self) -> dict:
        t = self.teams
        events = []
        for idx, ((h, a), line) in enumerate(zip(((t[0], t[1]), (t[2], t[3])), DEMO_LINES[self.league.key])):
            events.append({
                "id": f"demo{idx + 1}",
                "date": (self.now + timedelta(hours=1 + idx * 3)).strftime("%Y-%m-%dT%H:%MZ"),
                "status": {"type": {"state": "pre", "completed": False, "shortDetail": "ยังไม่เริ่ม"}},
                "competitions": [{
                    "competitors": [_comp(h, "home"), _comp(a, "away")],
                    "venue": {"fullName": f"{h[1]} Arena"},
                    "odds": [{"provider": {"name": "DemoBook"}, "overUnder": line,
                              "overOdds": -110, "underOdds": -110, "details": f"{h[2]} -3.5"}],
                }],
            })
        return {"events": events}

    def scoreboard(self, league, day=None, days=1):
        return parse_scoreboard(self.scoreboard_json(), league.key)

    def team_games(self, league, team_id, before=None, want=10):
        games = parse_team_schedule(self.schedules[team_id], team_id)
        games = [g for g in games if before is None or g.date < before]
        return sorted(games, key=lambda g: g.date, reverse=True)

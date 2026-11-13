"""การตั้งค่าลีกที่รองรับ และพารามิเตอร์ของโมเดลสกอร์รวมสำหรับแต่ละลีก

ค่าเฉลี่ย (team_avg) คือคะแนนเฉลี่ยต่อทีมต่อเกมโดยประมาณ ใช้เป็น "ค่าตั้งต้น" (prior)
เมื่อข้อมูลของทีมยังน้อย ปรับแก้ได้ตามฤดูกาลจริง
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ชนิดกีฬา
BASKETBALL = "basketball"
SOCCER = "soccer"
BASEBALL = "baseball"
AMERICAN_FOOTBALL = "football"

SPORT_NAMES_TH = {
    BASKETBALL: "บาสเกตบอล",
    SOCCER: "ฟุตบอล",
    BASEBALL: "เบสบอล",
    AMERICAN_FOOTBALL: "อเมริกันฟุตบอล",
}

# โมเดลการกระจายของสกอร์รวม
NORMAL = "normal"      # คะแนนเยอะ (บาส, อเมริกันฟุตบอล) -> แจกแจงปกติ
POISSON = "poisson"    # ประตูฟุตบอล -> ปัวซองต่อทีม
NEGBIN = "negbin"      # รันเบสบอล -> ทวินามลบ (กระจายมากกว่าปัวซอง)


@dataclass(frozen=True)
class League:
    key: str                 # ชื่อย่อที่ใช้ในคำสั่ง เช่น nba, epl
    sport: str               # path ชนิดกีฬาของ ESPN
    slug: str                # path ลีกของ ESPN
    name_th: str
    model: str
    team_avg: float          # คะแนนเฉลี่ยต่อทีมต่อเกม (prior)
    total_sd: float = 0.0    # ส่วนเบี่ยงเบนมาตรฐานของสกอร์รวม (โมเดล normal)
    home_adv: float = 0.0    # สัดส่วนที่ทีมเหย้าทำคะแนนเพิ่ม/ทีมเยือนลดลง
    dispersion: float = 0.0  # พารามิเตอร์ r ของทวินามลบ (เบสบอล)
    prior_games: float = 5.0  # น้ำหนักของค่าตั้งต้น (จำนวนเกมเสมือน)
    line_step: float = 0.0   # ระยะห่างของไลน์ที่แสดงเพิ่มเติม
    default_lines: tuple[float, ...] = ()
    scoreboard_params: dict = field(default_factory=dict)

    @property
    def unit_th(self) -> str:
        return {SOCCER: "ประตู", BASEBALL: "รัน"}.get(self.sport, "แต้ม")

    @property
    def sport_th(self) -> str:
        return SPORT_NAMES_TH[self.sport]


def _bb(key, slug, name, avg, sd, home=0.012, step=5.0, params=None):
    return League(key, BASKETBALL, slug, name, NORMAL, avg, total_sd=sd, home_adv=home,
                  line_step=step, prior_games=4.0, scoreboard_params=params or {})


def _fb(key, slug, name, avg=1.38, home=0.10):
    return League(key, SOCCER, slug, name, POISSON, avg, home_adv=home, prior_games=6.0,
                  default_lines=(1.5, 2.5, 3.5))


def _af(key, slug, name, avg, sd, params=None):
    return League(key, AMERICAN_FOOTBALL, slug, name, NORMAL, avg, total_sd=sd, home_adv=0.025,
                  line_step=3.0, prior_games=3.0, scoreboard_params=params or {})


LEAGUES: dict[str, League] = {lg.key: lg for lg in [
    # บาสเกตบอล
    _bb("nba", "nba", "NBA", 114.5, 18.0),
    _bb("wnba", "wnba", "WNBA", 82.0, 15.0),
    _bb("ncaab", "mens-college-basketball", "NCAA บาสชาย", 72.5, 15.5, home=0.02,
        params={"groups": "50", "limit": "400"}),
    _bb("ncaaw", "womens-college-basketball", "NCAA บาสหญิง", 66.0, 15.0, home=0.02,
        params={"groups": "50", "limit": "400"}),
    # ฟุตบอล
    _fb("epl", "eng.1", "พรีเมียร์ลีก อังกฤษ", 1.42),
    _fb("championship", "eng.2", "แชมเปียนชิพ อังกฤษ", 1.30),
    _fb("laliga", "esp.1", "ลาลีกา สเปน", 1.30),
    _fb("seriea", "ita.1", "เซเรียอา อิตาลี", 1.35),
    _fb("bundesliga", "ger.1", "บุนเดสลีกา เยอรมนี", 1.55),
    _fb("ligue1", "fra.1", "ลีกเอิง ฝรั่งเศส", 1.40),
    _fb("eredivisie", "ned.1", "เอเรอดิวิซี เนเธอร์แลนด์", 1.55),
    _fb("ucl", "uefa.champions", "ยูฟ่า แชมเปียนส์ลีก", 1.50, home=0.08),
    _fb("uel", "uefa.europa", "ยูฟ่า ยูโรปาลีก", 1.40, home=0.08),
    _fb("mls", "usa.1", "MLS สหรัฐฯ", 1.50),
    _fb("jleague", "jpn.1", "เจลีก ญี่ปุ่น", 1.30),
    _fb("thaileague", "tha.1", "ไทยลีก 1", 1.40),
    # เบสบอล
    League("mlb", BASEBALL, "mlb", "MLB", NEGBIN, 4.45, home_adv=0.02, dispersion=3.8,
           prior_games=8.0, default_lines=(7.5, 8.5, 9.5)),
    League("ncaabase", BASEBALL, "college-baseball", "NCAA เบสบอล", NEGBIN, 6.5, home_adv=0.03,
           dispersion=3.0, prior_games=6.0, default_lines=(10.5, 12.5, 14.5)),
    # อเมริกันฟุตบอล
    _af("nfl", "nfl", "NFL", 22.5, 13.5),
    _af("ncaaf", "college-football", "NCAA อเมริกันฟุตบอล", 28.0, 16.5,
        params={"groups": "80", "limit": "300"}),
]}


def get_league(key: str) -> League:
    """รับชื่อย่อลีก หรือรูปแบบ `soccer:xxx.1` เพื่อใช้ลีกฟุตบอลใดก็ได้ของ ESPN"""
    k = key.strip().lower()
    if k in LEAGUES:
        return LEAGUES[k]
    if k.startswith("soccer:"):
        slug = k.split(":", 1)[1]
        return _fb(k, slug, f"ฟุตบอล ({slug})")
    raise KeyError(
        f"ไม่รู้จักลีก '{key}' — ใช้คำสั่ง `leagues` เพื่อดูรายชื่อ "
        "หรือใช้ soccer:<รหัสลีก ESPN> เช่น soccer:por.1"
    )

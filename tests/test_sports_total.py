import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

from sports_total import stats
from sports_total.analyzer import TeamForm, TotalAnalyzer
from sports_total.cli import main
from sports_total.demo import DemoClient
from sports_total.espn import parse_scoreboard, parse_team_schedule, season_year
from sports_total.leagues import LEAGUES, get_league
from sports_total.models import Match, Team


class StatsTests(unittest.TestCase):
    def test_distributions_sum_to_one(self):
        d = stats.distribution(lambda k: stats.poisson_pmf(k, 1.4), 15)
        self.assertAlmostEqual(sum(d), 1.0, places=9)
        nb = stats.distribution(lambda k: stats.negbin_pmf(k, 4.5, 3.8), 40)
        mean = sum(k * p for k, p in enumerate(nb))
        var = sum((k - mean) ** 2 * p for k, p in enumerate(nb))
        self.assertAlmostEqual(mean, 4.5, delta=0.05)
        self.assertAlmostEqual(var, 4.5 + 4.5 ** 2 / 3.8, delta=0.3)  # กระจายมากกว่าปัวซอง

    def test_line_probs(self):
        o, u, p = stats.normal_line_probs(220, 18, 220.5)
        self.assertAlmostEqual(o + u, 1.0)
        self.assertEqual(p, 0.0)
        o, u, p = stats.normal_line_probs(220, 18, 220)
        self.assertGreater(p, 0)
        self.assertAlmostEqual(o, u, places=9)
        dist = [0.1, 0.2, 0.3, 0.4]
        self.assertEqual(stats.discrete_line_probs(dist, 1.5), (0.7, 0.30000000000000004, 0.0))
        o, u, p = stats.discrete_line_probs(dist, 2)
        self.assertAlmostEqual((o, u, p), (0.4, 0.3, 0.3))

    def test_odds_and_weights(self):
        self.assertAlmostEqual(stats.american_to_decimal(-110), 1.9090909, places=6)
        self.assertAlmostEqual(stats.american_to_decimal(150), 2.5)
        self.assertAlmostEqual(stats.weighted_mean([10, 0], 1), 10 / 1.5)
        self.assertEqual(stats.weighted_mean([4, 6], 0), 5)


SCOREBOARD = {"events": [
    {"id": "1", "date": "2026-11-14T00:30Z",
     "status": {"type": {"state": "pre", "shortDetail": "11/13 - 7:30 PM EST"}},
     "competitions": [{
         "venue": {"fullName": "TD Garden"},
         "competitors": [
             {"homeAway": "home", "score": "0", "team": {"id": "2", "displayName": "Boston Celtics",
                                                          "abbreviation": "BOS"},
              "records": [{"type": "total", "summary": "8-3"}]},
             {"homeAway": "away", "score": "0", "team": {"id": "7", "displayName": "Denver Nuggets",
                                                          "abbreviation": "DEN"}}],
         "odds": [{"provider": {"name": "ESPN BET"}, "details": "BOS -4.5",
                   "total": {"over": {"close": {"line": "o226.5", "odds": "-112"}},
                             "under": {"close": {"line": "u226.5", "odds": "EVEN"}}}}]}]},
    {"id": "2", "date": "2026-11-13T23:00Z",
     "status": {"type": {"state": "post", "completed": True, "shortDetail": "Final"}},
     "competitions": [{"competitors": [
         {"homeAway": "home", "score": "101", "team": {"id": "3", "displayName": "A"}},
         {"homeAway": "away", "score": "99", "team": {"id": "4", "displayName": "B"}}],
         "odds": [{"provider": {"name": "X"}, "overUnder": 210.5, "overOdds": -105, "underOdds": -115}]}]},
    {"id": "bad"},
]}

SCHEDULE = {"requestedSeason": {"year": 2027}, "events": [
    {"id": "a", "date": "2026-11-10T00:00Z", "competitions": [{
        "status": {"type": {"state": "post", "completed": True}},
        "competitors": [
            {"homeAway": "home", "team": {"id": "2"}, "score": {"value": 120.0, "displayValue": "120"}},
            {"homeAway": "away", "team": {"id": "9", "displayName": "Opp"}, "score": {"value": 110.0}}]}]},
    {"id": "b", "date": "2026-11-20T00:00Z", "competitions": [{
        "status": {"type": {"state": "pre", "completed": False}},
        "competitors": [{"homeAway": "home", "team": {"id": "2"}},
                        {"homeAway": "away", "team": {"id": "9"}}]}]},
]}


class ParseTests(unittest.TestCase):
    def test_scoreboard(self):
        ms = parse_scoreboard(SCOREBOARD, "nba")
        self.assertEqual([m.event_id for m in ms], ["2", "1"])  # เรียงตามเวลา, ข้ามรายการเสีย
        pre = ms[1]
        self.assertTrue(pre.is_pregame)
        self.assertEqual(pre.home.abbr, "BOS")
        self.assertEqual(pre.home.record, "8-3")
        self.assertEqual(pre.market.line, 226.5)
        self.assertEqual(pre.market.over_odds, -112)
        self.assertEqual(pre.market.under_odds, 100)
        post = ms[0]
        self.assertEqual((post.home_score, post.away_score), (101, 99))
        self.assertEqual((post.market.line, post.market.under_odds), (210.5, -115))

    def test_schedule(self):
        games = parse_team_schedule(SCHEDULE, "2")
        self.assertEqual(len(games), 1)
        g = games[0]
        self.assertEqual((g.points_for, g.points_against, g.is_home, g.opponent), (120, 110, True, "Opp"))
        self.assertEqual(season_year(SCHEDULE), 2027)


class AnalyzerTests(unittest.TestCase):
    def _match(self, key, line=None):
        lg = get_league(key)
        m = Match("x", key, datetime(2026, 11, 14, tzinfo=timezone.utc), "pre", "", Team("h", "H"),
                  Team("a", "A"))
        return lg, m

    def test_average_teams_project_league_average(self):
        for key in ("nba", "epl", "mlb", "nfl"):
            lg, m = self._match(key)
            avg = lg.team_avg
            hf = TeamForm.manual(m.home, avg, avg, 10)
            af = TeamForm.manual(m.away, avg, avg, 10)
            a = TotalAnalyzer(lg).evaluate(m, hf, af)
            self.assertAlmostEqual(a.total, 2 * avg, delta=0.02 * avg, msg=key)
            self.assertGreater(a.home_exp, a.away_exp, msg=key)  # ได้เปรียบเจ้าบ้าน
            self.assertIsNone(a.pick)

    def test_pick_logic(self):
        lg, m = self._match("nba")
        hf = TeamForm.manual(m.home, 125, 122, 10)
        af = TeamForm.manual(m.away, 124, 121, 10)
        a = TotalAnalyzer(lg).evaluate(m, hf, af, line=235.5)
        self.assertGreater(a.total, 240)
        self.assertEqual(a.pick, "over")
        self.assertEqual(a.strength, "แนะนำ")
        b = TotalAnalyzer(lg).evaluate(m, hf, af, line=round(a.total) + 0.5)
        self.assertEqual(b.strength, "ผ่าน")

    def test_small_sample_shrinks_and_downgrades(self):
        lg, m = self._match("nba")
        hf = TeamForm.manual(m.home, 140, 140, 1)
        af = TeamForm.manual(m.away, 140, 140, 1)
        a = TotalAnalyzer(lg).evaluate(m, hf, af, line=225.5)
        self.assertLess(a.total, 260)       # หดเข้าหาค่าเฉลี่ยลีก
        self.assertEqual(a.data_quality, "ต่ำ")
        self.assertNotEqual(a.strength, "แนะนำ")

    def test_soccer_extras(self):
        lg, m = self._match("epl")
        a = TotalAnalyzer(lg).evaluate(m, TeamForm.manual(m.home, 2, 1, 10),
                                       TeamForm.manual(m.away, 1, 2, 10))
        ex = a.extras
        self.assertAlmostEqual(ex["p_home_win"] + ex["p_draw"] + ex["p_away_win"], 1, places=3)
        self.assertGreater(ex["p_home_win"], ex["p_away_win"])
        self.assertEqual([x.line for x in a.ladder], [1.5, 2.5, 3.5])

    def test_demo_client_excludes_future_games(self):
        lg = get_league("nfl")
        c = DemoClient(lg)
        m = c.scoreboard(lg)[0]
        games = c.team_games(lg, m.home.id, before=m.start)
        self.assertTrue(all(g.date < m.start for g in games))
        a = TotalAnalyzer(lg, c).analyze(m)
        self.assertEqual(a.home_form.n, 10)
        self.assertEqual(a.line_source, "เจ้ามือ (DemoBook)")


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(list(argv))
        return code, buf.getvalue()

    def test_demo_all_sports(self):
        for key in ("nba", "epl", "mlb", "nfl"):
            code, out = self.run_cli("demo", key)
            self.assertEqual(code, 0)
            self.assertIn("สกอร์รวมคาดการณ์", out)

    def test_manual_json(self):
        code, out = self.run_cli("manual", "mlb", "--home-for", "5", "--home-against", "4",
                                 "--away-for", "4", "--away-against", "5", "--line", "8.5", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["main_line"]["line"], 8.5)
        self.assertIn("p_home_win", data["extras"])

    def test_unknown_league(self):
        self.assertEqual(self.run_cli("manual", "xyz", "--home-for", "1", "--home-against", "1",
                                      "--away-for", "1", "--away-against", "1")[0], 2)

    def test_all_leagues_listed(self):
        code, out = self.run_cli("leagues")
        self.assertEqual(code, 0)
        for key in LEAGUES:
            self.assertIn(key, out)
        self.assertEqual(get_league("soccer:por.1").slug, "por.1")


if __name__ == "__main__":
    unittest.main()

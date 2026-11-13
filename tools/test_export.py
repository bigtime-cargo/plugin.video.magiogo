# -*- coding: utf-8 -*-
"""Offline testy exportu playlistu (skupiny kanálov).

    cd ~/plugin.video.magiogo && python3 -m unittest tools.test_export -v
"""
import os, re, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "resources", "lib"))
import export  # noqa: E402

# reálne mená z Magio GO (13. 11. 2026) - väčšina nesie suffix "HD", čo
# posúva "Všeobecné" kanály (Jednotka, Markíza, JOJ, ...) do "Ostatné",
# lebo kanaly_skupiny.py anchoruje "Všeobecné" na celý (normalizovaný)
# názov. Je to kozmetická odchýlka od O2 TV (tam mená "HD" nenesú) -
# pozri CLAUDE.md.
CHANS = [
    {"id": "4099", "name": "Jednotka HD", "number": 1, "has_archive": True},
    {"id": "4044", "name": "Markíza HD", "number": 4, "has_archive": True},
    {"id": "4223", "name": "JOJ KRIMI HD", "number": 8, "has_archive": False},
    {"id": "9999", "name": "TA3", "number": 9, "has_archive": True},
    {"id": "9998", "name": "Šport HD", "number": 99, "has_archive": False},
]


class SkupinyVExporte(unittest.TestCase):
    def setUp(self):
        self.lines = export.build_m3u(CHANS).splitlines()
        self.extinf = [l for l in self.lines if l.startswith("#EXTINF")]

    def test_catchup_len_pri_archive(self):
        # Jednotka a Markíza majú archív, JOJ KRIMI a Šport nie
        self.assertIn('catchup="default"', self.extinf[0])
        self.assertIn('catchup="default"', self.extinf[1])
        self.assertNotIn('catchup=', self.extinf[2])
        self.assertNotIn('catchup=', self.extinf[4])

    def test_group_title_archiv_len_ked_ma_archiv(self):
        self.assertIn('group-title="Magio GO (archív);', self.extinf[0])
        self.assertNotIn('Magio GO (archív)', self.extinf[2])

    def test_jeden_atribut_group_title_na_riadok(self):
        for l in self.extinf:
            self.assertEqual(l.count("group-title="), 1)

    def test_tvg_chno_sa_nemeni(self):
        nums = [re.search(r'tvg-chno="(\d+)"', l).group(1) for l in self.extinf]
        self.assertEqual(nums, ["1", "4", "8", "9", "99"])

    def test_urls_su_plugin_magiogo(self):
        urls = [l for l in self.lines if l.startswith("plugin://")]
        self.assertTrue(all(u.startswith("plugin://plugin.video.magiogo/")
                            for u in urls))

    def test_ta3_je_spravy(self):
        l = next(l for l in self.extinf if ',TA3' in l)
        self.assertIn('group-title="Magio GO (archív);Správy"', l)


class CatchupId(unittest.TestCase):
    def test_catchup_source_pouziva_catchup_id(self):
        l = [l for l in export.build_m3u(CHANS).splitlines() if l.startswith("#EXTINF")][0]
        self.assertIn("&sid={catchup-id}&start_ts={utc}&end_ts={utcend}", l)

    def test_programme_nesie_catchup_id(self):
        class FakeApi:
            def epg_day(self, ts):
                return [{"channel": {"channelId": 4099}, "programs": [
                    {"startTimeUTC": 1794578400000, "endTimeUTC": 1794581400000,
                     "scheduleId": 140868577452082, "program": {"title": "Otec Brown"}},
                    {"startTimeUTC": 1794581400000, "endTimeUTC": 1794582000000,
                     "program": {"title": "Bez ID"}}]}]
        xml, failed = export.build_xmltv(FakeApi(), [{"id": "4099", "name": "Jednotka HD"}],
                                         days_back=0, days_fwd=0)
        self.assertIn(' catchup-id="140868577452082">', xml)
        self.assertEqual(xml.count("catchup-id="), 1)


class XmlEscaping(unittest.TestCase):
    def test_xesc_specialne_znaky(self):
        self.assertEqual(export.xesc('<a & "b" \'c\'>'),
                         '&lt;a &amp; &quot;b&quot; &apos;c&apos;&gt;')


if __name__ == "__main__":
    unittest.main()

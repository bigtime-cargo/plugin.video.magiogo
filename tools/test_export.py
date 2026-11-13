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

    def test_vsetky_temy_maju_prefix_magio_go(self):
        for l in self.extinf:
            skupiny = re.search(r'group-title="([^"]*)"', l).group(1).split(";")
            tema = [g for g in skupiny if g != 'Magio GO (archív)']
            self.assertEqual(len(tema), 1)
            self.assertTrue(tema[0].startswith('Magio GO – '), tema[0])

    def test_tvg_chno_sa_nemeni(self):
        nums = [re.search(r'tvg-chno="(\d+)"', l).group(1) for l in self.extinf]
        self.assertEqual(nums, ["1", "4", "8", "9", "99"])

    def test_urls_su_plugin_magiogo(self):
        urls = [l for l in self.lines if l.startswith("plugin://")]
        self.assertTrue(all(u.startswith("plugin://plugin.video.magiogo/")
                            for u in urls))

    def test_ta3_je_spravy(self):
        l = next(l for l in self.extinf if ',TA3' in l)
        self.assertIn('group-title="Magio GO (archív);Magio GO – Správy"', l)


class XmlEscaping(unittest.TestCase):
    def test_xesc_specialne_znaky(self):
        self.assertEqual(export.xesc('<a & "b" \'c\'>'),
                         '&lt;a &amp; &quot;b&quot; &apos;c&apos;&gt;')


if __name__ == "__main__":
    unittest.main()

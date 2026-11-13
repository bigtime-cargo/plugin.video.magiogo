# -*- coding: utf-8 -*-
"""Generuje playlist.m3u a epg.xml pre IPTV Simple Client, rovnako ako
plugin.video.o2tv. Na rozdiel od O2 TV tu kanály prichádzajú z API už
s informáciou o predplatnom (api.channels() filtruje liveSubscription),
takže tu nie je potrebný žiadny ekvivalent entitled_cached()."""
import os, time, datetime, tempfile

from kanaly_skupiny import group_title

PLUGIN = "plugin://plugin.video.magiogo/"


class Aborted(Exception):
    """Kodi sa vypina - export sa prerušil a nic sa nezapisalo."""


class Incomplete(Exception):
    """Cast EPG sa nestiahla a na disku je este cerstve EPG - nic sa nezapisalo."""


KEEP_OLD_EPG = 24 * 3600


def xesc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("'", "&apos;").replace('"', "&quot;"))


def fmt(ts):
    return datetime.datetime.fromtimestamp(
        int(ts), datetime.timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def _write(path, text):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def build_m3u(chans, epg_url=None):
    out = ['#EXTM3U' + (' url-tvg="%s"' % epg_url if epg_url else '')]
    for c in chans:
        cid = c["id"]
        attrs = 'tvg-id="%s" tvg-name="%s"' % (cid, xesc(c["name"]))
        if c.get("logo"):
            attrs += ' tvg-logo="%s"' % c["logo"]
        attrs += ' group-title="%s"' % xesc(
            group_title(c["name"], archive=bool(c.get("has_archive"))))
        if c.get("number"):
            attrs += ' tvg-chno="%s"' % c["number"]
        if c.get("has_archive"):
            attrs += ' catchup="default" catchup-days="7"'
            attrs += (' catchup-source="%s?action=play&cid=%s'
                      '&sid={catchup-id}&start_ts={utc}&end_ts={utcend}"'
                      % (PLUGIN, cid))
        out.append('#EXTINF:-1 %s,%s' % (attrs, c["name"]))
        out.append('%s?action=play&cid=%s' % (PLUGIN, cid))
    return "\n".join(out) + "\n"


def build_xmltv(api, chans, days_back=7, days_fwd=3, log=None, should_stop=None):
    """Vracia (xml, pocet zlyhanych dni). Stahuje po dnoch (API vracia
    jednu skupinu programov na kanal a den)."""
    now = int(time.time())
    failed = 0
    id2name = {c["id"]: c["name"] for c in chans}

    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<tv generator-info-name="plugin.video.magiogo">']
    for c in chans:
        xml.append('<channel id="%s"><display-name>%s</display-name>%s</channel>' % (
            xesc(c["id"]), xesc(c["name"]),
            '<icon src="%s"/>' % xesc(c["logo"]) if c.get("logo") else ""))

    day_count = days_back + days_fwd + 1
    for n in range(-days_back, days_fwd + 1):
        if should_stop and should_stop():
            raise Aborted()
        day_ts = now + n * 86400
        try:
            groups = api.epg_day(day_ts)
        except Exception as e:
            if log:
                log("EPG pre deň %s zlyhalo: %s"
                    % (time.strftime("%Y-%m-%d", time.gmtime(day_ts)), e))
            failed += 1
            continue
        for grp in groups:
            ch = str((grp.get("channel") or {}).get("channelId"))
            if ch not in id2name:
                continue
            for p in grp.get("programs") or []:
                ps, pe = p.get("startTimeUTC"), p.get("endTimeUTC")
                if ps is None or pe is None:
                    continue
                prog = p.get("program") or {}
                # catchup-id = scheduleId konkretneho vysielania; IPTV Simple ho
                # dosadi do {catchup-id} v catchup-source, takze archiv nehada
                # program podla casu (IPTV Simple posuva start_ts o -5 min a
                # end_ts o +15 min, co vybralo predchadzajuci program).
                sid = p.get("scheduleId")
                xml.append('<programme start="%s" stop="%s" channel="%s"%s>' % (
                    fmt(ps / 1000.0), fmt(pe / 1000.0), xesc(ch),
                    ' catchup-id="%s"' % xesc(sid) if sid else ""))
                xml.append('<title>%s</title>' % xesc(prog.get("title", "")))
                if prog.get("description"):
                    xml.append('<desc>%s</desc>' % xesc(prog["description"]))
                xml.append('</programme>')
    xml.append('</tv>')
    return "\n".join(xml), failed


def export_all(api, profile_dir, days_back=7, days_fwd=3, log=None, extra_dir=None,
               should_stop=None):
    """Vygeneruje playlist a EPG. Vracia (počet kanálov, počet programov).
    Pri ukončovaní Kodi vyhodí Aborted a nezapíše nič. Vyhodí Incomplete,
    keď časť EPG chýba a staré EPG je ešte čerstvé."""
    chans = api.channels()
    if should_stop and should_stop():
        raise Aborted()

    xml, failed = build_xmltv(api, chans, days_back, days_fwd, log, should_stop)

    epg_main = os.path.join(profile_dir, "epg.xml")
    if failed:
        try:
            age = time.time() - os.path.getmtime(epg_main)
        except OSError:
            age = None
        if age is not None and age < KEEP_OLD_EPG:
            raise Incomplete("%d dní EPG zlyhalo, ponechávam EPG staré %.1f h"
                             % (failed, age / 3600.0))
        if log:
            log("%d dní EPG zlyhalo, staré EPG je staršie než %d h — "
                "zapisujem neúplné" % (failed, KEEP_OLD_EPG // 3600))

    targets = [(os.path.join(profile_dir, "playlist.m3u"), epg_main)]
    if extra_dir:
        targets.append((os.path.join(extra_dir, "playlist.m3u"),
                        os.path.join(extra_dir, "magiogo_epg.xml")))

    for m3u_path, epg_path in targets:
        try:
            _write(m3u_path, build_m3u(chans, epg_url=epg_path))
            _write(epg_path, xml)
        except Exception as e:
            if log:
                log("zápis do %s zlyhal: %s" % (os.path.dirname(m3u_path), e))
    return len(chans), xml.count("<programme")

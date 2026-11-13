# -*- coding: utf-8 -*-
"""Od štartu Kodi: denná obnova session (access/refresh token) + export
playlist.m3u a epg.xml pre IPTV Simple Client.

Zjednodušené oproti plugin.video.o2tv:
- prihlásenie je login/heslo (bez Keycloaku, bez SMS, bez SSO cookie) -
  nepotrebuje teda AutoLogin ani import_sso.
- žiadne SCTE-35 značky v manifeste -> žiadne preskakovanie reklám (ads.py).
- koniec programu / pokračovanie na ďalší cez EPG (EndWatch v O2 TV) tu
  zatiaľ nie je - netestované, či to Magio GO potrebuje. Pozri CLAUDE.md.

KeepAlive je ponechaný, lebo manifest sa rovnako ako pri O2 TV presmeruje
(307) na konkrétny CDN server (s1-hNN-vliveXX...) - to je presne situácia,
pri ktorej O2 TV relácia počas pauzy umiera. Prahové hodnoty (40 s) sú
PREVZATÉ z O2 TV a NEOVERENÉ na Magio GO - treba potvrdiť reálnym testom
(dlhšia pauza v živom vysielaní) a prípadne upraviť.
"""
import os, sys, time
import threading, urllib.request, urllib.error

import xbmc, xbmcaddon, xbmcgui, xbmcvfs

ADDON = xbmcaddon.Addon()
sys.path.insert(0, xbmcvfs.translatePath(
    os.path.join(ADDON.getAddonInfo("path"), "resources", "lib")))
from api import MagioAPI, MagioError, UA   # noqa: E402
from export import export_all, Aborted   # noqa: E402


class Store:
    def get(self, key):
        return ADDON.getSetting(key)

    def set(self, key, value):
        ADDON.setSetting(key, str(value))


def log(msg, err=False):
    xbmc.log("[magiogo.service] %s" % msg, xbmc.LOGERROR if err else xbmc.LOGINFO)


EXPORT_RETRY = 30 * 60   # po zlyhanom exporte EPG, sekund


def dead_notice():
    xbmcgui.Dialog().notification(
        "Magio GO", "Prihlásenie vypršalo — otvor doplnok (Nastavenia → "
                   "Prihlásiť sa nanovo)", xbmcgui.NOTIFICATION_WARNING, 10000)


def tick(api):
    """Jedno kolo údržby session. Vracia True, ked je access token platný
    (ensure_session() sa sama postará o dennú obnovu)."""
    try:
        api.ensure_session()
        return True
    except MagioError as e:
        log("obnova session zlyhala: %s" % e, True)
        if getattr(e, "code", "") == "NOSESSION":
            # zariadenie sa este neprihlasilo - cakame na uzivatela
            return False
        if getattr(e, "code", "") in ("NET", "BADJSON"):
            return False
        # refresh token uz neplati (napr. INVALID_REFRESH_TOKEN) - treba
        # nove prihlasenie menom a heslom
        dead_notice()
        return False


# ---------- udrziavanie CDN relacie pocas pauzy ----------
KEEPALIVE_PROP = "magiogo.keepalive_url"
RESUME_PROP = "magiogo.play_url"
PING_EVERY = 20
KEEPALIVE_MAX = 45 * 60
FOREIGN_FORGET = 20


class KeepAlive(threading.Thread):
    """Vlastné vlákno, aby pingy nezávisely od hlavnej slučky (export EPG ju
    blokuje na desiatky sekúnd, čo by pauzu rozbilo)."""

    def __init__(self, monitor):
        threading.Thread.__init__(self, daemon=True)
        self.monitor = monitor
        self.last_ping = 0
        self.paused_since = 0
        self.seen_video = False
        self.dead = False
        self.foreign_since = 0

    def run(self):
        while not self.monitor.abortRequested():
            if self.monitor.waitForAbort(2):
                break
            try:
                self.tick()
            except Exception as e:
                log("keep-alive: %s" % e, True)

    def tick(self):
        win = xbmcgui.Window(10000)
        url = win.getProperty(KEEPALIVE_PROP)
        if not url:
            return
        playing = xbmc.getCondVisibility("Player.HasVideo")
        if playing and not self.ours(url):
            now = time.time()
            if not self.foreign_since:
                self.foreign_since = now
            elif now - self.foreign_since > FOREIGN_FORGET:
                log("hrá iné video — zabúdam adresu Magio GO")
                self.forget()
            return
        self.foreign_since = 0
        if playing:
            self.seen_video = True
        if not xbmc.getCondVisibility("Player.Paused"):
            was_paused = bool(self.paused_since)
            self.paused_since = 0
            if was_paused and self.dead and playing:
                self.dead = False
                self.restart()
                return
            if self.seen_video and not playing:
                self.forget()
            return
        now = time.time()
        if not self.paused_since:
            self.paused_since = now
            log("pauza — držím CDN reláciu nažive")
        if self.dead:
            return
        if now - self.paused_since > KEEPALIVE_MAX:
            self.dead = True
            log("pauza nad %d min — po odpauznutí prehrám znova" % (KEEPALIVE_MAX // 60))
            return
        if now - self.last_ping < PING_EVERY:
            return
        self.last_ping = now
        try:
            req = urllib.request.Request(url, headers={"user-agent": UA})
            with urllib.request.urlopen(req, timeout=5) as r:
                r.read(1)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                self.dead = True
                log("CDN relácia vypršala — po odpauznutí prehrám znova", True)
                return
            log("keep-alive zlyhal: %s" % e, True)
        except Exception as e:
            log("keep-alive zlyhal: %s" % e, True)

    @staticmethod
    def ours(url):
        try:
            f = xbmc.Player().getPlayingFile()
        except RuntimeError:
            return True
        return (f == url or f.startswith("pvr://")
                or f.startswith("plugin://plugin.video.magiogo/"))

    def forget(self):
        win = xbmcgui.Window(10000)
        win.clearProperty(KEEPALIVE_PROP)
        win.clearProperty(RESUME_PROP)
        self.seen_video = False
        self.dead = False
        self.paused_since = 0
        self.foreign_since = 0

    def restart(self):
        play_url = xbmcgui.Window(10000).getProperty(RESUME_PROP)
        if not play_url:
            log("obnova nemá čo pustiť - chýba adresa", True)
            return
        player = xbmc.Player()
        try:
            pos = int(player.getTime())
        except Exception:
            pos = 0
        log("obnovujem prehrávanie od %d s" % pos)
        self.seen_video = False
        player.play(play_url)
        for _ in range(30):
            if self.monitor.waitForAbort(1):
                return
            try:
                if player.isPlayingVideo() and player.getTotalTime() > 0:
                    break
            except Exception:
                continue
        else:
            log("obnova sa nerozbehla do 30 s", True)
            return
        if pos <= 0:
            return
        self.monitor.waitForAbort(1)
        try:
            player.seekTime(pos)
        except Exception as e:
            log("seek po obnove zlyhal: %s" % e, True)


def sleep_abortable(monitor, seconds, chunk=2):
    waited = 0
    while waited < seconds:
        step = min(chunk, seconds - waited)
        if monitor.waitForAbort(step):
            return True
        waited += step
    return False


def main():
    monitor = xbmc.Monitor()
    api = MagioAPI(Store(), xbmcvfs.translatePath(ADDON.getAddonInfo("profile")),
                   log=lambda m: log(m, True))
    log("service štart")

    ok, detail = api.state_writable()
    if ok:
        log("zápis stavu overený")
    else:
        log("POZOR: stav sa nedá zapísať (%s) — obnovená relácia sa "
            "neuloží a doplnok prestane fungovať" % detail, True)

    if sleep_abortable(monitor, 20):
        return

    profile = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
    KeepAlive(monitor).start()
    last_export = 0
    while not monitor.abortRequested():
        try:
            ok = tick(api)
        except Exception as e:
            log("údržba session spadla: %r" % e, True)
            ok = False
        if ok:
            try:
                every = int(ADDON.getSetting("epg_refresh_h") or 12) * 3600
            except ValueError:
                every = 43200
            if time.time() - last_export > every:
                try:
                    db = int(ADDON.getSetting("epg_days_back") or 7)
                    df = int(ADDON.getSetting("epg_days_fwd") or 3)
                    n, p = export_all(api, profile, db, df,
                                      lambda m: log(m, True),
                                      ADDON.getSetting("export_dir") or None,
                                      should_stop=monitor.abortRequested)
                    last_export = time.time()
                    log("export hotový: %d kanálov, %d programov" % (n, p))
                except Aborted:
                    log("export prerušený, Kodi sa vypína")
                    break
                except Exception as e:
                    log("export zlyhal: %s" % e, True)
                    last_export = time.time() - every + EXPORT_RETRY
        if sleep_abortable(monitor, 600):
            break
    log("service koniec")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
import sys, os
import urllib.parse, urllib.request

import xbmc, xbmcgui, xbmcplugin, xbmcaddon, xbmcvfs

ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else -1
BASE = sys.argv[0] if len(sys.argv) > 0 else "plugin://plugin.video.magiogo/"

sys.path.insert(0, xbmcvfs.translatePath(
    os.path.join(ADDON.getAddonInfo("path"), "resources", "lib")))
from api import MagioAPI, MagioError, UA   # noqa: E402

# Na rozdiel od O2 TV sa manifest ziveho vysielania presmeruje na konkretny
# CDN server (s1-h25-vlive01...) rovnako ako O2 - preto rovnaky trik:
# rozbalit presmerovanie sami a adresu drzat cez window property, nech ju
# service.py moze pocas pauzy udrziavat nazive (kym sa to neoveri priamo
# v Kodi, nechavame to len ako pripravu - service.py zatial keep-alive
# nerobi, pozri CLAUDE.md).
KEEPALIVE_PROP = "magiogo.keepalive_url"
RESUME_PROP = "magiogo.play_url"


class Store:
    def get(self, key):
        return ADDON.getSetting(key)

    def set(self, key, value):
        ADDON.setSetting(key, str(value))


def log(msg):
    xbmc.log("[magiogo] %s" % msg, xbmc.LOGINFO)


def notify(msg, err=False):
    xbmcgui.Dialog().notification(
        "Magio GO", msg,
        xbmcgui.NOTIFICATION_ERROR if err else xbmcgui.NOTIFICATION_INFO, 5000)


def url_for(**kwargs):
    return BASE + "?" + urllib.parse.urlencode(kwargs)


def do_login(api, silent=False):
    """Prihlási sa menom a heslom z nastavení doplnku. Vracia True pri úspechu."""
    user = ADDON.getSetting("username")
    pwd = ADDON.getSetting("password")
    if not user or not pwd:
        if not silent:
            notify("Vyplň Login a Heslo v nastaveniach doplnku.", True)
        return False
    try:
        api.login(user, pwd)
    except MagioError as e:
        if not silent:
            notify("Prihlásenie zlyhalo: %s" % e, True)
        log("prihlásenie zlyhalo (%s): %s" % (e.code or "-", e))
        return False
    log("prihlásenie OK")
    if not silent:
        notify("Prihlásené do Magio GO.")
    return True


def login_item():
    li = xbmcgui.ListItem(label="[ Prihlásiť sa nanovo ]")
    xbmcplugin.addDirectoryItem(HANDLE, url_for(action="login"), li, isFolder=False)


def channels_with_relogin(api):
    try:
        return api.channels()
    except MagioError as e:
        if getattr(e, "code", "") in ("NOSESSION",) and do_login(api, silent=True):
            return api.channels()
        raise


def list_channels(api):
    try:
        chans = channels_with_relogin(api)
    except MagioError as e:
        if getattr(e, "code", "") == "NOSESSION":
            notify("Zariadenie nie je prihlásené. Vyplň Login a Heslo v "
                  "nastaveniach a skús znova, alebo zvoľ nižšie prihlásenie.", True)
        else:
            notify("Chyba: %s" % e, True)
        login_item()
        xbmcplugin.endOfDirectory(HANDLE)
        return

    xbmcplugin.setContent(HANDLE, "videos")
    for c in chans:
        label = "%s. %s" % (c["number"], c["name"]) if c["number"] else c["name"]
        li = xbmcgui.ListItem(label=label)
        if c.get("logo"):
            li.setArt({"icon": c["logo"], "thumb": c["logo"]})
        li.setProperty("IsPlayable", "true")
        tag = li.getVideoInfoTag()
        tag.setMediaType("video")
        tag.setTitle(label)
        xbmcplugin.addDirectoryItem(
            HANDLE, url_for(action="play", cid=c["id"]), li, isFolder=False)

    login_item()
    xbmcplugin.endOfDirectory(HANDLE)


def cdn_session(url):
    """Rovnaký trik ako pri O2 TV: manifest sa 307-presmeruje na server
    konkrétnej relácie (s1-hNN-vliveXX...), tú adresu treba podať
    inputstream.adaptive priamo, inak hrozí, že si ju prehrávač nevyžiada
    znova pri obnove po pauze."""
    try:
        req = urllib.request.Request(url, headers={"user-agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.geturl()
    except Exception as e:
        log("presmerovanie manifestu zlyhalo: %s" % e)
        return url


def play(api, cid, start_ts=None, end_ts=None):
    try:
        try:
            manifest, info = api.resolve(cid, start_ts, end_ts)
        except MagioError as e:
            if getattr(e, "code", "") != "NOSESSION" or not do_login(api, silent=True):
                raise
            manifest, info = api.resolve(cid, start_ts, end_ts)
        log("resolve: %s" % getattr(api, "last_mode", "?"))
    except MagioError as e:
        log("resolve zlyhal (%s): %s" % (getattr(api, "last_mode", "?"), e))
        notify("Nedá sa prehrať: %s" % e, True)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    if not manifest:
        notify("Server nevrátil adresu streamu.", True)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    manifest = cdn_session(manifest)
    win = xbmcgui.Window(10000)
    win.setProperty(KEEPALIVE_PROP, manifest)
    resume = {"action": "play", "cid": cid}
    if start_ts:
        resume["start_ts"] = start_ts
    if end_ts:
        resume["end_ts"] = end_ts
    win.setProperty(RESUME_PROP, url_for(**resume))

    li = xbmcgui.ListItem(path=manifest)
    li.setMimeType("application/dash+xml")
    li.setContentLookup(False)
    li.setProperty("inputstream", "inputstream.adaptive")
    li.setProperty("inputstream.adaptive.manifest_type", "mpd")
    if start_ts:
        li.setProperty("inputstream.adaptive.play_timeshift_buffer", "true")

    lic, lic_headers = api.widevine_license(info.get("ecid") if isinstance(info, dict) else None)
    if lic:
        hdr = "&".join("%s=%s" % (k, urllib.parse.quote(v)) for k, v in lic_headers.items())
        li.setProperty("inputstream.adaptive.license_type", "com.widevine.alpha")
        li.setProperty("inputstream.adaptive.license_key",
                       "%s|%s|R{SSM}|" % (lic, hdr))

    maxb = ADDON.getSetting("max_bitrate")
    caps = {"1080p": "1920", "720p": "1280", "576p": "1024"}
    if maxb in caps:
        li.setProperty("inputstream.adaptive.max_resolution", caps[maxb])

    xbmcplugin.setResolvedUrl(HANDLE, True, li)


def main():
    raw = urllib.parse.parse_qs(sys.argv[2][1:]) if len(sys.argv) > 2 else {}
    args = {k[4:] if k.startswith("amp;") else k: v for k, v in raw.items()}
    action = args.get("action", [None])[0]

    api = MagioAPI(Store(), xbmcvfs.translatePath(ADDON.getAddonInfo("profile")), log=log)

    if action == "play":
        cid = args.get("cid", [None])[0]
        st = args.get("start_ts", [None])[0]
        et = args.get("end_ts", [None])[0]
        play(api, cid, int(st) if st else None, int(et) if et else None)
    elif action == "login":
        do_login(api)
        xbmc.executebuiltin("Container.Refresh")
    else:
        list_channels(api)


if __name__ == "__main__":
    main()

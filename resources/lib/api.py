# -*- coding: utf-8 -*-
"""Klient pre Magio GO (Slovak Telekom). Backend je 24i mCore, nie Kaltura.

Zistené reverzným inžinierstvom webu www.magiogo.sk (13. 11. 2026):
- appVersion musí byť aktuálne (web posiela 5.0.4), inak auth/init vráti
  417 OLD_APP_VERSION. Je to hodnota z balíka @24i/prj-1260-stl-nxg.
- Prihlásenie je priame: POST auth/login s loginOrNickname a password,
  žiadny Keycloak, žiadne SMS. Access token je Bearer, obnovuje sa cez
  refreshToken (auth/tokens).
- expiresIn v token odpovedi je ABSOLÚTNY čas v ms (epoch*1000), nie dĺžka.
- Limit zariadení (DEVICE_MAX_LIMIT) rieši home/listDevices +
  home/deleteDevice?id=...
- Stream: GET television/stream-url, service=LIVE|ARCHIVE|DVR, drm=verimatrix.
  Vracia DASH manifest (.mpd) bez SCTE-35 EventStream - Magio GO teda
  (na rozdiel od O2 TV) nemá v manifeste značky reklamných blokov a
  seekingForbidden je True - reklamy sa nedajú programovo preskočiť.
- DRM: Widevine cez home/config -> widevineStreamKeeperDrmUrl (keď
  drmIntegration == STREAM_KEEPER/VERIMATRIX), s Authorization hlavičkou
  rovnakou ako na API (Bearer access token).
"""
import json, time
import urllib.request, urllib.error, urllib.parse

BASE = "https://skgo.magio.tv"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
ORIGIN_HEADERS = {"Origin": "https://www.magiogo.sk", "Referer": "https://www.magiogo.sk/"}
# zistené funkčné hodnoty (13. 11. 2026) - ked Magio zmeni appVersion a
# auth/init zacne vracat OLD_APP_VERSION, treba ich aktualizovat
APP_VERSION = "5.0.4"
DEVICE_TYPE = "OTT_LINUX"
DEVICE_NAME = "Web Browser"


class MagioError(Exception):
    """Chyba API Magio GO. code drzi errorCode, aby sa dalo rozlisit napr.
    DEVICE_MAX_LIMIT alebo INVALID_CREDENTIALS."""

    def __init__(self, msg, code=""):
        Exception.__init__(self, msg)
        self.code = str(code or "")


def gen_dsid():
    import random
    return "Netscape.%d.%s" % (int(time.time()), random.random())


class MagioAPI:
    def __init__(self, store, state_dir=None, log=None):
        # store = Kodi nastavenia (login, heslo, kvalita)
        # state = vlastny JSON subor v profile (access/refresh token)
        self.s = store
        self.state_dir = state_dir
        self._state = None
        self._log = log
        self.write_error = ""

    # ---------- stav mimo nastavení ----------
    def _state_path(self):
        import os
        return os.path.join(self.state_dir or ".", "session.json")

    def st_load(self, force=False):
        if force or self._state is None:
            try:
                with open(self._state_path()) as f:
                    self._state = json.load(f)
            except Exception:
                self._state = {}
        return self._state

    def st_get(self, key, default=""):
        return self.st_load(force=True).get(key, default)

    def st_set(self, **kw):
        import os, tempfile
        st = self.st_load(force=True)
        st.update(kw)
        self._state = st
        d = self.state_dir or "."
        try:
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d)
            with os.fdopen(fd, "w") as f:
                json.dump(st, f)
            os.replace(tmp, self._state_path())
            self.write_error = ""
        except Exception as e:
            self.write_error = str(e)
            if self._log:
                self._log("zápis %s zlyhal: %s" % (self._state_path(), e))

    def state_writable(self):
        import os, tempfile
        d = self.state_dir or "."
        probe = os.path.join(d, "session.probe")
        try:
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d)
            with os.fdopen(fd, "w") as f:
                f.write("probe")
            os.replace(tmp, probe)
            os.remove(probe)
            return True, ""
        except Exception as e:
            try:
                os.remove(probe)
            except Exception:
                pass
            return False, str(e)

    # ---------- HTTP ----------
    def _call(self, method, path, params=None, body=None, auth=True, _retry=False):
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = dict(ORIGIN_HEADERS, **{"User-Agent": UA, "Accept": "application/json"})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth:
            tok = self.st_get("accessToken")
            if tok:
                headers["Authorization"] = "Bearer " + tok
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                resp = json.loads(e.read().decode("utf-8"))
            except Exception:
                raise MagioError("HTTP %s na %s" % (e.code, path), "HTTP_%d" % e.code)
        except OSError as e:
            raise MagioError("sieť: %s" % e, "NET")
        except ValueError as e:
            raise MagioError("neplatná odpoveď API: %s" % e, "BADJSON")

        if not resp.get("success", True) and "errorCode" in resp:
            code = resp.get("errorCode") or ""
            # access token vypršal: skús raz obnoviť a zopakovať
            if code in ("TOKEN_EXPIRED", "INVALID_TOKEN", "UNAUTHORIZED") \
                    and auth and not _retry and self.st_get("refreshToken"):
                self.refresh()
                return self._call(method, path, params, body, auth, True)
            raise MagioError(resp.get("localizedMessage") or resp.get("errorMessage")
                             or code or "neznáma chyba", code)
        if "token" in resp:
            self._save_token(resp["token"])
        return resp

    def _save_token(self, token):
        self.st_set(accessToken=token.get("accessToken", ""),
                    refreshToken=token.get("refreshToken") or self.st_get("refreshToken"),
                    tokenType=token.get("type", "Bearer"),
                    expiresIn=int(token.get("expiresIn") or 0),
                    issued=int(time.time()))

    # ---------- prihlásenie a relácia ----------
    def _device_params(self):
        return {"dsid": gen_dsid(), "deviceName": DEVICE_NAME,
                "deviceType": DEVICE_TYPE, "osVersion": "0.0.0",
                "appVersion": APP_VERSION, "language": "SK"}

    def login(self, username, password):
        """Prihlási sa menom a heslom. Uloží tokeny a čas prihlásenia."""
        self._call("POST", "/v2/auth/init", params=self._device_params(), auth=False)
        self._call("POST", "/v2/auth/login",
                   body={"loginOrNickname": username, "password": password})
        self.st_set(login_time=int(time.time()))

    def have_session(self):
        return bool(self.st_get("accessToken") and self.st_get("refreshToken"))

    def refresh(self):
        rt = self.st_get("refreshToken")
        if not rt:
            raise MagioError("Zariadenie ešte nie je prihlásené.", "NOSESSION")
        self._call("POST", "/v2/auth/tokens", body={"refreshToken": rt}, auth=False)

    # token sa obnovuje raz denne (nie az pred vyprsenim) - kratsie intervaly
    # by zatazovali API zbytocne, dlhsie riskuju vyprsany access token
    MAX_AGE = 86400

    def ensure_session(self):
        """Zaruci platny access token. Obnovi, ked je stav starsi nez MAX_AGE
        alebo access token uz vyprsal. Vyhodi MagioError (NOSESSION, alebo
        chyba z API), ked sa neda prihlasit/obnovit."""
        if not self.have_session():
            raise MagioError("Zariadenie ešte nie je prihlásené.", "NOSESSION")
        now = int(time.time())
        try:
            issued = int(self.st_get("issued") or 0)
        except Exception:
            issued = 0
        try:
            exp_ms = int(self.st_get("expiresIn") or 0)
        except Exception:
            exp_ms = 0
        expired = exp_ms and now * 1000 >= exp_ms
        if expired or (now - issued > self.MAX_AGE if issued else True):
            self.refresh()

    def state_age(self):
        try:
            got = int(self.st_get("issued") or 0)
        except Exception:
            got = 0
        return int(time.time()) - got if got else -1

    # ---------- zariadenia (limit DEVICE_MAX_LIMIT) ----------
    def list_devices(self):
        res = self._call("GET", "/home/listDevices")
        items = list(res.get("items") or [])
        if res.get("thisDevice"):
            items.append(res["thisDevice"])
        return items

    def delete_device(self, device_id):
        self._call("GET", "/home/deleteDevice", params={"id": device_id})

    def free_device_slot(self, pick="oldest"):
        """Odpojí jedno zariadenie, aby sa uvoľnil slot. Vracia True, ked
        nejake zariadenie odpojila. `pick` = "oldest" zoberie prve z listu
        (API ich vracia v poradi pridania)."""
        devices = self.list_devices()
        if not devices:
            return False
        dev = devices[0]
        self.delete_device(dev["id"])
        if self._log:
            self._log("odpojené zariadenie %s (%s), aby sa uvoľnil limit"
                      % (dev.get("name", "?"), dev.get("id")))
        return True

    # ---------- kanály ----------
    def channels(self):
        """Vráti len kanály, na ktoré má predplatné (liveSubscription) -
        na rozdiel od O2 TV to Magio hovorí priamo pri každom kanáli,
        nemusí sa to zisťovať osobitným volaním playbackContext na kanál."""
        self.ensure_session()
        res = self._call("GET", "/v2/television/channels",
                         params={"list": "LIVE", "queryScope": "LIVE"})
        out = []
        for it in res.get("items") or []:
            c = it.get("channel") or {}
            if not c.get("liveSubscription", True):
                continue
            out.append({
                "id": str(c.get("channelId")),
                "name": c.get("name", ""),
                "number": c.get("defaultChannelPosition"),
                "logo": c.get("logoUrl") or None,
                # archiveSubscription NEROZHODUJE o tom, ci archiv ozaj hra -
                # overene 13. 11. 2026: kanal s archiveSubscription=false
                # prehral ARCHIVE stream bez problemu. Drzime sa hasArchive.
                "has_archive": bool(c.get("hasArchive")),
            })
        out.sort(key=lambda c: (c["number"] is None, c["number"]))
        return out

    # ---------- EPG ----------
    # API vracia pre kazdy kanal osobitnu skupinu ("items": [{channel,
    # programs: [...]}, ...]) - jedna skupina na kanal za pozadovany den.
    # Straskovane po 20 (totalCount = pocet kanalov).
    def epg_day(self, day_ts):
        """Programy vsetkych kanalov pre jeden den (day_ts = lubovolny cas
        v tom dni, UTC). Filter podla vzoru povodneho MagioGo doplnku:
        startTime v [den 00:00, den+1 00:59]."""
        day = time.strftime("%Y-%m-%d", time.gmtime(day_ts))
        next_day = time.strftime("%Y-%m-%d", time.gmtime(day_ts + 86400))
        filt = "startTime=ge=%sT00:00:00.000Z;startTime=le=%sT00:59:59.999Z" % (
            day, next_day)
        out, offset = [], 0
        while True:
            res = self._call("GET", "/v2/television/epg",
                             params={"filter": filt, "limit": "20",
                                     "offset": offset, "list": "LIVE"})
            items = res.get("items") or []
            out += items
            if len(items) < 20:
                break
            offset += 20
            if offset > 2000:    # poistka proti nekonecnej slucke
                break
        return out

    def find_programme(self, channel_id, start_ts, end_ts):
        """Najde scheduleId konkretneho vysielania na danom kanali v danom
        case (pre archiv) - to je id, ktore stream-url pre ARCHIVE chce,
        NIE program.programId (ten je spolocny pre vsetky opakovania
        rovnakeho programu, scheduleId je jedno konkretne vysielanie).
        Vracia None, ked sa nenasiel."""
        for day in self.epg_day(start_ts):
            # POZOR: na urovni skupiny je kluc "channelId", na urovni
            # jednotliveho programu "id" - API nie je konzistentne
            if str((day.get("channel") or {}).get("channelId")) != str(channel_id):
                continue
            for p in day.get("programs") or []:
                ps, pe = p.get("startTimeUTC"), p.get("endTimeUTC")
                if ps is None or pe is None:
                    continue
                if ps / 1000.0 <= start_ts < pe / 1000.0:
                    return p.get("scheduleId")
        return None

    # ---------- prehrávanie ----------
    def stream_url(self, service, asset_id, quality="p5"):
        """service: LIVE / ARCHIVE / DVR. asset_id: channelId / programId /
        recordingId podľa service. Vracia (url, extra) - extra je cela
        odpoved pre diagnostiku (seekingForbidden, timeshift, ...)."""
        self.ensure_session()
        if service == "ARCHIVE":
            # Presne ako web klient magiogo.sk (zachytene 13. 11. 2026):
            # bez `name`, prof=p0, startTime=0. S `name=Web Browser` a
            # prof=p5 server odmietol archiv hlaskou "Nemate aktivovanu
            # doplnkovu sluzbu Magio TV Archiv", hoci web ten isty program
            # prehral.
            params = {"service": service, "devtype": DEVICE_TYPE,
                      "id": asset_id, "prof": "p0", "ecid": "",
                      "drm": "verimatrix", "startTime": "0"}
        else:
            params = {"service": service, "name": DEVICE_NAME,
                      "devtype": DEVICE_TYPE, "id": asset_id,
                      "prof": quality, "ecid": "", "drm": "verimatrix"}
        try:
            res = self._call("GET", "/v2/television/stream-url", params=params)
        except MagioError as e:
            if e.code == "DEVICE_MAX_LIMIT" and self.free_device_slot():
                res = self._call("GET", "/v2/television/stream-url", params=params)
            else:
                raise
        return res.get("url"), res

    def resolve(self, channel_id, start_ts=None, end_ts=None, quality="p5"):
        """Vráti (manifest_url, info). Minulý program (end_ts v minulosti)
        ide cez ARCHIVE podľa programId z EPG; inak LIVE (so sliding-window
        timeshiftom, co zabezpeci inputstream.adaptive)."""
        now = int(time.time())
        if start_ts and end_ts and int(end_ts) < now - 10:
            prog = self.find_programme(channel_id, int(start_ts), int(end_ts))
            if prog:
                self.last_mode = "ARCHIVE cid=%s prog=%s" % (channel_id, prog)
                return self.stream_url("ARCHIVE", prog, quality)
            self.last_mode = "ARCHIVE cid=%s (programId nenájdený, LIVE)" % channel_id
        else:
            self.last_mode = "LIVE cid=%s" % channel_id
        return self.stream_url("LIVE", channel_id, quality)

    # ---------- DRM (Widevine) ----------
    def drm_config(self):
        self.ensure_session()
        return self._call("GET", "/v2/home/config", params={"language": "SK"})

    def widevine_license(self, ecid=None):
        """Vrati (license_url, extra_headers) alebo (None, {}), ked DRM
        konfiguraciu nevie zistit.

        NEISTÉ - treba overiť na reálnom prehrávaní: z JS web klienta sa
        zdá, že Authorization k licenčnému serveru NIE je API token, ale
        `ecid` z odpovede stream-url (premenná `r = e.ecid` v minifikovanom
        kóde, hlavička sa nastaví len ked `r` je pravdivé). V našom teste
        (13. 11. 2026) bolo `ecid` v odpovedi `null` - teda možno web pre
        STREAM_KEEPER/Widevine žiadnu vlastnú Authorization hlavičku
        neposiela a licenčný server sa spolieha na niečo iné (napr. že sa
        pýta rovnaký klient/IP ako stream-url). Ked DRM v Kodi nebude
        fungovať (license server vráti 401/403), skús najprv BEZ
        Authorization hlavičky."""
        try:
            cfg = self.drm_config()
        except MagioError:
            return None, {}
        integration = cfg.get("drmIntegration")
        if integration not in ("STREAM_KEEPER", "VERIMATRIX"):
            return None, {}
        url = cfg.get("widevineStreamKeeperDrmUrl") or cfg.get("widevineDrmUrl")
        if not url:
            return None, {}
        return url, ({"Authorization": str(ecid)} if ecid else {})

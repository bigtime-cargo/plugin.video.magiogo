# -*- coding: utf-8 -*-
"""Prihlásenie do Magio GO mimo Kodi - na rozdiel od O2 TV je to jednoduché
meno a heslo, žiadny Keycloak ani kód zariadenia.

    python3 tools/login.py <login> <heslo> [cesta_k_session.json]

Zapíše session.json (accessToken, refreshToken, ...) do zadanej cesty,
predvolene do ./session.json v aktuálnom priečinku. Ten súbor potom treba
skopírovať do profilu doplnku na cieľovom zariadení
(userdata/addon_data/plugin.video.magiogo/session.json), presne ako pri
O2 TV - pozri CLAUDE.md oboch doplnkov.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "resources", "lib"))
import api  # noqa: E402


class FakeStore(dict):
    def get(self, k, d=""):
        return dict.get(self, k, d)

    def set(self, k, v):
        self[k] = v


def main():
    if len(sys.argv) < 3:
        sys.exit("použitie: python3 tools/login.py <login> <heslo> [session.json]")
    user, pwd = sys.argv[1], sys.argv[2]
    dest = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.getcwd(), "session.json")

    a = api.MagioAPI(FakeStore(), state_dir=os.path.dirname(dest) or ".")
    try:
        a.login(user, pwd)
    except api.MagioError as e:
        sys.exit("prihlásenie zlyhalo (%s): %s" % (e.code or "-", e))
    print("prihlásenie OK, uložené do %s" % a._state_path())
    chans = a.channels()
    print("kanálov s predplatným: %d" % len(chans))


if __name__ == "__main__":
    main()

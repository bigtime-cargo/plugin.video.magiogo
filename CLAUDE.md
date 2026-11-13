# plugin.video.magiogo

Kodi doplnok pre Magio GO (Slovak Telekom). Postavený rovnako ako
`~/plugin.video.o2tv` — žiadny server, žiadny sidecar, každé zariadenie
sebestačné.

STAV (13. 11. 2026): **živé vysielanie overené v reálnom Kodi 21.3** na PC
(Kubuntu, AMD RX 580, VAAPI) — prihlásenie, zoznam kanálov, automatické
odpojenie zariadenia pri DEVICE_MAX_LIMIT, DASH manifest aj Widevine DRM
decryption fungujú (`kodi.log`: "Manifest successfully parsed", h264
snímky sa reálne dekódovali a renderovali cez VAAPI ~50 s bez chyby).
Licenčný server NEPOTREBUJE žiadnu Authorization hlavičku (pôvodná
neistota v `widevine_license()` sa potvrdila v prospech prázdnych
headers). Archív/catchup OVERENÉ v reálnom Kodi (13. 11. 2026, verzia
0.1.1) — viď sekcia "Archív" nižšie. Správanie pri dlhšej pauze (KeepAlive
prahy) ešte NEOVERENÉ.

## Štruktúra

    addon.xml                 verzia doplnku — MUSÍ sa zvýšiť pri každej zmene
    addon.py                  zoznam kanálov + prehrávanie (plugin:// URL)
    service.py                od štartu Kodi: denná obnova session + export
    resources/settings.xml    login, heslo, kvalita, EPG dni
    resources/lib/api.py      klient Magio GO (login, refresh, kanály, EPG, playback)
    resources/lib/export.py   playlist.m3u + epg.xml pre IPTV Simple
    resources/lib/kanaly_skupiny.py  téma kanála podľa názvu (KÓPIA z plugin.video.o2tv)
    tools/test_export.py      testy exportu (python3 -m unittest tools.test_export -v)
    tools/login.py            prihlásenie mimo Kodi — login+heslo rovno na príkazový riadok

## API Magio GO (zistené reverzným inžinierstvom webu magiogo.sk, 13. 11. 2026)

Backend je **24i mCore** (`skgo.magio.tv`), NIE Kaltura ako O2 TV. Web klient
je balík `@24i/prj-1260-stl-nxg` verzia 5.0.4.

- `appVersion` musí byť aktuálna hodnota webu (teraz `5.0.4`), inak
  `auth/init` vráti HTTP 417 `OLD_APP_VERSION`. Keď sa to stane, treba
  zistiť novú hodnotu — je v JS bundli `www.magiogo.sk/static/js/main.*.js`,
  modul `8330`, pole `version`.
- **Prihlásenie je priame**: `POST /v2/auth/init` (device info) potom
  `POST /v2/auth/login` s `{loginOrNickname, password}`. Žiadny Keycloak,
  žiadne SMS, žiadne SSO cookie — oproti O2 TV oveľa jednoduchšie.
- Token: `Authorization: Bearer <accessToken>`. `expiresIn` v odpovedi je
  **absolútny čas v ms** (epoch*1000), nie dĺžka platnosti.
- Obnova: `POST /v2/auth/tokens` s `{refreshToken}`. Robí sa raz denne
  (`MAX_AGE = 86400` v `api.py`), nie až pred vypršaním — rovnaký dôvod ako
  pri O2 TV (dlhší odstup od prihlásenia = väčšie riziko, že obnova
  neprejde a dôvod sa zistí neskoro).
- **Limit zariadení** (`DEVICE_MAX_LIMIT` pri `stream-url`): vyriešené
  `GET /home/listDevices` (vráti `items` + `thisDevice`) a
  `GET /home/deleteDevice?id=...`. Testovaný účet mal limit **1 zariadenie**
  (`api.free_device_slot()` odpojí najstaršie a zopakuje volanie).
- **Kanály**: `GET /v2/television/channels?list=LIVE&queryScope=LIVE`.
  Pole `channel.liveSubscription` hovorí priamo, či má used predplatné na
  live (filtrovať na toto — Magio to na rozdiel od O2 TV nehovorí cez
  samostatné `playbackContext` volanie na kanál, takže žiadny ekvivalent
  `entitled_cached()` netreba). `channel.archiveSubscription` je `false`
  pri všetkých kanáloch testovaného účtu (len ~4 h archív, viď "Archív");
  `api.channels()` sa drží `hasArchive`. Číslo kanála je
  `channel.defaultChannelPosition` (NIE `channelNumber`, to pole v odpovedi
  nie je).
- **EPG**: `GET /v2/television/epg?filter=startTime=ge=<deň>T00:00:00.000Z;
  startTime=le=<deň+1>T00:59:59.999Z&limit=20&offset=N&list=LIVE`.
  Odpoveď je **skupiny po kanáli** (`items: [{channel, programs: [...]}]`),
  stránkovane po 20 (limit API), `totalCount` = počet kanálov. POZOR na
  nekonzistentné pole s ID kanála:
    - na úrovni **skupiny** je to `channel.channelId`
    - na úrovni **jednotlivého programu** je to `program_item.channel.id`
      (iný kľúč aj iná štruktúra — netreba zamieňať)
  Časy (`startTimeUTC`/`endTimeUTC`) sú **epoch v ms** ako číslo, nie ISO
  string (na rozdiel od staršieho addonu Sorien/plugin.video.iptv.magiogo,
  ktorý čakal ISO formát — API sa odtedy zmenilo).
- **Playback**: `GET /v2/television/stream-url?service=LIVE|ARCHIVE|DVR&
  name=Web Browser&devtype=OTT_LINUX&id=<asset_id>&prof=p5&ecid=&drm=verimatrix`.
    - `service=LIVE`, `id` = `channelId`
    - `service=ARCHIVE`, `id` = **`scheduleId`** z EPG (top-level pole
      programu, NIE `program.programId` — to je spoločné pre všetky
      opakovania toho istého programu, scheduleId je jedno konkrétne
      vysielanie; overené naživo 13. 11. 2026)
  Vracia DASH manifest (`.mpd`), typ `dynamic`, `timeShiftBufferDepth≈PT1M`.
  `seekingForbidden: true`, `liveSlidingWindowInSeconds: 1800`,
  `timeshift: 240` (4 min) — pozri nižšie, prečo sa reklamy nedajú
  preskakovať.
- **CDN relácia**: manifest sa 307-presmeruje na konkrétny server
  (`vlive01.cdn.magio.tv` → `s1-h25-vlive01.cdn.magio.tv`), **rovnaký
  vzor ako O2 TV** (Broadpeak/Cetin tam, tu vlastný CDN Magio). `addon.py`
  preto rozbaľuje presmerovanie a `service.py` má prevzatý `KeepAlive` z
  O2 TV — **prahy (40 s do 403, 45 min max pauza) sú PREVZATÉ, NEOVERENÉ**
  na Magio GO. Treba reálny test dlhšej pauzy v Kodi.
- **DRM (Widevine) — OVERENÉ V REÁLNOM KODI 13. 11. 2026**: `GET
  /v2/home/config?language=SK` → pole `drmIntegration`
  (`STREAM_KEEPER`/`VERIMATRIX`) a `widevineStreamKeeperDrmUrl`
  (`https://multidrm.core.verimatrixcloud.net/widevine`). Licenčný server
  **nepotrebuje žiadnu `Authorization` hlavičku** — v JS web klienta sa
  zdalo, že by mal byť `ecid` z odpovede `stream-url`, ten je ale v praxi
  `null`, teda hlavička je prázdna (`widevine_license()` v `api.py` to tak
  rieši) a reálne prehrávanie (AMC HD, 13. 11. 2026, Kodi 21.3 + VAAPI) to
  potvrdilo — `kodi.log` ukázal "Manifest successfully parsed" a h264
  snímky sa reálne dekódovali a vykresľovali ~50 s bez CDM/licenčnej
  chyby. Manifest samotný nenesie `<ContentProtection>` — DRM nastavuje
  len `inputstream.adaptive.license_*` properties v `addon.py`.

## Archív (overené v Kodi 13. 11. 2026)

- `stream-url` pre ARCHIVE musí mať PRESNE parametre webu: `service=ARCHIVE
  &devtype=OTT_LINUX&id=<scheduleId>&prof=p0&ecid=&drm=verimatrix&startTime=0`
  (BEZ `name`, `prof=p0`). S `name=Web Browser&prof=p5` server odmietol
  archív ako "Nemáte aktivovanú doplnkovú službu Magio TV Archív".
- **Hĺbka archívu na testovanom účte je len cca 4 hodiny** (zodpovedá
  `channel.timeshift=240`), nie 7 dní z `channel.archive=604800000`.
  Staršie programy server odmieta tou istou hláškou; web pri 2 dni starom
  programe ponúka len "Nahrať", nie "Pozerať". `archiveSubscription` je
  `false` pri všetkých kanáloch a zodpovedá tomu (nie je "nespoľahlivý").
- **Presné pravidlo (overené 13. 11. 2026 na 26 programoch):** program sa dá
  prehrať, ak jeho ZAČIATOK nie je starší než 240 min (−3,95 h OK, −4,12 h
  nie), nezáleží na konci. Rovnaké na všetkých kanáloch (`timeshift=240`).
- **Zelená guľička v Kodi** = `IsEPGTagPlayable` v IPTV Simple. Pri
  `catchup-days="-1"` je prehrateľný len program s `catchup-id` v XMLTV, preto
  `render_xmltv()` dáva `catchup-id` programom so začiatkom v rozsahu
  <teraz − 240 min, teraz + 20 min> (bežiaci aj práve skončený; ARCHIVE
  funguje aj pri bežiacom programe od začiatku, pri programe, ktorý ešte
  nezačal, zlyhá "relácia ešte nezačala"). Predstih 20 min (`LEAD_MIN`) kryje
  oneskorenie nového programu: služba prepisuje `epg.xml` z pamäte každých ~5
  min (bez siete), IPTV Simple ho načíta pri obnove inštancie (odporúča sa
  15 min). Guľička preto môže byť až ~20 min pred začiatkom a až ~20 min
  po vypršaní archívu. Niektoré programy majú práva obmedzené ("tento
  program nie je možné prehrať") — vtedy doplnok spadne na LIVE.
- **IPTV Simple posúva čas v catchup URL** (`start_ts` o -5 min,
  `end_ts` o +15 min, nastavenia `catchupWatchEpg*BufferMins`). Hľadanie
  programu podľa `start_ts` preto vybralo PREDCHÁDZAJÚCI program. Riešenie:
  `<programme catchup-id="<scheduleId>">` v epg.xml a `{catchup-id}` v
  `catchup-source` (parameter `sid`). Podľa času sa hľadá len ako záloha.
- IPTV Simple inštancia "Magio GO" (`instance-settings-3.xml`) číta
  `playlist.m3u` a `epg.xml` z profilu doplnku; skupina "Magio GO (archív)".

## Reklamy — ako to funguje na Magio GO (výskum 13. 11. 2026)

Nie je to SCTE-35 v manifeste ako pri O2 TV (manifest žiadne značky nemá).
Reklamné bloky dodáva osobitný endpoint a prehráva ich web klient sám:

- Len **8 kanálov** má `adsSeekingForbidden: true` v
  `GET /v3/television/channels-brief?list=all&forceV2Logo=true&phv=<claim phv z JWT>`:
  Markíza HD (4044), JOJ HD (4070), Plus HD (4222), JOJ KRIMI HD (4223),
  Doma HD (4221), DAJTO HD (4111), Markíza KRIMI HD (4557), Markíza Klasik
  HD (4602). Ostatné kanály (Jednotka, Dvojka, ...) žiadne bloky nemajú
  (`ADS_NOT_REQUIRED`, HTTP 417).
- Bloky: `GET https://ads-sk.cdn.magio.tv/schedules/ads?service=ARCHIVE
  &scheduleId=<scheduleId programu>` (base z `home/config.adsBlocksCdnBaseUrl`),
  stačí `Authorization: Bearer`. Odpoveď: `adSkipPolicy`,
  `gracePeriodInSeconds`, `forceWatchEveryAd`, `adBlocks[]` s
  `adStartTimeUTC`, `adSkipTimeUTC`, `adEndTimeUTC` (ISO UTC).
  Pre budúci program HTTP 400 "no ads data for future schedule".
- **Politika závisí od toho, či program skončil**:
  - skončený program (archív): `PARTIAL_SKIPPABLE`, `forceWatchEveryAd=false`,
    grace 60 s. V bloku treba pozrieť prvých ~3 min (od `adStart` do
    `adSkip`), potom sa dá preskočiť na `adEnd`.
  - práve bežiaci program (live): `NOT_SKIPPABLE`, `forceWatchEveryAd=true`.
  - tretia hodnota `FULLY_SKIPPABLE` sa v JS klienta vyskytuje, tu sa nevidela.
- Web ju vynucuje v prehrávači (`seekingRestrictions`, časová os s
  `skipOffset = adSkipTimeUTC`). Pozícia v archívnom streame =
  čas bloku − začiatok programu (manifest archívu má `start=`/`end=` presne
  na hraniciach programu). Či server/CDN vynucuje aj sám (seekingForbidden:
  true v stream-url), NEOVERENÉ - treba zistiť, či sa dá v Kodi vôbec seekovať
  v archívnom streame.

**Overené na ostatných kanáloch (13. 11. 2026):** 17 živých manifestov
kanálov, ktoré nie sú na O2 TV (AMC, JOJ Svet, Nova Sport, Eurosport,
Discovery, JOJ Cinema, ...), nemá `EventStream`, SCTE-35 ani `emsg`, a
`schedules/ads` vracia pre 34 z 39 týchto kanálov `ADS_NOT_REQUIRED`. Pre
kanály mimo 8 vyššie sa preto reklamy preskakovať nedajú (nie je žiadna
značka ani zoznam blokov). Zmysel by to malo len pre tých 8 kanálov, ktoré
sú však aj na O2 TV, kde preskakovanie funguje plne.

## Čo (zatiaľ) chýba oproti O2 TV

- **KeepAlive prahy** (40 s / 45 min) sú skopírované z O2 TV, nie zmerané
  na Magio GO — treba reálny test dlhšej pauzy v Kodi.
- **EndWatch** (pokračovanie na ďalší program z EPG po skončení aktuálneho,
  pozri O2 TV `service.py`) tu nie je — netestované, či to Magio GO vôbec
  potrebuje (môže sa prejaviť rovnaký problém so zamrznutím na konci
  statického manifestu, alebo nie).
- **Automatické prihlásenie bez hesla v nastaveniach** (SSO cookie ako pri
  O2 TV) — Magio GO nemá Keycloak device-flow, takže by to vyžadovalo iný
  mechanizmus (ak vôbec existuje). Zatiaľ je jediná cesta login+heslo v
  nastaveniach doplnku (uložené v Kodi settings.xml, nie šifrované —
  rovnaké riziko ako pri väčšine IPTV doplnkov).
- **Kozmetika**: `kanaly_skupiny.py` je kópia z O2 TV a nerozpoznáva
  "Všeobecné" kanály s menami končiacimi na " HD" (napr. "Jednotka HD" padá
  do "Ostatné", lebo O2 TV kanály "HD" v mene nenesú a pravidlo je
  anchored na celý názov). Funkčne to nevadí, len škatuľkovanie v M3U.

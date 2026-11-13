# Magio GO pre Kodi

Neoficiálny doplnok pre Magio GO (Slovak Telekom). Zoznam kanálov, živé
vysielanie (DASH + Widevine), archív programov a export playlistu a EPG pre
IPTV Simple Client. Vyžaduje vlastné predplatné Magio GO.

## Inštalácia

Z repozitára BigTime (`https://bigtime-cargo.github.io/kodi-repo/`):
Doplnky → Inštalovať z repozitára → BigTime → Video doplnky → Magio GO.
Potrebný je `inputstream.adaptive` s Widevine.

## Nastavenie

1. V nastaveniach doplnku vyplň login a heslo Magio GO.
2. Služba doplnku po štarte Kodi vytvorí `playlist.m3u` a `epg.xml` v
   `userdata/addon_data/plugin.video.magiogo/` (trvá asi minútu, potom
   každých 12 hodín).
3. V IPTV Simple Client pridaj inštanciu s týmito dvomi súbormi, zapni
   catchup a nastav obnovu playlistu každých 30 minút (obnovou sa načíta aj
   EPG). Kanály s archívom sú v skupine „Magio GO (archív)“.

Zelená guľička pri programe v EPG znamená, že sa dá pozrieť z archívu. Doplnok
ju ukazuje len pri programoch, ktoré skončili a sú ešte v archíve (približne
posledné 4 hodiny), takže podľa nej vidíš, dokedy sa dá archív spustiť.

Nastavenia „Kanály“: skrytie kanálov, ktoré sú aj v doplnku O2 TV, a
regionálnych televízií (č. 500+). Obe voľby sú predvolene zapnuté, vypni ich,
ak O2 TV nepoužívaš.

## Obmedzenia

- Magio GO povoľuje obmedzený počet zariadení (testovaný účet: 1). Doplnok pri
  prehrávaní odpojí iné zariadenie z účtu. Na viacerých zariadeniach naraz
  to preto nefunguje.
- Hĺbka archívu závisí od predplatného. Testovaný účet mal len ~4 hodiny,
  staršie programy server odmieta.
- Preskakovanie reklám nie je (Magio GO ho umožňuje len čiastočne a len v
  archíve niektorých kanálov, pozri CLAUDE.md).

Technické detaily API sú v [CLAUDE.md](CLAUDE.md).

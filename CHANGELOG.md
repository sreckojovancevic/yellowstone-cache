# Yellowstone Cache — Changelog

## 0.3.5-alpha (2026-07-19)

- FIX (systemd auto režim): ExecStart je sada `repair --apply`
  umesto `up NAME` — `up` bi posle reboot-a odbio sa "already exists"
  (state zapis postoji). repair je idempotentan i pokriva sve boot
  slučajeve; nije vezan za ime backstore-a.
- Uklonjen ExecStop iz unit-a: svako gašenje se tretira kao pad,
  put dizanja je uvek isti. `down` je isključivo ručna, namerna akcija.

## 0.3.4-alpha (2026-07-19)

- FIX (repair): `_teardown` sada PRVO gasi LIO — ako je LIO živ i
  drži mapper uređaj, dmsetup remove bi pukao sa "device busy".
  Rušenje ide strogo obrnutim redosledom od podizanja.
- FIX (state): korumpiran/nečitljiv state fajl više ne obara alat sa
  traceback-om — jasna StateError poruka, fajl se NE dira (ostaje za
  analizu). Napomena: polu-upisan fajl ne može nastati (atomičan upis);
  ovo pokriva korupciju diska i ručne izmene. Bez jsonschema
  zavisnosti — projekat ostaje čist stdlib.
- `recreate` čisti eventualnu delimičnu LIO konfiguraciju pre
  sastavljanja.
- Future work (zabeleženo, nije za alpha): monitor režim sa
  dinamičkim migration_threshold podešavanjem pod pritiskom RAID-a.

## 0.3.3-alpha (2026-07-19)

- Nova komanda: `yellowstone repair [NAME] [--apply] [--json]`
  Razrešava prekinute procedure poređenjem tri izvora istine
  (state, saveconfig.json, kernel dm) po tabeli iz docs/state.md.
  - DRY-RUN JE DEFAULT — bez `--apply` samo prikazuje plan
  - `recreate` posle reboot-a: origin se uzima IZ STATE-a
    (saveconfig tada pokazuje na mapper — neupotrebljiv kao izvor)
  - čiste se isključivo dm imena izvedena iz state zapisa,
    nikad pattern matching po `dmsetup ls`
  - bez backup-a: repoint direktno na state.origin (by-id)
- `lib/repair.py`: `decide_action()` je čista funkcija (testabilna
  bez root-a), pokriva svih 12 kombinacija phase × dev × dm

## 0.3.2-alpha (2026-07-19)

- `ram_prealloc` opcija (default: true): pri `up` se dodirne svaka
  stranica ramdiska (dd nulama) — svih 12G je REZERVISANO odmah,
  vidljivo u htop/free, bez rizika kasnijeg OOM-a kad se keš zagreje.
  `false` vraća lenju brd alokaciju (memorija raste sa punjenjem).

## 0.3.1-alpha (2026-07-18)

- Formalna specifikacija state fajla: `docs/state.md` + JSON Schema
  (`docs/state.schema.json`)
- state format v1: `{"version": 1, "caches": {...}}` sa automatskom
  migracijom starog formata; atomičan upis
- Novo polje `phase` (attaching/active/detaching) — sidro za oporavak
- FIX redosleda u `up()`: state zapis (phase=attaching) se pravi PRE
  repoint-a saveconfig-a. Ranije je pad između repoint-a i upisa state-a
  ostavljao saveconfig na mapper uređaju za koji state ne zna.
- `down()` upisuje phase=detaching pre prvog destruktivnog koraka
- `list` prikazuje phase i upozorava na prekinute procedure
- Tabela tumačenja stanja posle pada u docs/state.md = specifikacija
  buduće `repair` komande

## 0.3.0-alpha (2026-07-18)

Cilj verzije: QNAP-stil "cache block device" — ubrzanje postojećeg
RAID/LIO storage-a RAM keširanjem, bez diranja identiteta LUN-a.

### Ključni koncept

`yellowstone up NAME` radi celu proceduru u jednom downtime prozoru:

1. Pročita backstore NAME iz saveconfig.json (source of truth)
2. Rezolvuje origin u stabilnu /dev/disk/by-id/ putanju
3. Proveri MemAvailable (cache + headroom) — fail-fast PRE gašenja LIO-a
4. Zaustavi LIO (`targetctl clear`; saveconfig.json netaknut)
5. Napravi RAM disk (brd, fiksno cache_ram, default 12G)
6. Napravi dm-cache (writethrough) iznad origin-a
7. Promeni SAMO "dev" polje u saveconfig.json → /dev/mapper/NAMECached
   — **WWN, LUN, ACL, atributi netaknuti** → ESXi vidi identičan NAA ID
8. Pokrene LIO (`targetctl restore`), izmeri i loguje downtime

Bilo koji neuspeh posle koraka 4 → automatski rollback
(restore backup-a konfiguracije, uklanjanje dm/RAM sloja, LIO na origin).

`yellowstone down NAME` je ogledalo: repoint na origin (by-id),
cleaner flush, uklanjanje dm-cache i RAM diska, LIO nazad.

### Novo

- `lib/lio.py`: `get_storage_object()`, `set_device()` (atomičan upis,
  menja isključivo "dev"), `backup_config()`, `restore_backup()`
- `lib/sysinfo.py`: provera MemAvailable bez izvršavanja komandi
- `lib/config.py`: `cache_type` (ram|device), `cache_ram`,
  `memory_headroom`, parser veličina (12G, 512M...)
- Skripte: `ram_create.sh`, `ram_destroy.sh`, `lio_stop.sh`,
  `lio_start.sh`, `resolve_device.sh`
- `systemd/`: opcioni auto režim (Before=target.service + drop-in);
  default je ručni režim (admin pokreće `up` posle boot-a,
  target.service disabled)
- CLI: `up`, `down` (zahtevaju root), merenje downtime prozora

### Bezbednosna pravila ugrađena u kod

- `cache_type=ram` + `cache_mode=writeback` → config se ODBIJA
  (dirty podaci samo u RAM-u = gubitak podataka pri nestanku struje)
- `up` odbija ako MemAvailable < cache_ram + memory_headroom
- backup saveconfig.json pre svake izmene, upis atomičan
  (temp + rename + fsync)
- rollback vraća LIO na origin pri bilo kom neuspehu

## 0.2.0-alpha

- Ispravke iz code review-a (importi, config/manager, status kodovi,
  logger, kolizija lib/cache.py vs lib/cache/)
- dm-cache skripte, CLI, JSON izlaz, parser statistike, state evidencija

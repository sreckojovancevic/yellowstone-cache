# Yellowstone Cache — Uputstvo za korišćenje

Verzija: 0.3.2-alpha

## Šta je Yellowstone Cache

Alat koji postojećem Linux LIO storage serveru (iSCSI/FC target) dodaje
RAM ili NVMe read-cache sloj preko dm-cache-a — **bez diranja podataka
na disku i bez promene identiteta LUN-a**.

Ključna garancija: WWN, LUN brojevi, ACL-ovi i atributi backstore-a
ostaju netaknuti. Initiator (ESXi, Windows, Linux) vidi isti disk pre
i posle — menja se samo brzina. Na origin uređaj (RAID) se ne upisuje
nijedan bajt administracije keša; skidanjem keša disk je u stanju kao
da Yellowstone nikad nije postojao.

```text
   PRE                                POSLE up
   ---                                --------
   ESXi                               ESXi                (isti NAA ID)
    │                                  │
   LIO backstore                      LIO backstore       (isti WWN/LUN/ACL)
    │                                  │
   /dev/disk/by-id/wwn-...           /dev/mapper/<NAME>Cached
   (RAID)                              │
                                     dm-cache (writethrough)
                                      │            │
                                   /dev/ram0    /dev/disk/by-id/wwn-...
                                   (12G RAM)    (RAID — netaknut)
```

## Preduslovi

* Linux sa LIO targetom (targetcli-fb / rtslib-fb), konfiguracija u
  `/etc/rtslib-fb-target/saveconfig.json`
* Kernel moduli: `dm_cache`, `brd` (standardni deo kernela)
* Python 3.8+, root pristup
* Za RAM cache: slobodno `cache_ram + memory_headroom` memorije
  (default 12G + 4G)

## Instalacija

```bash
# 1. Raspakuj u /opt
unzip yellowstone-*.zip -d /opt/
cd /opt/yellowstone

# 2. Dozvole
chmod +x bin/yellowstone scripts/*.sh

# 3. Konfiguracija
vi etc/yellowstone.cache

# 4. Provera sistema (bez ikakvih izmena)
bin/yellowstone validate
```

## Konfiguracija (etc/yellowstone.cache)

```ini
[cache]
enable = true
engine = dmsetup

cache_type = ram          # ram | device
cache_ram = 12G           # velicina RAM cache-a
ram_prealloc = true       # rezervisi svu memoriju odmah pri up
memory_headroom = 4G      # minimum koji mora ostati sistemu
cache_device =            # blok uredjaj (samo za cache_type=device)
cache_mode = writethrough # writethrough | writeback
```

**Bezbednosna pravila koja alat sam nameće:**

* `cache_type=ram` + `cache_mode=writeback` → konfiguracija se ODBIJA.
  Writeback drži podatke samo u RAM-u pre upisa na disk — nestanak
  struje bi značio gubitak podataka. RAM cache je uvek writethrough:
  svaki upis je potvrđen tek kad sedne na RAID.
* `up` se odbija ako nema `cache_ram + memory_headroom` slobodne memorije.
* Sve izmene saveconfig.json su atomične i sa automatskim backup-om.

## Komande

Sve komande imaju `--json` varijantu za automatizaciju.
Exit code procesa = status kod operacije (0 = OK).

| Komanda                      | Šta radi                                     | Root |
|------------------------------|----------------------------------------------|------|
| `yellowstone validate`       | Proveri LIO konfiguraciju i uređaje          | ne   |
| `yellowstone up NAME`        | Zakači cache na backstore NAME               | da   |
| `yellowstone down NAME`      | Otkači cache, vrati LIO na origin            | da   |
| `yellowstone status NAME`    | Status + statistika keša (hit ratio, dirty…) | ne   |
| `yellowstone list`           | Svi registrovani keševi i njihove faze       | ne   |
| `yellowstone repair [NAME]`  | Plan oporavka prekinutih procedura (dry-run) | da   |
| `yellowstone repair --apply` | Izvrši plan oporavka                         | da   |
| `yellowstone version`        | Verzija                                      | ne   |

`NAME` je ime backstore-a iz saveconfig.json (npr. `TestDisk`).

## Šta up tačno radi

```text
 1. Učita config i proveri backstore u saveconfig.json
 2. Rezolvuje origin u stabilnu /dev/disk/by-id/ putanju
 3. Proveri slobodnu memoriju (fail-fast, LIO još radi)
 4. Zaustavi LIO                     ← POČETAK DOWNTIME PROZORA
 5. Napravi RAM disk (+ prealloc)
 6. Napravi dm-cache iznad origin-a
 7. Backup saveconfig.json, upiše state (phase=attaching)
 8. Promeni SAMO "dev" polje → /dev/mapper/NAMECached
 9. Pokrene LIO                      ← KRAJ DOWNTIME PROZORA
10. state → phase=active, ispiše trajanje prozora
```

Bilo koji neuspeh u koracima 5-9 → **automatski rollback**: LIO se
vraća na origin, dm/RAM slojevi se čiste, backup konfiguracije stoji.

**Downtime prozor**: initiatori za to vreme vide zastoj I/O (ESXi: APD).
Tipično par sekundi — VM-ovi ne padaju, I/O im kratko stane. Ipak,
`up`/`down` radi u mirnom periodu ili pre paljenja VM-ova.

## Prvi test — preporučena procedura

```bash
# 0. PRE svega: baseline bez keša (fio iz VM-a + esxtop DAVG)

# 1. Provera
yellowstone validate

# 2. Attach (biraj miran trenutak — kratak APD prozor!)
yellowstone up TestDisk
#    → htop na storage serveru: odmah -12G (ram_prealloc)

# 3. Upali VM-ove, pusti da rade

# 4. Prati zagrevanje keša
watch -n 10 'yellowstone status TestDisk --json'
#    → read_hits raste, cache_used raste, hit ratio se penje

# 5. Merenje: fio randread iz VM-a (2x — hladno pa vruće),
#    esxtop na ESXi (kolona DAVG/cmd za LUN)
```

**Napomena o merenju:** sekvencijalni saobraćaj (dd, kopiranje velikih
fajlova, NVR strimovi) smq policy NAMERNO pušta pored keša — to je
ispravno ponašanje, ne kvar. Efekat keša se vidi na random čitanju
(fio `--rw=randread --direct=1`), i to tek u DRUGOM prolazu, kad je
keš topao. Prvi prolaz je uvek miss i ide brzinom RAID-a.

## Ponašanje posle reboot-a / nestanka struje

RAM keš nestaje sa strujom — **podaci NE nestaju** (writethrough:
sve je već na RAID-u). Ali dm mapiranja ne preživljavaju reboot, a
saveconfig.json pokazuje na mapper uređaj koji još ne postoji.

Zato: **LIO ne sme da se diže sam.**

* Ručni režim (default): `systemctl disable target`, pa se admin
  posle boot-a uloguje i pokrene `yellowstone up NAME` — procedura
  ponovo sastavi keš i digne LIO.
* Auto režim (opciono): instaliraj `systemd/yellowstone.service` i
  drop-in za target.service (uputstvo u samim fajlovima) — LIO tada
  fizički ne može krenuti pre nego što Yellowstone završi.

Stanje evidencije proveri sa `yellowstone list` — upozoriće na
prekinute procedure (phase != active). Tumačenje faza: `docs/state.md`.

## Skidanje keša

```bash
yellowstone down TestDisk
```

Vraća "dev" na origin (by-id), flushuje i uklanja dm-cache, oslobađa
RAM, diže LIO. Disk je bajt-za-bajt u stanju kao pre `up` — bez
ostataka, bez potpisa, bez čišćenja.

## Rešavanje problema

| Simptom | Uzrok / rešenje |
|---------|-----------------|
| `up` javlja "Not enough memory" | Oslobodi RAM ili smanji `cache_ram` / `memory_headroom` |
| `up` javlja "already exists" za /dev/ram0 | Zaostali ramdisk: `rmmod brd` pa ponovi |
| hit ratio stoji na ~0 | Saobraćaj je sekvencijalan (bypass po dizajnu) ili keš još hladan — proveri sa fio randread |
| posle reboot-a LIO ne radi | Očekivano u ručnom režimu: pokreni `yellowstone up NAME` |
| `list` javlja "interrupted procedure" | Pad usred up/down — vidi tabelu u `docs/state.md`, backup konfiguracije je u `state/backups/` |
| ESXi izgubio datastore posle up | NE bi smelo da se desi (WWN se ne menja). Proveri da li je neko menjao backstore mimo alata; rollback: `down` ili vrati backup iz `state/backups/` + `targetctl restore` |

## Logovi i stanje

```text
logs/yellowstone.log      — svi događaji (INFO/WARNING/ERROR/DEBUG)
state/caches.json         — evidencija keševa (spec: docs/state.md)
state/backups/            — backup saveconfig.json pre svake izmene
```

## Ograničenja trenutne verzije

* Jedan RAM cache po serveru (`/dev/ram0` fiksno)
* bcache/lvmcache engine-i su predviđeni interfejsom, nisu implementirani

## Repair — kada i kako se koristi

`repair` poredi tri izvora istine (state/caches.json, saveconfig.json,
kernel dm) i razrešava svaku nekonzistentnost po tabeli iz
`docs/state.md`.

**Bezbedan je za pokretanje u bilo kom trenutku**: bez `--apply` ništa
ne menja — samo prikaže zatečeno stanje i plan. Tek `--apply` izvršava,
i to plan koji si već video.

```bash
yellowstone repair            # dijagnostika + plan (ništa ne menja)
yellowstone repair --apply    # izvrši plan
yellowstone repair NAME       # samo za jedan backstore
```

### Situacija 1: posle svakog reboot-a (standardna boot procedura)

U ručnom režimu ovo je redovan način dizanja sistema. Posle restarta:
RAM keš ne postoji, saveconfig pokazuje na mapper uređaj koga nema,
LIO stoji dole (target.service je disabled). Admin se uloguje:

```bash
yellowstone repair          # → akcija: recreate
yellowstone repair --apply  # sastavi ramdisk + dm-cache, digne LIO
```

Origin za ponovno sastavljanje se uzima iz state evidencije (stabilna
by-id putanja) — ne iz saveconfig-a, koji u tom trenutku pokazuje na
mapper. Podaci su netaknuti (writethrough — sve je već na RAID-u);
keš kreće prazan i ponovo se greje.

### Situacija 2: pad usred up/down procedure

`up` i `down` imaju automatski rollback — ali rollback radi samo dok
proces živi. Nestanak struje ili kill USRED procedure ostavlja sistem
na pola puta (state: `attaching`/`detaching`). Repair tada, zavisno od
zatečenog stanja: dovrši attach, uradi rollback na origin, dovrši
detach ili samo očisti ostatke. Ako backup konfiguracije ne postoji,
repoint se radi direktno na origin iz state-a.

### Situacija 3: `list` prijavi prekinutu proceduru

```text
[WARN] 'TestDisk' has interrupted procedure (phase=attaching) ...
```

→ pokreni `repair`, pogledaj plan, `--apply`.

### Kratko pravilo

* `up` / `down` — namerna promena stanja
* `repair` — kad god stvarnost i evidencija možda nisu iste
  (posle reboot-a NIKAD nisu → repair je ujedno boot procedura)
* `repair` bez `--apply` — slobodno, uvek, čisto dijagnostički;
  odgovor `healthy` znači da je sve konzistentno

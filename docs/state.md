# Specifikacija: state/caches.json

Autoritativan opis formata i životnog ciklusa state fajla.
Mašinski čitljiva schema: `docs/state.schema.json`.

## Uloga

state/caches.json je evidencija onoga što je Yellowstone kreirao i
**sidro za oporavak**. Sistem ima tri izvora istine:

1. `/etc/rtslib-fb-target/saveconfig.json` — šta LIO eksportuje
2. `state/caches.json` — šta je Yellowstone uradio i dokle je stigao
3. kernel device-mapper (`dmsetup`) — šta stvarno postoji SADA

Posle pada sistema, poređenje ova tri izvora jednoznačno govori u kom
koraku je procedura prekinuta.

## Format fajla

```json
{
  "version": 1,
  "caches": {
    "TestDisk": {
      "phase": "active",
      "origin": "/dev/disk/by-id/wwn-0x5000c500a1b2c3d4",
      "origin_at_attach": "/dev/sdc",
      "cache_type": "ram",
      "cache_device": "/dev/ram0",
      "mode": "writethrough",
      "dm_name": "TestDiskCached",
      "backup": "/opt/yellowstone/state/backups/saveconfig-20260718-213000.json"
    }
  }
}
```

## Polja

| Polje              | Obavezno | Vrednosti / format                        | Značenje |
|--------------------|----------|-------------------------------------------|----------|
| `version` (vrh)    | da       | `1`                                       | Verzija formata fajla. Svaka nekompatibilna izmena formata MORA povećati broj i dodati migraciju u `state.py::_load()`. |
| `phase`            | da       | `attaching` / `active` / `detaching`      | Faza životnog ciklusa (vidi dole). |
| `origin`           | da       | apsolutna putanja                         | STABILNA putanja origin uređaja (`/dev/disk/by-id/...`). Koristi se za detach i za svaki budući assemble — nikad sdX. |
| `origin_at_attach` | da       | apsolutna putanja                         | Putanja koja je bila u saveconfig.json u trenutku attach-a (istorijski trag, samo za dijagnostiku). |
| `cache_type`       | da       | `ram` / `device`                          | Tip cache uređaja. |
| `cache_device`     | da       | apsolutna putanja                         | Cache uređaj (`/dev/ram0` ili blok uređaj). Za `ram` NE preživljava reboot. |
| `mode`             | da       | `writethrough` / `writeback`              | dm-cache režim. Za `cache_type=ram` uvek `writethrough` (nameće config). |
| `dm_name`          | da       | ime bez putanje                           | Ime dm cache target-a; pomoćni targeti su `<dm_name>-cmeta` i `<dm_name>-cdata`. |
| `backup`           | ne       | apsolutna putanja                         | Backup saveconfig.json napravljen NEPOSREDNO pre repoint-a u ovoj proceduri. |

Ključ zapisa (`TestDisk`) je ime LIO backstore-a iz saveconfig.json.

## Životni ciklus — kada se šta upisuje

Redosled upisa je deo specifikacije, jer od njega zavisi oporavak.

### up(name)

```
 1. provere (config, backstore, memorija)     state: bez izmene
 2. stop LIO                                  state: bez izmene
 3. ram_create + dm-cache create              state: bez izmene
 4. backup saveconfig                         state: bez izmene
 5. >>> register(name, phase="attaching") <<<
 6. repoint "dev" u saveconfig.json
 7. start LIO
 8. >>> set_phase(name, "active") <<<
 -  rollback (bilo koji neuspeh 3-7):         state: unregister(name)
```

Zapis se pravi PRE repoint-a (korak 5→6): ako sistem padne između
repoint-a i starta, state zna za proceduru i `down`/`repair` mogu da
je razreše. Obrnuti redosled bi ostavio saveconfig koji pokazuje na
mapper uređaj za koji state ne zna — najgori mogući ishod.

### down(name)

```
 1. >>> set_phase(name, "detaching") <<<
 2. stop LIO
 3. backup + repoint "dev" na origin
 4. destroy dm-cache (+ ram_destroy)
 5. start LIO
 6. >>> unregister(name) <<<
```

### Tumačenje posle pada / reboot-a

| Zatečeno stanje                  | Značenje                            | Akcija |
|----------------------------------|-------------------------------------|--------|
| nema zapisa                      | cache ne postoji                    | ništa |
| `phase=active`, RAM prazan posle reboot-a | normalan reboot RAM keša   | ponovo `up` procedura (admin ili service); saveconfig pokazuje na mapper koji ne postoji dok se ne sastavi |
| `phase=attaching`                | pad usred up() koraka 5-8           | proveri saveconfig: pokazuje li na mapper → dovrši ili vrati iz `backup`; pokazuje li na origin → samo očisti dm/ram ostatke i unregister |
| `phase=detaching`                | pad usred down()                    | proveri saveconfig: origin → dovrši čišćenje i unregister; mapper → ponovi down |

Ova tabela je specifikacija buduće `yellowstone repair` komande.

## Pravila izmene formata

1. Novo opciono polje: dozvoljeno bez podizanja verzije.
2. Novo obavezno polje, preimenovanje, promena semantike: `version + 1`
   i migracija u `_load()`.
3. Fajl bez `version` polja je pred-verzionisani format (v0.3.0-alpha)
   i migrira se automatski.

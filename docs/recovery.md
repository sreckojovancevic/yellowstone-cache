# Yellowstone Storage & ESXi Disaster Recovery Manual

Detaljne, terenski proverene procedure za oporavak Yellowstone SAN
storage-a i ESXi hostova nakon potpunog prekida napajanja (blackout),
hladnog restarta ili pada Fibre Channel veza.

Napisano posle stvarnog incidenta (blackout, agregat se nije upalio,
UPS-ovi nisu izdržali, jul 2026).

---

## 📋 Brzi pregled arhitekture

* **Storage Node:** `yellowstone` (Ubuntu, kernel 6.8)
* **Storage Stack:** HDD Array (`/dev/sdb`) + **RAM cache 16 GiB**
  (brd modul, `dm-cache` u `writethrough` režimu, Yellowstone Cache alat)
* **Mapper Target:** `/dev/mapper/TestDiskCached` (14.6 TiB, GPT / VMFS-6)
* **SAN Protocol:** LIO Target preko QLogic Fibre Channel HBA
* **ESXi Datastore Name:** `PRIVREMEN15T`
* **LIO NAA ID:** `naa.60014051c81a9c25556438cb1b17fa4b`
* **LIO konfiguracija:** `/etc/rtslib-fb-target/saveconfig.json`
  (Ubuntu putanja; na RHEL/Rocky bi bila /etc/target/)

---

## 🛠️ SCENARIO 1: Oporavak Yellowstone Storage-a (Linux Node)

Nakon dolaska struje LIO i dm-cache se NE podižu automatski —
**namerno**: `target.service` je disabled, sve diže Yellowstone alat
pod kontrolom admina, kad se hardver stabilizuje.

### Korak 1: Provera stanja diskova

```bash
lsblk -o NAME,SIZE,TYPE,RO,MOUNTPOINTS
```

Očekivano PRE oporavka: vidljiv je samo fizički disk `/dev/sdb` (14.6T).
**`/dev/ram0` i mapper uređaji NE postoje još — to je normalno**
(RAM keš nestaje sa strujom i sastavlja se u sledećem koraku).

### Korak 2: Sastavljanje keša i dizanje LIO-a

```bash
sudo /opt/yellowstone/bin/yellowstone repair          # plan (recreate)
sudo /opt/yellowstone/bin/yellowstone repair --apply  # izvrši
```

`repair --apply` će: napraviti RAM disk (16 GiB, prealloc), sastaviti
dm-cache nad originom (origin čita iz state-a, po stabilnoj by-id
putanji), i pokrenuti LIO iz saveconfig.json. WWN/NAA ostaje identičan.

### Korak 3: Verifikacija

```bash
# Status keša: mode writethrough, dirty 0
sudo /opt/yellowstone/bin/yellowstone status TestDisk

# Kernel vidi VMFS particiju
sudo fdisk -l /dev/mapper/TestDiskCached
```

Provera: fdisk mora prikazati particiju tipa VMware VMFS.
Podaci su bezbedni bez obzira na trenutak pada: **writethrough znači
da je svaki potvrđeni upis već bio na RAID-u pre nestanka struje.**

---

## 🔌 SCENARIO 2: Oporavak ESXi hostova (mrtvi lock-ovi)

Svaki ESXi host koji je imao pokrenute VM-ove u momentu prekida
zadržava "mrtve" lock-ove (World ID-jeve) nad LUN-om.

> ⚠️ **UPOZORENJE:** komanda ispod nasilno ubija SVE procese nad
> LUN-om. Koristiti ISKLJUČIVO posle pada napajanja/storage-a, kada su
> ti procesi ionako mrtvi. NIKAD na zdravom hostu sa živim VM-ovima.

Na hostu gde je datastore zasivljen/nevidljiv, preko SSH:

```bash
LUN="naa.60014051c81a9c25556438cb1b17fa4b"; for w in $(esxcli storage core device world list | grep "$LUN" | awk '{print $2}'); do esxcli vm process kill --type=force --world-id=$w; done; esxcli storage core adapter rescan --all; esxcli storage filesystem rescan; vmkfstools -V
```

Šta radi: (1) nađe zaglavljene world-ove nad LUN-om, (2) ubije ih,
(3) rescan svih HBA, (4) osveži VMFS tabele.

---

## ⚡ SCENARIO 3: LUN se uopšte ne vidi (zaglavljen HBA drajver)

Posle naponskih udara usred I/O, QLogic/Emulex FC drajver
(`qlnativefc`) može ući u queue freeze: link je up, ali komunikacija
stoji i običan rescan ne pomaže.

### Korak 1: Duboki rescan (zameni vmhba4 svojim adapterom)

```bash
esxcli storage core adapter rescan --adapter=vmhba4 --type=all
```

`--type=all` resetuje komunikacione redove drajvera — običan rescan
radi samo površinsko skeniranje.

### Korak 2: Provera "Detached" black-liste

```bash
esxcli storage core device detached list
```

Ako je naš NAA na listi:

```bash
esxcli storage core device set --state=on -d naa.60014051c81a9c25556438cb1b17fa4b
```

### Korak 3: Osvežavanje i provera

```bash
esxcli storage filesystem rescan
vmkfstools -V
ls -l /dev/disks/naa.60014051c81a9c25556438cb1b17fa4b*
```

Očekivano u /dev/disks/: goli NAA (LUN) + `NAA:1` (VMFS particija).

---

## 🌐 SCENARIO 4: GUI ne prikazuje datastore / vCenter redosled

Ako /dev/disks/ vidi `:1` particiju a GUI ne prikazuje datastore:

1. `esxcli storage filesystem rescan && vmkfstools -V`
2. ESXi Web GUI: **Ctrl + F5** (hard refresh — GUI keš ume da laže)
3. vCenter redosled:
   * prvo oporavi storage na hostu gde leži vCenter VM
   * pokreni vCenter VM direktno iz ESXi GUI-ja
   * iz vCenter-a: Rescan Storage na nivou klastera za ostale hostove

---

## 💡 Važne napomene

1. **Zašto writethrough spava mirno:** svi upisi idu sinhrono na RAM
   keš i na RAID — potvrda initiatoru stiže tek kad RAID ima podatak.
   Nagli prekid napajanja briše samo keš (koji se ionako gradi iznova),
   nikad podatke.
2. **Zašto se NAA nikad ne menja:** LIO čuva NAA/WWN u
   `/etc/rtslib-fb-target/saveconfig.json`, a Yellowstone alat pri
   attach/detach menja isključivo `dev` polje. Isti NAA = ESXi ne traži
   Resignature niti reformat.
3. **Redosled dizanja cele sale:** storage uređaji (potpuno) → FC/LAN
   switchevi → ESXi hostovi → vCenter → ostali VM-ovi. Yellowstone
   node: boot → `repair --apply` → tek onda ESXi rescan.
4. **`--type=all`** je razlika između "rescan koji ništa ne vidi" i
   oporavka zamrznutog FC drajvera — prvi alat za posezanje kad LUN
   fizički postoji a host ga ne vidi.

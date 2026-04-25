# Wearable Sync — iOS Shortcut Recipe

Goal: Apple Watch / iPhone health data flows into the workspace daily without typing.

## Path: file-based, local-only

The skill watches `<person-folder>/inbox/wearable/` for `.xml` and `.csv` files. When you run `sync-wearable`, every file is imported, moved to `Archive/wearable/`, and the workspace is updated.

The pieces below let you make that drop happen automatically from your phone — without any cloud service.

---

## Option A — Daily CSV via iOS Shortcut (recommended)

This Shortcut runs once a day, exports yesterday's HealthKit metrics to a CSV in the right folder, and the watcher picks it up next time you open the workspace.

### Setup

1. Open the **Shortcuts** app on iPhone or iPad.
2. Tap **+** to create a new Shortcut.
3. Add these actions in order:

#### 1. Find Health Samples (steps)

```
Find Health Samples
  Type: Steps
  Date Range: Yesterday
```

Repeat the same action for each metric you want:

- Resting Heart Rate
- VO2 Max
- Body Mass
- Oxygen Saturation
- Heart Rate Variability
- Sleep Analysis (asleep)

#### 2. Build a CSV

Use a **Text** action and assemble:

```
date,metric,value,unit
{Yesterday's date},steps,{Statistical: Sum of "Find Steps"},
{Yesterday's date},heart_rate,{Average of "Find RHR"},bpm
{Yesterday's date},vo2_max,{Average of "Find VO2"},ml/kg/min
{Yesterday's date},weight,{Average of "Find Body Mass"},kg
{Yesterday's date},spo2,{Average of "Find SpO2"},%
{Yesterday's date},hrv,{Average of "Find HRV"},ms
```

(Replace each `{...}` with the matching Magic Variable from the previous step.)

#### 3. Save to Files

```
Save File
  File Name: wearable-{Today's Date}.csv
  Destination: On My iPhone / iCloud Drive
  Folder: <pick the wearable inbox path you sync to your Mac>
```

Most users either:
- Symlink `inbox/wearable/` into iCloud Drive on the Mac, or
- Save to `Shortcuts/HealthSync/` and the watcher pulls from there.

#### 4. Automate it

In the **Automation** tab of Shortcuts, create a daily trigger:
- When: Every day at 7:00 AM
- Run: this Shortcut
- Run without confirmation: Yes

### Then on your Mac

```bash
scripts/care_workspace.py sync-wearable --root .
```

Or wire it into a launchd job that runs every morning.

---

## Option B — Apple Health full export (manual, weekly)

For a full sweep including sleep stages, BP, VO2 trend:

1. Open **Health** app → tap your profile picture top-right
2. Scroll down → **Export All Health Data**
3. Wait for the zip to generate (5–10 minutes for a few years of data)
4. AirDrop / share to your Mac
5. Unzip → drop `export.xml` into `<person-folder>/inbox/wearable/`
6. Run `sync-wearable --root .`

---

## Option C — Oura, Whoop, Garmin

Each platform has CSV/JSON export:

- **Oura**: cloud.ouraring.com → My Data → Download CSV
- **Whoop**: app → menu → My Performance → Export
- **Garmin**: Garmin Connect → settings → Account Information → Export Your Data

Drop the CSV into `inbox/wearable/`. The CSV importer accepts any file with these columns:

```
date,metric,value,unit
2026-04-22,steps,8421,
2026-04-22,heart_rate,57,bpm
2026-04-22,vo2_max,42.3,ml/kg/min
```

Recognised metrics: `steps, heart_rate, rhr, vo2_max, spo2, hrv, weight`.

---

## Privacy

Nothing leaves your devices. The Shortcut writes to local storage; the importer reads from the local filesystem; no network calls.

If you want a fully cloud-free path, save to **On My iPhone** instead of iCloud Drive and AirDrop manually.

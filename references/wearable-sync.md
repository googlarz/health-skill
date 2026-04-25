# Wearable Sync — Apple Health Integration

Goal: Apple Watch / iPhone health data flows into the workspace automatically without any manual step.

## Path: file-based, local-only

The skill watches `<person-folder>/inbox/wearable/` for `.xml`, `.csv`, and `.json` files. When you run `sync-wearable`, every file is imported, moved to `Archive/wearable/`, and the workspace is updated.

The options below let you make that happen automatically from your phone — no cloud service required.

---

## Option A — Health Auto Export + iCloud Drive (recommended, fully automatic)

This is the easiest path. The [Health Auto Export](https://www.healthexportapp.com/) app ($3.99) exports your Apple Watch and iPhone metrics to a JSON file on a schedule. You set it once; data arrives every hour.

### Setup

#### 1. Install Health Auto Export

Download from the App Store: **Health Auto Export - JSON+CSV**.

#### 2. Configure the export

In the app:
- Tap **Exports** → **+** → name it "Health Skill"
- **Format**: JSON
- **Metrics to include**: Step Count, Resting Heart Rate, Heart Rate Variability (SDNN), VO2 Max, Body Mass, Oxygen Saturation, Sleep Analysis, Blood Pressure
- **Export destination**: iCloud Drive → `Health Auto Export/` folder (or any folder)
- **Schedule**: Every hour (or Every day — hourly gives you fresher data)
- Toggle **Auto Export** ON

#### 3. Link the folder to your workspace inbox

On your Mac, open Terminal and create a symlink so the JSON files land directly in your workspace inbox:

```bash
# Replace ~/Health/me with your actual person folder
mkdir -p ~/Health/me/inbox/wearable
ln -sf ~/Library/Mobile\ Documents/com~apple~CloudDocs/Health\ Auto\ Export \
       ~/Health/me/inbox/wearable/health-auto-export
```

Or, in the Health Auto Export app, set the destination folder directly to a folder inside iCloud Drive that you've already configured your Mac to sync.

#### 4. Install the background watcher

This installs a macOS background job (launchd) that runs `sync-wearable` every hour:

```bash
python3 ~/.claude/skills/health-skill/scripts/care_workspace.py setup-watch \
  --root ~/Health/me \
  --person-id me
```

That's it. From this point:
- Health Auto Export writes a JSON to iCloud Drive every hour
- iCloud syncs it to your Mac
- The background job picks it up and imports it into your workspace

#### Check watcher status

```bash
python3 ~/.claude/skills/health-skill/scripts/care_workspace.py setup-watch \
  --root ~/Health/me --person-id me --status
```

#### Uninstall

```bash
python3 ~/.claude/skills/health-skill/scripts/care_workspace.py setup-watch \
  --root ~/Health/me --person-id me --uninstall
```

#### Logs

```
~/Health/me/logs/wearable-sync.log
~/Health/me/logs/wearable-sync-error.log
```

---

## Option B — Daily CSV via iOS Shortcut

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

## Option C — Apple Health full export (manual, weekly)

For a full sweep including sleep stages, BP, VO2 trend:

1. Open **Health** app → tap your profile picture top-right
2. Scroll down → **Export All Health Data**
3. Wait for the zip to generate (5–10 minutes for a few years of data)
4. AirDrop / share to your Mac
5. Unzip → drop `export.xml` into `<person-folder>/inbox/wearable/`
6. Run `sync-wearable --root .`

---

## Option D — Oura, Whoop, Garmin

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

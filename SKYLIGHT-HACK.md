# Skylight Calendar Max — Free Photos Hack

## Goal
Keep the Skylight calendar working (free) AND display photos without paying for Plus subscription.

## What We Know

### Device Info
- **Device IP:** 192.168.4.162
- **MAC:** 78:E3:6D:F4:AA:0C (Espressif WiFi chip)
- **Frame ID:** 4474337
- **Frame email:** killerkastle@ourskylight.com
- **Account:** brett@swaimdesign.com
- **Hardware:** Android tablet with Rockchip SoC, locked-down custom launcher by Glance LLC
- **USB:** USB-C port on back (works with ADB, does NOT provide power)

### How the Device Works
- Maintains a persistent **MQTT over TLS** connection to `a2xzplp9f2eduj.iot.us-east-1.amazonaws.com` on port 8883 (AWS IoT Core)
- This is how it receives push notifications for new photos, calendar updates, config changes
- Only other traffic: NTP time sync to `time.google.com`
- Calendar sync works free, photos are gated behind Plus subscription at the API level (`photos: {enabled: false}` in feature bundle)
- Emailing photos to `killerkastle@ourskylight.com` does NOT work on free plan — Skylight sends a "upgrade to Plus" email back

### Why We Can't Proxy
- MQTT + mutual TLS with device certificates baked into firmware
- Can't MITM without the device's private key
- No HTTP REST endpoints to intercept — everything goes through MQTT

## The Plan

**Keep the Skylight app for calendar. Inject photos directly into the device via ADB.**

### Phase 1: Enable ADB (One-Time Setup)

#### Requirements
- USB-C cable
- PC with ADB tools (Android Studio or standalone platform-tools)
- The Skylight must be powered on separately (USB-C doesn't provide power)

#### Install ADB (if you don't have it)
Option A — Android Studio: https://developer.android.com/studio (ADB installs to `%LOCALAPPDATA%\Android\sdk\platform-tools`)

Option B — Standalone platform-tools (smaller download):
```
https://developer.android.com/tools/releases/platform-tools
```
Extract somewhere and add to PATH or cd into it.

#### Enable Developer Mode on Skylight
1. Connect USB-C from Skylight to PC
2. Hold power button ~2 sec → Power Off/Restart dialog appears
3. Pull down from top of screen with 2 fingers
4. You may get a normal dropdown — repeat steps 2-3 until you get **"System UI keeps stopping"** error popup
5. Tap **"App Info"** on the error dialog
6. This drops you into Android Settings. Navigate to **About Tablet**
7. Scroll down to **Build Number** — tap it **7 times** to enable Developer Mode
8. Go back to **System → Developer Options**
9. Enable **USB Debugging**
10. On your PC, verify connection:
```
adb devices
```
Should show your device listed.

#### Useful ADB Commands
```bash
# Open Android Settings (escape from Skylight app anytime)
adb shell am start -a android.settings.SETTINGS

# Get a shell on the device
adb shell

# Enable wireless ADB (so you don't need the cable after this)
adb tcpip 5555

# Connect wirelessly (after enabling tcpip)
adb connect 192.168.4.162:5555
```

### Phase 2: Explore Photo Storage

Once you have ADB shell access, run these commands to find where the Skylight app stores photos:

```bash
# Find the Skylight app package name
adb shell pm list packages | findstr -i skylight

# Look at app data directories
adb shell ls -la /data/data/com.skylightframe.mobile/
adb shell ls -la /data/data/com.skylightframe.mobile/files/
adb shell ls -la /data/data/com.skylightframe.mobile/cache/

# Check external storage
adb shell ls -la /sdcard/
adb shell ls -la /sdcard/Pictures/
adb shell ls -la /sdcard/DCIM/
adb shell ls -la /sdcard/Download/

# Find any image files on the device
adb shell find /sdcard/ -name "*.jpg" -o -name "*.png" 2>/dev/null
adb shell find /data/data/com.skylightframe* -name "*.jpg" -o -name "*.png" 2>/dev/null

# Check the Skylight app's database for photo references
adb shell ls -la /data/data/com.skylightframe.mobile/databases/

# If you find a SQLite database, pull it for inspection:
adb pull /data/data/com.skylightframe.mobile/databases/ ./skylight-db/
```

**Save the output of ALL of these commands** — paste them back to me and I'll figure out exactly how to inject photos.

### Phase 3: Inject Photos (TBD — depends on Phase 2 findings)

Depending on what we find in Phase 2, the approach will be one of:

#### Option A: Direct File Injection
If the Skylight app loads photos from a local directory:
```bash
# Push a photo to the device
adb push photo.jpg /sdcard/Pictures/skylight/

# Or wherever the app stores them
adb push photo.jpg /data/data/com.skylightframe.mobile/files/photos/
```

#### Option B: Database Injection
If the app tracks photos in a SQLite database, we'd need to:
1. Pull the database
2. Understand the schema
3. Insert rows pointing to our injected photos
4. Push the database back

#### Option C: Sideload a Photo Frame Widget
If the Skylight app's storage is too locked down:
1. Install a photo slideshow widget/app via ADB
2. Configure it to load photos from a network share (SMB) or web URL
3. Run it alongside the Skylight calendar app

```bash
# Example: Install Fotoo (digital photo frame app)
adb install fotoo.apk

# Or a simple gallery with slideshow
adb install simple-gallery-pro.apk
```

### Phase 4: Automate (After Phase 3 Works)

Once we know the injection method, we build automation:

1. **Self-hosted photo server** on webserver (192.168.1.50) — already built at `/opt/skylight-photos`
   - Drag-and-drop web UI at `http://skylight.2azone.com`
   - Accepts photo uploads

2. **Sync script** that runs on a schedule:
   - Pulls new photos from the server
   - Pushes them to the Skylight via wireless ADB (`adb connect 192.168.4.162:5555`)
   - Could run as a cron job on the webserver

3. **Or network-based approach:**
   - If we sideload a photo app, point it to an SMB share or web gallery
   - Photos added to the share automatically appear on the device
   - No ADB needed after initial setup

## Existing Infrastructure

### Already Built
- **Skylight Photos app** at `/opt/skylight-photos` on webserver
  - FastAPI backend + drag-and-drop frontend
  - Service: `skylight-photos.service` (currently stopped)
  - Port: 8007
  - Nginx: `skylight.2azone.com` (internal DNS set up, no SSL — internal only)
  - Originally built to email photos, will repurpose for local photo serving

### Skylight API Info (for reference)
- **Base URL:** `https://app.ourskylight.com`
- **Login:** `POST /api/sessions` with `{"email": "brett@swaimdesign.com", "password": "ZC9pftXZiKdaUFDzio8d"}`
- **Token:** User ID `3687599`, token `27faa1e07281ef6f181d3f627d5ceb34`
- **Auth header:** `Basic base64("3687599:27faa1e07281ef6f181d3f627d5ceb34")`
- **Frame info:** `GET /api/frames` (works), `GET /api/frames/4474337/messages` (works, empty)
- **Feature bundle:** `photos: false`, `videos: false`, `captions: false` (all paywalled)
- **Calendar:** works free
- **Subscription:** "basic" (free tier)

### Firewalla Access
- **IP:** 192.168.4.1
- **User:** pi
- **Password:** sreesrwg83
- **Access from:** webserver via `sshpass -p 'sreesrwg83' ssh pi@192.168.4.1`
- **Skylight device traffic:** Only MQTT to AWS IoT + NTP to Google

## What To Do Right Now

1. **Get a USB-C cable**
2. **Connect Skylight to your PC** (keep it plugged into power too)
3. **Follow Phase 1** to enable Developer Mode and USB Debugging
4. **Run Phase 2 commands** and save all output
5. **Paste the output back to Claude** — I'll design the injection method based on what we find

## Recovery
If anything goes wrong: **Hold power button for 10 seconds** → Factory Reset. All changes are cleared and the device returns to stock.

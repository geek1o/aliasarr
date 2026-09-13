<p align="right">
  <a href="hardlinks_indexers_and_clients.md">Русский</a> | <b>English</b>
</p>

# Guide: Hardlinks, Indexers, and Download Clients in Aliasarr

This document provides a comprehensive overview of the architecture, mechanics, and step-by-step configuration of **Hardlinks**, **selective private tracker seeding**, **indexers**, and **download clients** in **Aliasarr**.

---

## 1. Hardlinks: Principles & Advantages

### What is a Hardlink?
On Linux, macOS, and UNIX-like operating systems, a file on storage consists of two distinct components:
1. **Inode** — Contains file metadata and addresses of data blocks on physical media.
2. **Directory Entry** — A filename path entry within a directory pointing to that specific Inode.

A **Hardlink** creates an additional directory entry (path) pointing to the existing Inode on the same filesystem.

```
                  ┌───────────────────────────────┐
                  │      Physical Disk Blocks     │
                  │   (Inode #482910, Size 8 GB)  │
                  └───────────────┬───────────────┘
                                  │
                 ┌────────────────┴────────────────┐
                 ▼                                 ▼
┌─────────────────────────────────┐ ┌─────────────────────────────────┐
│ /data/downloads/Show.S01E01.mkv │ │ /data/serials/Show/S01E01.mkv   │
│   (Used by torrent client)      │ │   (Used by Plex / Jellyfin)     │
└─────────────────────────────────┘ └─────────────────────────────────┘
```

### Core Advantages of Hardlinks:
1. **Zero Extra Storage Duplication**: A 50 GB file linked via hardlink takes up zero additional bytes. The filesystem stores only one 50 GB physical copy.
2. **Instant Import (0 Milliseconds)**: Creating a hardlink is an atomic pointer write in the filesystem directory table. Even an 80 GB 4K BD-Remux links in a fraction of a millisecond with zero I/O copying.
3. **Zero Storage Wear & Latency**: Eliminates disk read/write throughput bottlenecks, CPU usage, and SSD/HDD degradation.
4. **Continuous, Safe Seeding**: The torrent client continues actively seeding the original file in `/data/downloads`, while media servers (Plex, Jellyfin, Emby) stream the neatly renamed file from `/data/films` or `/data/serials`.
5. **Safe Deletion**: When seeding quotas are satisfied, Aliasarr removes the file from `/data/downloads`. The physical data is **never lost** — the Inode reference count simply decrements from 2 to 1, leaving the library file fully intact.

---

## 2. Configuring Hardlinks in Aliasarr

1. Open the **Aliasarr** web interface.
2. Navigate to **«Settings»** $\to$ tab **«Media Management / Folders»**.
3. Locate the **«Hardlinks and Seeding Management»** section.
4. Ensure that the toggle **«Use Hardlinks instead of copying»** is enabled (enabled by default).
5. Click **«Save»**.

> **Automatic Fallback:** If hardlink creation is impossible (for instance, if the downloads folder and media folder reside on separate disk mounts or independent ZFS datasets), Aliasarr automatically and transparently falls back to safe file copying (`shutil.copy2`), maintaining file integrity.

---

## 3. Configuring Indexers (Trackers)

Aliasarr supports flexible tracker integration with granular control over seeding policies for each source.

### Supported Indexer Types:
- **Torznab** — Native integration with **Prowlarr**, **Jackett**, or native tracker APIs.
- **Nyaa.si** — Direct built-in search and anime release parsing.
- **Newznab** — Usenet indexer support.
- **Torrent RSS / IPTorrents / TorrentLeech** — Personalized RSS feeds and tracker APIs.

### Step-by-Step Indexer Setup:
1. Go to the **«Indexers»** section.
2. Click **«Add Indexer»** (or the edit icon for an existing indexer).
3. Fill in the primary parameters:
   - **Name:** Tracker name (e.g. `Prowlarr - IPTorrents` or `RuTracker`).
   - **Type:** Select indexer type (`Torznab`, `Nyaa`, `Torrent RSS`, etc.).
   - **URL:** API or aggregator endpoint.
   - **API Key:** Access key (if required).
   - **Priority:** From 1 (highest) to 1000 (lowest). Higher priority indexers are evaluated first.

---

### Selective Seeding Settings

Inside each indexer's modal, there is a toggle **«Seed downloaded files (for private / ratio trackers)»**:

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [x] Seed downloaded files (for private / ratio-enforced trackers)        │
├──────────────────────────────────────────────────────────────────────────┤
│ Seed Ratio Limit:            [ 1.5 ]           (empty = unlimited)       │
│ Seed Time Limit (hours):     [ 72 ]            (empty = unlimited)       │
└──────────────────────────────────────────────────────────────────────────┘
```

#### Configuration Recommendations:
* **Public Trackers (RuTracker, Rutor, Nyaa, Kinozal, etc.):**
  - Keep the **«Seed» checkbox disabled**.
  - Downloaded files will be moved directly to the library, and the torrent task will be cleaned up from the client without taking up download buffer space.
* **Private / Ratio Trackers (IPTorrents, TorrentLeech, Tapochek, HDBits, Gazelle, etc.):**
  - **Enable the «Seed» checkbox**.
  - **Seed Ratio Limit:** Enter the required ratio threshold (e.g., `1.0`, `1.5`, or `2.0`). Leaving it empty disables ratio-based removal.
  - **Seed Time Limit:** Enter the minimum seeding duration in hours (e.g., `12`, `72` for 3 days, or `168` for 7-day Hit & Run rules). Leaving it empty keeps the torrent seeding indefinitely `(∞)`.
  - In the indexers table, the tracker will display a green `Seed 1.5x` badge.

---

### Seeding Telemetry in «Activity & Queue»

In the download queue, Aliasarr surfaces detailed seeding telemetry for each torrent:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ TITLE / EPISODES           CLIENT          SPEED / SEEDING        PROGRESS  STATUS     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ INVINCIBLE (2021)          Transmission    —                      100%      seeding    │
│ 8 eps  [Tapochek]                          11h 53m / 12h          17.5 GiB             │
│                                            Remaining: 6m                               │
│                                            Ratio: 0.06                                 │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Occult Academy             Transmission    —                      100%      pausedup   │
│ 19 eps [RuTracker]                         33s (∞)                24.1 GiB             │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Fixed Duration Timers (`11h 53m / 12h` + `Remaining: 6m`):**
   - Displays current seeding elapsed time versus the target quota.
   - The «Remaining» countdown calculates time until mandatory seeding requirements are met.
2. **Indefinite Seeding (`[time] (∞)`):**
   - The infinity symbol `(∞)` appears when no time limit is imposed on a tracker or release. The torrent will not be automatically pruned, protecting your tracker standing.
3. **Upload Ratio (`Ratio: X.XX / Y.YY` or `Ratio: X.XX`):**
   - Shows uploaded data volume relative to downloaded size.
4. **Client Statuses:**
   - `seeding` — Actively uploading to network peers.
   - `pausedup` — Torrent is paused or waiting for resumed bandwidth in the client.

---

## 4. Download Client Integration

Aliasarr connects to leading torrent clients via official RPC and REST APIs.

### Supported Clients:
- **qBittorrent** (API v2)
- **Transmission** (RPC API)

### Step-by-Step Client Setup:
1. Navigate to **«Settings»** $\to$ tab **«Download Clients»**.
2. Click **«Add Client»** or select an existing instance.
3. Enter connection parameters:
   - **Name:** Client identifier (e.g., `qBittorrent Primary`).
   - **Type:** `qbittorrent` or `transmission`.
   - **Host:** Host IP address or container hostname (e.g., `192.168.1.100` or `qbittorrent` within a shared Docker network).
   - **Port:** Web UI port (default `8080` for qBittorrent, `9091` for Transmission).
   - **Username / Password:** Web UI credentials.
   - **Category:** Category tag used in the client (e.g., `aliasarr` or `media`).
4. Click **«Test»** to verify connectivity.
5. Click **«Save»**.

---

### How Aliasarr Manages Client Seeding:
1. When submitting releases to a download client, Aliasarr automatically invokes:
   - `setShareLimits` in **qBittorrent**
   - `seedRatioLimit` and `seedIdleLimit` in **Transmission**
2. The client is aware of the specific torrent's quotas from the second it starts.
3. The background `DownloadsMonitor` service continuously tracks seeding progress.
4. When thresholds are achieved, Aliasarr removes the finished torrent and clears the temporary download folder.

---

## 5. Docker & ZFS / RAID Best Practices

For hardlinks to function instantly and seamlessly, all related paths must reside on the **same filesystem mount**:

### Incorrect Docker Mapping (Hardlinks FAIL):
```yaml
# With separate mounts, Docker interprets /downloads and /movies as two DIFFERENT virtual filesystems:
services:
  aliasarr:
    volumes:
      - /mnt/storage/downloads:/downloads  # Disk 1
      - /mnt/storage/movies:/movies        # Disk 2
      - /mnt/storage/tv:/tv                # Disk 3
```
*Result:* The kernel returns an `EXDEV: Invalid cross-device link` error, forcing a full physical file copy.

---

### Correct Docker Mapping (Single Mount Point):
```yaml
services:
  aliasarr:
    image: ghcr.io/lqwestl/aliasarr:latest
    container_name: aliasarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=UTC
    volumes:
      - ./config:/config
      - /data:/data                       # Single unified mount for all media
    ports:
      - "8989:8989"
    restart: unless-stopped

  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent:latest
    container_name: qbittorrent
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=UTC
    volumes:
      - ./qbittorrent/config:/config
      - /data:/data                       # Same unified mount
    ports:
      - "8080:8080"
      - "6881:6881"
      - "6881:6881/udp"
    restart: unless-stopped
```

### Folder Structure Inside Aliasarr:
- Download Folder: `/data/downloads`
- Movies Root Folder: `/data/films`
- Series Root Folder: `/data/serials`
- Anime Root Folder: `/data/anime`

### ZFS / Btrfs Specifics:
- When `/data` is a single ZFS dataset (e.g., RAID-Z1 across multiple disks), hardlinking between `/data/downloads` and `/data/serials` takes **0 ms** and **0 bytes**.
- If distinct ZFS datasets are created for each folder (`zfs create pool/downloads`, `zfs create pool/films`), ZFS treats them as separate filesystems. Keep subdirectories inside a single dataset to maintain hardlink support.

---

## 6. Download Lifecycle Scenarios

```
                       ┌─────────────────────────┐
                       │      Grab Release       │
                       │     (Auto / Manual)     │
                       └────────────┬────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │ Download Client Activity│
                       │    (/data/downloads)    │
                       └────────────┬────────────┘
                                    │
                         Torrent reaches 100%
                                    │
                     ┌──────────────┴──────────────┐
                     ▼                             ▼
           [Seeding Disabled]             [Seeding Enabled]
            (Public Tracker)              (Private Tracker)
                  │                                │
                  ▼                                ▼
       ┌────────────────────┐            ┌────────────────────┐
       │     Move File      │            │  Create Hardlink   │
       │   (shutil.move)    │            │     (os.link)      │
       └──────────┬─────────┘            └──────────┬─────────┘
                  │                                 │
                  ▼                                 │ 0 byte duplication,
       ┌────────────────────┐                       │ instant streaming
       │   Remove Torrent   │                       ▼
       │    from Client     │            ┌─────────────────────┐
       └────────────────────┘            │ Active Client Seed  │
                                         │   until Quotas Met  │
                                         └──────────┬──────────┘
                                                    │
                                           Ratio/Time limit reached
                                                    │
                                                    ▼
                                         ┌─────────────────────┐
                                         │ Clean Up Torrent &  │
                                         │   /data/downloads   │
                                         │ (Library Intact)    │
                                         └─────────────────────┘
```

---

## 7. Diagnostics & FAQ

### How can I verify that a Hardlink was created instead of a copy?
Connect to your host via SSH and run `ls -l` or `stat`:
```bash
ls -l "/data/downloads/Show.S01E01.mkv" "/data/serials/Show/Season 01/Show - S01E01.mkv"
```
**Signs of a true hardlink:**
1. **Link count (the second column in `ls -l`) is `2`** (or higher).
2. **Inode numbers match identically**:
   ```bash
   stat -c "%i %n" "/data/downloads/Show.S01E01.mkv" "/data/serials/Show/Season 01/Show - S01E01.mkv"
   # Output:
   # 482910 /data/downloads/Show.S01E01.mkv
   # 482910 /data/serials/Show/Season 01/Show - S01E01.mkv
   ```

### What happens if I manually delete a file from my media library?
The copy in `/data/downloads` continues seeding normally. Deleting one path simply decrements the Inode reference count. Physical disk data is only freed once **all** paths referencing that Inode are removed.

### What should I do if I see `Invalid cross-device link` in logs?
This indicates that your download folder and media library are mounted across different virtual mount points or separate filesystems/datasets. Aliasarr will perform a safe copy fallback. To enable true instant hardlinks, reconfigure your Docker volume mounts to share a single root `/data:/data`.

### What happens when both Ratio Limit and Time Limit are specified?
The engine operates on a **«whichever comes first» (logical OR)** basis:
- **Popular releases:** If the target Ratio (e.g., `1.5`) is achieved rapidly (say, within 8 hours), the task concludes immediately without waiting for the time limit.
- **Low-demand releases:** If the target Ratio is not reached within the specified time (e.g., `72 hours`), the task cleanly finishes once 72 hours expire, preventing disk accumulation while honoring tracker Hit & Run policies.

### Who takes precedence: Tracker Seeding Rules or Download Client Defaults?
1. **The Tracker (Indexer) has highest priority:** Each tracker has distinct community rules (RuTracker requires no seeding, TorrentLeech requires 1.0 ratio or 72 hours). Aliasarr applies the exact rule matching the origin tracker.
2. **Download Client settings serve as fallback:** Generic client settings are only referenced when a torrent is imported without an associated indexer.

### What does the `(∞)` symbol mean in the Activity queue?
The infinity symbol `(∞)` signifies that **no time limit is configured** for this tracker or torrent. Aliasarr will never prune the release based on elapsed time, allowing unlimited seeding until manually stopped.

### How are combined releases (Season batches + Specials / OVAs) handled?
If a torrent package bundles regular episodes and special features:
1. Regular season episodes are identified and imported **automatically**.
2. Specials (Season 0) require manual verification and enter manual import mode.
3. **Folder Protection:** Aliasarr **does not prune** the source download folder until specials are mapped and imported via the **«Import Specials»** action in the title card.
4. **Import Modes:**
   - **«Move»**: Transfers files into the media library and removes source files once all items are imported.
   - **«Copy / Hardlink»**: Generates library links while preserving source files for continuous client seeding.

<p align="right">
  <a href="scoped_aliases_and_offsets.md">Русский</a> | <b>English</b>
</p>

# Guide: Scoped Search Aliases, Episode Range Binding, and Number Offsets (+Offset)

## Introduction & Purpose

In major metadata databases (Shikimori, AniList, TheTVDB, TMDB, AniDB), many popular titles are cataloged as a **single season with continuous, flat episode numbering** (for instance, 24–26 episodes in Season 1).

Common examples include:
- *Space Dandy* (26 episodes in Season 1)
- *Mushoku Tensei: Jobless Reincarnation* (23 episodes in Season 1)
- *Bleach: Thousand-Year Blood War* (Part 1, Part 2, Part 3)
- *Spy x Family* (Part 1, Part 2)
- *Frieren: Beyond Journey's End* (28 episodes in Season 1)
- *Re:Zero - Starting Life in Another World Season 2* (Part 1, Part 2)

However, across torrent trackers (RuTracker, Nyaa, AniLibria, Anime365, Rutor), release groups traditionally structure these titles into distinct split-cours:
- **Part 1**: `Space Dandy TV-1 [01-13]`
- **Part 2**: `Space Dandy TV-2 [01-13]` or `Space Dandy 2nd Season [01-13]`

Without an offset shifting mechanism, files from the second cour (`01..13`) either fail to be discovered by automated search under the general title or mistakenly overwrite episodes 1–13 of the first cour upon import.

The **Scoped Aliases & Offset** capability in Aliasarr completely eliminates this problem.

---

## Mathematical Matching Formula

$$\text{Episode Number in Library} = \text{Episode Number in Release} + \text{Offset}$$

### Formula to calculate Offset when configuring an alias:

$$\text{Offset} = \text{Starting Episode in Card} - \text{Starting Episode in Release}$$

### Calculation Examples:

| Title & Part | Episodes in Card | Numbering in Release | Card Season | Range (From – To) | Offset (+Shift) | Resulting Match |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Space Dandy (TV-1)** | 1–13 | 01–13 | `1` | `1 – 13` | **0** (or empty) | File `01.mkv` $+ 0 \rightarrow$ **S01E01** |
| **Space Dandy (TV-2)** | 14–26 | 01–13 | `1` | `14 – 26` | **+13** | File `01.mkv` $+ 13 \rightarrow$ **S01E14**<br>File `02.mkv` $+ 13 \rightarrow$ **S01E15**<br>File `13.mkv` $+ 13 \rightarrow$ **S01E26** |
| **Mushoku Tensei (Part 1)** | 1–11 | 01–11 | `1` | `1 – 11` | **0** (or empty) | File `01.mkv` $+ 0 \rightarrow$ **S01E01** |
| **Mushoku Tensei (Part 2)** | 12–23 | 01–12 | `1` | `12 – 23` | **+11** | File `01.mkv` $+ 11 \rightarrow$ **S01E12**<br>File `12.mkv` $+ 11 \rightarrow$ **S01E23** |
| **Bleach: TYBW (Part 2)** | 14–26 | 01–13 | `1` | `14 – 26` | **+13** | File `01.mkv` $+ 13 \rightarrow$ **S01E14** |
| **Spy x Family (Part 2)** | 13–25 | 01–13 | `1` | `13 – 25` | **+12** | File `01.mkv` $+ 12 \rightarrow$ **S01E13** |
| **Standard Season 2** | 1–12 | 01–12 | `2` | `1 – 12` | **0** (or empty) | File `01.mkv` $+ 0 \rightarrow$ **S02E01** |

---

## Step-by-Step Configuration in the Web Interface

### 1. Adding an alias for the first part (1–13)
1. Open the title card in your Aliasarr library.
2. In the alias input field, enter: `Space Dandy` (or `Space Dandy TV-1`).
3. If necessary, open the advanced settings drawer (sliders icon) and specify:
   - **Season:** `1`
   - **Episode From:** `1`
   - **Episode To:** `13`
   - **+Offset:** `0` (or leave empty)
4. Click **«+ Add»**.

### 2. Adding an alias for the second part (14–26)
1. In the alias input field, enter: `Space Dandy TV-2` (or `Space Dandy 2nd Season`).
2. Click the advanced settings icon and specify:
   - **Season:** `1`
   - **Episode From:** `14`
   - **Episode To:** `26`
   - **+Offset:** `13`
3. Click **«+ Add»**.
4. The title card will display a chip with a dedicated badge: `[S1, E14–26, +13]`.

### 3. Editing existing aliases
Click the edit pencil icon on any alias chip. In the modal, you can easily adjust text, language, priority, bound season, episode range, or offset.

---

## Under the Hood: How Aliasarr Processes Scoped Aliases

1. **Selective Tracker Polling (Auto Search)**:
   The scheduler queries indexers exclusively with aliases matching currently `WANTED` episodes. When looking for episodes 14–26, the search engine sends requests with `Space Dandy TV-2`.

2. **Season Overwrite Protection (Matcher & Decision Engine)**:
   Even if a release is titled `TV-2` or `2nd Season`, the configured scope of `season_number = 1` binds the release strictly to Season 1 of the title card, preventing the accidental generation of an unwanted dummy Season 2.

3. **Selective File Downloading**:
   When a torrent pack contains files `01.mkv..13.mkv` but your library only requires episodes `15` and `16`, the torrent file inspection engine instructs the client to download **only files 02.mkv and 03.mkv**.

4. **Atomic Post-processing & Renaming (Hardlinks)**:
   Upon completion of download, the post-processing module applies the `+13` offset, seamlessly importing `Space Dandy TV-2 - 01.mkv` as `Space Dandy - S01E14.mkv` into the `Season 1/` directory.

---

## Frequently Asked Questions (FAQ)

**Q: What offset should I set for Season 1 (episodes 1 to 13)?**
> **A:** Set `0` or leave the offset field empty. On trackers, episodes 01–13 map directly to episodes 1–13 of the card ($1 + 0 = 1$).

**Q: How do I calculate the offset for Part 3 (e.g., episodes 25 to 36)?**
> **A:** Subtract 1 from the starting card episode number: $25 - 1 = \mathbf{24}$. The torrent's `01.mkv` will map to $1 + 24 = 25$.

**Q: What happens if I leave the season and episode fields empty?**
> **A:** The alias will function as a global search alias for the entire title without season restrictions or number shifting.

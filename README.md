
![Studsift Image.](https://joezalewski.co.uk/rec/studsift-top.png)

# StudSift

StudSift is a free, open-source, **local-only** LEGO® part scanner, bag organiser and set tracker. Identify bricks with a webcam, sort loose pieces into numbered bags, and find which parts of a LEGO set you already own. **Your collection is stored in CSV files on your computer**, not on a cloud server.

> **Unofficial project.** Not affiliated with, endorsed by or sponsored by the LEGO Group, Brickognize or Rebrickable. LEGO® is a trademark of the LEGO Group.

## Requirements

- **Windows 10/11**, or macOS/Linux using the command-line instructions below
- Python **3.10 or newer** (no third-party Python packages)
- Chrome or Edge with a working **webcam**
- Internet access for image identification and importing sets
- A free **Rebrickable API key** to track LEGO sets (not needed for loose-part scanning)

## Start in 3 steps

1. Download the latest source ZIP from [GitHub Releases](../../releases), **extract it**, and install [Python](https://www.python.org/downloads/) if you don't already have it. On Windows, enable *Add Python to PATH* during installation.
2. On Windows double-click **`start.bat`**. On macOS/Linux open Terminal in the extracted folder and run `python3 server.py`.
3. Open **http://localhost:8765** in Chrome or Edge and allow camera access when prompted.

The terminal window must stay open while using the app. To stop, close it or press Ctrl+C. The browser and Python server run on **the same computer**; this application is intentionally restricted to `127.0.0.1` and does not offer remote access.

## Features

- **Instant webcam scanning**: keep the camera open; one click captures an image and sends it to Brickognize; review the identification, then confirm to save.
- **Automatic bags**: different compatible pieces can share a bag; existing identical pieces prefer the same bag; create new bags as needed.
- **Adjustable bag capacity** (Settings, defaults to 100 pieces): the limit applies to loose and set bags. No automatic rebalancing.
- **Set collection**: enter a LEGO set ID, import the parts list via Rebrickable, and track exact part ID/colour/quantity (includes minifigure components, excludes spare parts).
- **Active set priority**: when scanning, exact matches needed by the active set go into dedicated set bags; any excess remains loose.
- **Collect from existing bags**: guided photo checklist with quantities and a bag-by-bag confirmation step; pieces are only deducted from loose inventory once the bag is confirmed.
- **Possible Matches**: if a required part ID exists in a different recorded colour, view possible colour mix-ups and manually correct verified pieces; nothing counts toward a set automatically.
- **Completed checklist items** have a pale-green background.
- **CSV exports** are accessible from the app and from the `data` directory.

### How scanning works

1. Put one LEGO piece in front of your webcam.
2. Click **Open webcam & scan**, or **Scan next brick** for subsequent pieces. Capture is immediate; **no timer**.
3. The image is sent to [Brickognize](https://brickognize.com/) for recognition. Confirm or correct part ID, description, colour and quantity; the bag suggestion updates.
4. Click **Confirm & save**. The CSV inventory changes and the destination bag is displayed.

**Recognition is not always correct**, especially colours, worn pieces and closely related moulds. Verify the selection before saving. Images are transmitted to the external Brickognize service when you scan.

### Track a LEGO set

1. Create a Rebrickable API key via [Rebrickable API](https://rebrickable.com/api/), then paste it into the app's **Settings** tab. The key is saved locally in `data/config.json`.
2. Under **Sets**, enter a set number such as `75375-1` and import it.
3. Choose that set as the active target on the Scan page to reserve newly scanned exact matches.
4. Alternatively, open **Sets → Pick from loose bags**, select piece images, adjust quantities using +/−, then confirm each bag. These operations move inventory from loose bags to set bags without double-counting.
5. Check **Possible matches** for *suggestions*, particularly grey/gray shades. Correct a colour only after inspecting the real part.

Set bags and loose bags share a global sequence of bag IDs. **Each bag holds no more than your configured total piece capacity.** The app will refuse to lower the limit below the current contents of an existing bag.

## Your data and upgrades

The first run creates `data/` containing:

| File | Purpose |
|---|---|
| `inventory.csv` | Loose stock: part ID, colour, bag number, quantity |
| `bags.csv` | Bag numbers and categories |
| `sets.csv` | Tracked set IDs and names |
| `set_requirements.csv` | Per-set part requirements and image URLs |
| `set_pieces.csv` | Pieces already allocated to sets |
| `set_pick_staging.csv` | Picks awaiting bag confirmation |
| `set_bag_progress.csv` | Bags already processed while collecting a set |
| `colours.csv` | Colour catalogue |
| `config.json` | User settings, **including your private API key** |

**Do not publish or commit `data/`.** It contains your collection and API key and is ignored by Git. The software does not bundle anyone's existing CSV data.

**To upgrade an existing installation without losing data:**

1. Stop the running app.
2. **Back up your entire current `data/` folder** somewhere outside the app directory.
3. Extract the new release into a **new folder** and copy your existing `data/` folder into it.
4. Start the new release. The application retains existing CSV formats and creates missing CSVs automatically; it does **not** overwrite your existing inventory.

Avoid editing CSV files in Excel while the app is running. An interrupted multi-file transfer is replayed on startup from the local transaction journal; do not delete `.pending-transaction.json` if you see it.

## Development

```sh
python -m unittest -v test_server.py
```

No `pip install` step is necessary. CI runs unit tests and JavaScript syntax checks. The `data/` folder is omitted from source control. The backend is in `server.py`; the frontend is static HTML, CSS and JS under `web/`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contributions, [SECURITY.md](SECURITY.md) for security boundaries, and [CHANGELOG.md](CHANGELOG.md) for release details.

## Known limitations

- Built for a **single local user**; it does not authenticate clients or support running across your home network.
- Brickognize is currently used via a **legacy API endpoint**, subject to change; live API behaviour may differ from mocked tests.
- Colour recognition and catalog part-number mapping are imperfect; use manual review and Possible Matches.
- Internet access is required for Brickognize scans and Rebrickable set imports; Rebrickable limits request rates.
- Windows users must have Python installed; **no standalone Windows `.exe`** is provided in this release.
- Only the automated tests and local HTTP/simulated logic are validated; live webcam and Rebrickable/Brickognize APIs should be tested by users.

## Licence

[MIT](LICENSE). This licence covers the source code in this repository, not the LEGO, Rebrickable or Brickognize names, data, imagery or APIs.

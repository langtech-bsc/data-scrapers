import os
import argparse
import pandas as pd
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from urllib.request import urlopen
from bs4 import BeautifulSoup


# ── Configuration ─────────────────────────────────────────────────────────────

MANIFEST  = "data_to_download.tsv"
ERROR_TSV = "error_in_transcription.tsv"
AUDIO_INGESTION_PATH = "audios"

MANIFEST_COLS = ["id", "mp4_hq", "mp4_mq", "ebuttd_ca", "durada_segons",
                 "text", "hq_id", "mq_id"]

DIRS = {
    "hq":    "hq_videos",
    "mq":    "mq_videos",
    "audio": "audios",
    "tsv":   "fsp_tsv",
}

# State files — one line per completed filename, written atomically after each success
STATE = {
    "hq_done":      "state_hq_downloads.txt",
    "mq_done":      "state_mq_downloads.txt",
    "audio_done":   "state_audio_conversions.txt",
    "tsv_done":     "state_tsv_written.txt",
}

TRANSCRIPTION_WORKERS = 10 # HTTP requests. I/O-bound, can be higher (50-100), but watch out for rate limits or instability.
DOWNLOAD_WORKERS      = 10 # large file transfers.
AUDIO_WORKERS         = 10 # CPU-bound ffmpeg processes.

# ── State helpers ──────────────────────────────────────────────────────────────

# One lock per state file so parallel workers can append safely.
_state_locks: dict[str, threading.Lock] = {key: threading.Lock() for key in STATE}


def load_state(key: str) -> set[str]:
    """
    Load a state file into a set of filenames.
    Returns an empty set if the file does not exist yet.
    """
    path = STATE[key]
    if not os.path.exists(path):
        return set()
    with open(path) as fh:
        return {line.strip() for line in fh if line.strip()}


def mark_done(key: str, filename: str) -> None:
    """
    Append a single filename to the state file.
    """
    path = STATE[key]
    with _state_locks[key]:
        with open(path, "a") as fh:
            fh.write(filename + "\n")
            fh.flush()
            os.fsync(fh.fileno())


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_video_name(url: str) -> str:
    """Return the filename portion of a video URL."""
    print(url)
    return url.split("/")[-1]


def fetch_transcription(url: str) -> str:
    """
    Download and parse an XML subtitle file.
    Returns the joined text, or an error marker on failure.
    """
    try:
        soup = BeautifulSoup(urlopen(url).read(), "html.parser")
        return " ".join(item.text for item in soup.find_all("tt:span"))
    except Exception:
        print(f"  [warn] transcription error: {url}")
        return f"@# error in transcription: {url}"


def wget_url(url: str, dest_dir: str, state_key: str) -> tuple[bool, str]:
    """
    Download a single URL into dest_dir using wget.
    Skips files already recorded in the state file (fast) or present on disk (safe).
    Marks success in the state file immediately after completion.
    Returns (success, url).
    """
    from datetime import datetime

    filename  = extract_video_name(url)
    dest      = os.path.join(dest_dir, filename)
    thread_id = threading.current_thread().name
    ts        = lambda: datetime.now().strftime("%H:%M:%S.%f")[:-3]

    # Primary check: state file (O(1) set lookup, no filesystem hit)
    if filename in _runtime_state[state_key]:
        print(f"  [{ts()}] [{thread_id}] [skip]  {filename} (state)")
        return True, url

    # Fallback check: file actually on disk (handles edge cases / manual copies)
    if os.path.exists(dest):
        print(f"  [{ts()}] [{thread_id}] [skip]  {filename} (disk)")
        mark_done(state_key, filename)
        _runtime_state[state_key].add(filename)
        return True, url

    print(f"  [{ts()}] [{thread_id}] [start] {filename}")
    result = subprocess.run(["wget", "-q", "-P", dest_dir, url])
    if result.returncode != 0:
        print(f"  [{ts()}] [{thread_id}] [error] {url}")
        return False, url

    mark_done(state_key, filename)
    _runtime_state[state_key].add(filename)
    print(f"  [{ts()}] [{thread_id}] [done]  {filename}")
    return True, url


def convert_to_audio(args: tuple[str, str]) -> None:
    """
    Convert a single video file to MP3 audio via ffmpeg.
    Skips if already recorded in the state file or the audio file exists on disk.
    Marks success in the state file immediately after completion.
    Accepts a (video_path, audio_path) tuple for use with ProcessPoolExecutor.
    """
    video_path, audio_path = args
    audio_name = os.path.basename(audio_path)

    # Check state file directly (separate process — no shared memory)
    already_done = load_state("audio_done")
    if audio_name in already_done or os.path.exists(audio_path):
        print(f"  [skip] audio already done: {audio_name}")
        if audio_name not in already_done:
            mark_done("audio_done", audio_name)
        return

    print(f"  [ffmpeg] {os.path.basename(video_path)} → {audio_name}")
    subprocess.run(
        ["ffmpeg", "-i", video_path, audio_path, "-loglevel", "error"],
        check=True,
    )
    mark_done("audio_done", audio_name)


# ── Runtime state (in-memory cache of state files, loaded once at startup) ────

_runtime_state: dict[str, set[str]] = {}


def init_runtime_state() -> None:
    """
    Load all state files into memory at startup.
    Workers update both _runtime_state and the on-disk file on each success.
    """
    for key in STATE:
        _runtime_state[key] = load_state(key)
    print(f"  Resumed state: "
          f"{len(_runtime_state['hq_done'])} HQ downloads, "
          f"{len(_runtime_state['mq_done'])} MQ downloads, "
          f"{len(_runtime_state['audio_done'])} conversions, "
          f"{len(_runtime_state['tsv_done'])} TSVs.")


# ── Pipeline steps ─────────────────────────────────────────────────────────────

def load_and_filter_data(datafile: str) -> pd.DataFrame:
    """Load the JSON catalogue and return the cleaned, filtered DataFrame."""
    print("Loading data…")
    with open(datafile) as fh:
        jsondata = json.load(fh)

    df = pd.DataFrame(jsondata["docs"]).fillna("nan")

    mask = (df["idioma"] == "Català") & (df["ebuttd_ca"] != "nan")
    if "mp4_1200_es" in df.columns:
        mask &= (df["mp4_1200_es"] == "nan")
    else:
        print("  [warn] column 'mp4_1200_es' not found in data, skipping that filter.")
    filtered = df[mask].drop_duplicates(subset=["mp4_hq"])

    return filtered[["id", "mp4_hq", "mp4_mq", "ebuttd_ca", "durada_segons"]]


def build_manifest(data: pd.DataFrame) -> pd.DataFrame:
    """
    Fetch all transcriptions in parallel and persist the result to MANIFEST.

    On a fresh run  → fetches all transcriptions concurrently, writes MANIFEST.
    On a resume run → MANIFEST already exists, reloaded, and returned immediately.

    Rows with transcription errors are saved to ERROR_TSV and excluded.
    """
    if os.path.exists(MANIFEST):
        print(f"Manifest '{MANIFEST}' found — skipping transcription fetch.")
        return pd.read_csv(MANIFEST, sep="\t", names=MANIFEST_COLS, keep_default_na=False)


    print(f"Fetching {len(data)} transcriptions with {TRANSCRIPTION_WORKERS} workers…")
    data = data.copy()
    urls = data["ebuttd_ca"].tolist()
    results = {}

    with ThreadPoolExecutor(max_workers=TRANSCRIPTION_WORKERS) as executor:
        future_to_url = {executor.submit(fetch_transcription, url): url for url in urls}
        for i, future in enumerate(as_completed(future_to_url), 1):
            url = future_to_url[future]
            results[url] = future.result()
            if i % 500 == 0:
                print(f"  {i}/{len(urls)} transcriptions fetched…")

    data["text"] = data["ebuttd_ca"].map(results)

    errors = data[data["text"].str.startswith("@# error in transcription:")]
    if not errors.empty:
        errors.to_csv(ERROR_TSV, sep="\t")
        print(f"  [warn] {len(errors)} error(s) saved to {ERROR_TSV}")

    clean = data[~data["text"].str.startswith("@# error in transcription:")].copy()
    clean["hq_id"] = clean["mp4_hq"].apply(extract_video_name)
    clean["mq_id"] = clean["mp4_mq"].apply(extract_video_name)

    clean.to_csv(MANIFEST, sep="\t", index=False, header=False)
    print(f"  Manifest saved to '{MANIFEST}' ({len(clean)} entries).")
    return clean


def prepare_directories() -> None:
    """Create all required output directories."""
    for path in DIRS.values():
        os.makedirs(path, exist_ok=True)


def download_videos(data: pd.DataFrame) -> tuple[list[str], list[str]]:
    """
    Download HQ videos in parallel, falling back to MQ for any that fail or are missing.
    Uses state files to skip already-completed downloads — no directory scan needed.
    Returns (hq_files, mq_files) as lists of base filenames present in state.
    """
    print(f"Downloading {len(data)} HQ videos with {DOWNLOAD_WORKERS} workers…")

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
        futures = {
            executor.submit(wget_url, row["mp4_hq"], DIRS["hq"], "hq_done"): row
            for _, row in data.iterrows()
        }
        for i, future in enumerate(as_completed(futures), 1):
            future.result()  # surface any unexpected exceptions
            if i % 100 == 0:
                print(f"  {i}/{len(data)} HQ downloads done…")

    # Any HQ file absent from state → try MQ fallback
    missing = data[~data["hq_id"].isin(_runtime_state["hq_done"])]

    if not missing.empty:
        print(f"  {len(missing)} HQ file(s) missing — downloading MQ fallback with {DOWNLOAD_WORKERS} workers…")
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
            futures = {
                executor.submit(wget_url, row["mp4_mq"], DIRS["mq"], "mq_done"): row
                for _, row in missing.iterrows()
            }
            for future in as_completed(futures):
                future.result()

    return list(_runtime_state["hq_done"]), list(_runtime_state["mq_done"])


def convert_all_to_audio(hq_files: list[str], mq_files: list[str]) -> None:
    """Convert every downloaded video to MP3 in parallel using multiple CPU cores."""
    print(f"Converting videos to audio with {AUDIO_WORKERS} workers…")

    jobs = []
    for filename in hq_files:
        stem = os.path.splitext(filename)[0]
        audio_name = f"{stem}.mp3"
        # Pre-filter using in-memory state to avoid spawning processes for done work
        if audio_name not in _runtime_state["audio_done"]:
            jobs.append((
                os.path.join(DIRS["hq"], filename),
                os.path.join(DIRS["audio"], audio_name),
            ))
    for filename in mq_files:
        stem = os.path.splitext(filename)[0]
        audio_name = f"{stem}.mp3"
        if audio_name not in _runtime_state["audio_done"]:
            jobs.append((
                os.path.join(DIRS["mq"], filename),
                os.path.join(DIRS["audio"], audio_name),
            ))

    print(f"  {len(jobs)} conversion(s) pending (already done: "
          f"{len(_runtime_state['audio_done'])})…")

    with ProcessPoolExecutor(max_workers=AUDIO_WORKERS) as executor:
        for i, _ in enumerate(executor.map(convert_to_audio, jobs), 1):
            if i % 100 == 0:
                print(f"  {i}/{len(jobs)} conversions done…")


def create_tsv_files(data: pd.DataFrame) -> None:
    """
    Write one TSV per successfully downloaded video into fsp_tsv/.
    Uses the state file to skip already-written TSVs — no directory scan needed.

    Each file contains two columns:
      - audioname: path where the .wav is expected
      - text:      the fetched transcription

    HQ takes priority. Already-written TSVs are skipped (resumable).
    """
    print("Creating TSVs…")

    written = 0
    skipped = 0

    for _, row in data.iterrows():
        if row["hq_id"] in _runtime_state["hq_done"]:
            video_id = row["hq_id"]
        elif row["mq_id"] in _runtime_state["mq_done"]:
            video_id = row["mq_id"]
        else:
            continue

        stem     = video_id[:-4]
        tsv_name = f"{stem}.tsv"

        if tsv_name in _runtime_state["tsv_done"]:
            skipped += 1
            continue

        tsv_path  = os.path.join(DIRS["tsv"], tsv_name)
        audioname = os.path.join(AUDIO_INGESTION_PATH, stem + ".wav")
        pd.DataFrame([{"audioname": audioname, "text": row["text"]}]).to_csv(
            tsv_path, sep="\t", index=False
        )
        mark_done("tsv_done", tsv_name)
        _runtime_state["tsv_done"].add(tsv_name)
        written += 1

    print(f"  TSVs written: {written}, skipped (already exist): {skipped}")


# ── Entry point ────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download 3Cat videos and transcriptions.")
    parser.add_argument(
        "--input", required=True, metavar="FILE",
        help="Path to the input JSON file (e.g. aina_filtered.json)",
    )
    parser.add_argument(
        "--transcription-workers", type=int, default=TRANSCRIPTION_WORKERS,
        help=f"Parallel workers for transcription fetch (default: {TRANSCRIPTION_WORKERS})",
    )
    parser.add_argument(
        "--download-workers", type=int, default=DOWNLOAD_WORKERS,
        help=f"Parallel workers for video downloads (default: {DOWNLOAD_WORKERS})",
    )
    parser.add_argument(
        "--audio-workers", type=int, default=AUDIO_WORKERS,
        help=f"Parallel workers for ffmpeg conversion (default: {AUDIO_WORKERS})",
    )
    args = parser.parse_args()
    if not os.path.exists(args.input):
        parser.error(f"Input file not found: {args.input}")
    return args


def main() -> None:
    args = parse_args()

    # Allow CLI overrides of worker counts
    global TRANSCRIPTION_WORKERS, DOWNLOAD_WORKERS, AUDIO_WORKERS
    TRANSCRIPTION_WORKERS = args.transcription_workers
    DOWNLOAD_WORKERS      = args.download_workers
    AUDIO_WORKERS         = args.audio_workers

    prepare_directories()
    init_runtime_state()       # load state files into memory before any work starts

    data     = load_and_filter_data(args.input)
    manifest = build_manifest(data)

    hq_files, mq_files = download_videos(manifest)
    convert_all_to_audio(hq_files, mq_files)

    create_tsv_files(manifest)
    print("Done!")


if __name__ == "__main__":
    main()

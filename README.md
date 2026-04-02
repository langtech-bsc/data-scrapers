# Data Scrapers

A collection of Python scripts for scraping structured data from different platforms.

Currently included:

- **YouTube Scraper** – downloads YouTube videos and captions, else falls back to whisper transcriptions. 
- **CCMA Scraper** – extracts media-related data from the CCMA.

Each scraper is implemented as an independent script with its own dependencies.

---

# Project Structure
Each scraper folder contains:

- The main Python script.
- A `requirements.txt` file listing the required dependencies.

---

# Installation

Clone the repository:

```bash
git clone https://github.com/langtech-bsc/data-scrapers.git
cd data-scrapers
```

## Install dependencies for a specific scraper

1. Example for the YouTube scraper:

```bash
cd youtube_scraper
pip install -r requirements.txt
```

2. Example for the CCMA scraper:

```bash
cd ccma_scraper
pip install -r requirements.txt
```
---
# Run scrapers
## YouTube scraper
```
python youtube_scraper.py  <youtube_id>
```
Both the downloaded audio converted to WAV format and the TSV file containing captions/transcriptions will be stored under the **ingestion** folder.

---

## CCMA scraper (WIP)
```
python ccma_scraper.py <json_file> <num_of_videos>
```

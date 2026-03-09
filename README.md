# Data Scrapers

A collection of Python scripts for scraping structured data from different platforms.

Currently included:

- **CCMA Scraper** – extracts media-related data from the CCMA.
- **YouTube Scraper** – collects metadata from YouTube videos or channels.

Each scraper is implemented as an independent script with its own dependencies.

---

# Project Structure
Each scraper folder contains:

- the main Python script
- a `requirements.txt` file listing the required dependencies

---

# Installation

Clone the repository:

```bash
git clone https://github.com/langtech-bsc/data-scrapers.git
cd data-scrapers
```

## Install dependencies for a specific scraper.

1. Example for the CCMA scraper:

```bash
cd ccma_scraper
pip install -r requirements.txt
```

2. Example for the YouTube scraper:

```bash
cd youtube_scraper
pip install -r requirements.txt
```

---
# Run scrapers
## CCMA scraper
---
## YouTube scraper
```
python youtube_scraper.py --youtube_url <YOUTUBE_URL>
```

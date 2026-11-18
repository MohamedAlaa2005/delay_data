import csv
import sys
import time
from bs4 import BeautifulSoup
from camoufox.sync_api import Camoufox

TARGETS = [
    {
        "type": "departures",
        "url": "https://planefinder.net/data/airport/AHB/departures",
        "output_csv": "departures.csv"
    },
    {
        "type": "arrivals",
        "url": "https://planefinder.net/data/airport/AHB/arrivals",
        "output_csv": "arrivals.csv"
    }
]

def clean_cell_text(td):
    if not td:
        return ""
    # Join internal text nicely preserving spaces between spans/tags
    return " ".join(td.get_text(separator=" ", strip=True).split())

def scrape_airport_earlier_flights(page, target):
    flight_type = target["type"]
    url = target["url"]
    csv_file = target["output_csv"]

    print(f"\n==========================================")
    print(f"Scraping ALL earlier {flight_type.upper()} from: {url}")
    print(f"==========================================")

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            if attempt < max_attempts:
                print(f"[!] Navigation error for {url} ({e}). Retrying once more...")
                page.wait_for_timeout(3000)
                continue
            print(f"[!] Navigation error: {e}")
            return

        title = page.title()
        if "Just a moment..." in title or "Attention Required" in title:
            page.wait_for_timeout(4000)
            title = page.title()

        if "Just a moment..." in title or "Attention Required" in title:
            if attempt < max_attempts:
                print(f"[!] Cloudflare challenge detected on {url}. Retrying once more (attempt {attempt + 1}/{max_attempts})...")
                page.wait_for_timeout(5000)
                continue
            else:
                print(f"[!] Cloudflare challenge persisted on {url} after retry.")
                return
        break
    page.wait_for_selector("table", timeout=15000)
    page.wait_for_selector("button.earlier-flights", timeout=15000)

    # Capture initial table headers
    raw_headers = page.eval_on_selector_all("table th", "elements => elements.map(e => e.innerText.trim())")
    headers = ["Date"] + raw_headers
    print(f"Headers: {headers}")

    # Capture initial flight row IDs (present before clicking earlier flights)
    initial_tr_ids = set(page.eval_on_selector_all("table tbody tr", "elements => elements.map(e => e.id).filter(id => id)"))
    print(f"Initial flight rows on board before loading earlier: {len(initial_tr_ids)}")

    btn = page.query_selector("button.earlier-flights")
    if not btn:
        print("[!] Earlier flights button not found.")
        return

    print("\nStarting continuous clicks on 'Show earlier flights'...")
    no_change_count = 0
    max_no_change = 5  # Stop when 5 consecutive clicks yield no new rows
    last_row_count = 0
    click_count = 0

    while True:
        if not btn.is_visible() or btn.is_disabled():
            print(f"Button became disabled/invisible after {click_count} clicks.")
            break

        click_count += 1
        btn.click()
        page.wait_for_timeout(1500)

        # Get current count of rows in tbody
        current_row_count = len(page.query_selector_all("table tbody tr"))
        print(f"Click #{click_count}: current total rows = {current_row_count}")

        if current_row_count > last_row_count:
            last_row_count = current_row_count
            no_change_count = 0
        else:
            no_change_count += 1
            if no_change_count >= max_no_change:
                print(f"No new flights appeared after {max_no_change} consecutive clicks. Reached end of earlier flights.")
                break

    # Parse full table from DOM
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    tbody = table.find("tbody") if table else None

    if not tbody:
        print(f"[!] Could not locate tbody in table for {flight_type}")
        return

    earlier_records = []
    current_date = ""

    for tr in tbody.find_all("tr"):
        # Check if date separator header
        td_separator = tr.find("td", colspan=True)
        if td_separator:
            current_date = td_separator.get_text(strip=True)
            continue

        row_id = tr.get("id", "")
        # Only include EARLIER flights (exclude the initial rows loaded at offset 0)
        if row_id and row_id in initial_tr_ids:
            continue

        date_attr = tr.get("data-date", "").strip()
        row_date = date_attr if date_attr else current_date

        tds = tr.find_all("td")
        if not tds:
            continue

        row_values = [row_date] + [clean_cell_text(td) for td in tds]
        earlier_records.append(row_values)

    print(f"\n[✓] Total earlier {flight_type} flights extracted: {len(earlier_records)}")

    # Write to CSV file
    with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in earlier_records:
            if len(row) < len(headers):
                row = row + [""] * (len(headers) - len(row))
            writer.writerow(row[:len(headers)])

    print(f"[✓] Saved to '{csv_file}' successfully!")

def main():
    print("Launching Camoufox (Stealth Firefox)...")
    with Camoufox(headless=False, humanize=True, canvas_noise=True, i_know_what_im_doing=True) as browser:
        page = browser.new_page()

        for target in TARGETS:
            scrape_airport_earlier_flights(page, target)

    print("\nAll earlier flights scraping completed successfully!")

if __name__ == "__main__":
    main()

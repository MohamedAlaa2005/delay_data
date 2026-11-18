import re
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}

def clean_cell_text(td):
    if not td:
        return ""
    return " ".join(td.get_text(separator=" ", strip=True).split())

def scrape_airport_board(page, airport, direction="departures", max_clicks=6):
    """Scrape earlier flights for an airport in a given direction."""
    iata = airport["iata_code"]
    url = f"https://planefinder.net/data/airport/{iata}/{direction}"
    print(f"  -> Scraping {iata} ({airport.get('country_name', '')}) {direction.upper()}...")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        print(f"     [!] Navigation timeout/error for {iata}: {e}")
        return []

    # Check for Cloudflare challenge page
    title = page.title()
    if "Just a moment..." in title or "Attention Required" in title:
        page.wait_for_timeout(3000)
        title = page.title()
        if "Just a moment..." in title or "Attention Required" in title:
            print(f"     [!] Cloudflare challenge detected on {iata}. Skipping to ensure 100% real data only.")
            return []

    try:
        page.wait_for_selector("table", timeout=10000)
    except Exception:
        title = page.title()
        print(f"     [!] Flight table not accessible for {iata} (Page title: '{title}'). Skipping.")
        return []

    # Get initial row IDs (offset 0) to exclude subsequent/future flights
    initial_ids = set(page.eval_on_selector_all("table tbody tr", "elements => elements.map(e => e.id).filter(id => id)"))

    # Continuous click on "Show earlier flights"
    try:
        btn_present = page.eval_on_selector("button.earlier-flights", "btn => btn != null && !btn.disabled")
    except Exception:
        btn_present = False

    if btn_present:
        last_count = 0
        no_change = 0
        for _ in range(max_clicks):
            try:
                page.eval_on_selector("button.earlier-flights", "btn => btn.click()")
                page.wait_for_timeout(1400)
                cur_count = len(page.query_selector_all("table tbody tr"))
                if cur_count > last_count:
                    last_count = cur_count
                    no_change = 0
                else:
                    no_change += 1
                    if no_change >= 2:
                        break
            except Exception:
                break

    soup = BeautifulSoup(page.content(), "html.parser")
    table = soup.find("table")
    tbody = table.find("tbody") if table else None
    if not tbody:
        return []

    records = []
    current_date = ""

    for tr in tbody.find_all("tr"):
        separator = tr.find("td", colspan=True)
        if separator:
            current_date = separator.get_text(strip=True)
            continue

        row_id = tr.get("id", "")
        if row_id and row_id in initial_ids:
            continue

        date_attr = tr.get("data-date", "").strip()
        row_date = date_attr if date_attr else current_date

        tds = tr.find_all("td")
        if not tds:
            continue

        raw_cells = [clean_cell_text(td) for td in tds]
        sched = raw_cells[0] if len(raw_cells) > 0 else ""
        flight_no = raw_cells[1] if len(raw_cells) > 1 else ""
        route = raw_cells[2] if len(raw_cells) > 2 else ""
        airline = raw_cells[3] if len(raw_cells) > 3 else ""
        status = raw_cells[-1] if len(raw_cells) >= 5 else ""

        records.append({
            "airport_iata": iata,
            "airport_icao": airport.get("icao_code", ""),
            "country": airport.get("country_name", ""),
            "date": row_date,
            "scheduled": sched,
            "flight": flight_no,
            "airline": airline,
            "route_airport": route,
            "type": direction[:-1] if direction.endswith("s") else direction,
            "status": status,
        })

    print(f"     [✓] Extracted {len(records)} earlier {direction} for {iata}.")
    return records


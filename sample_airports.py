import csv
import io
import urllib.request
from collections import defaultdict

OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

# Preferred flagship/primary hubs for major countries
PREFERRED_HUBS = {
    "SA": ["RUH", "JED", "AHB", "DMM"],
    "AE": ["DXB", "AUH", "SHJ"],
    "QA": ["DOH"],
    "KW": ["KWI"],
    "BH": ["BAH"],
    "OM": ["MCT", "SLL"],
    "EG": ["CAI", "HBE", "SSH", "HRG"],
    "JO": ["AMM", "AQJ"],
    "TR": ["IST", "SAW", "AYT"],
    "US": ["ATL", "JFK", "LAX", "ORD"],
    "GB": ["LHR", "LGW", "MAN"],
    "FR": ["CDG", "ORY", "NCE"],
    "DE": ["FRA", "MUC", "BER"],
    "ES": ["MAD", "BCN", "AGP"],
    "IT": ["FCO", "MXP", "NAP"],
    "NL": ["AMS", "EIN"],
    "CH": ["ZRH", "GVA"],
    "AT": ["VIE", "SZG"],
    "BE": ["BRU", "CRL"],
    "PT": ["LIS", "OPO", "FNC"],
    "GR": ["ATH", "SKG", "HER"],
    "IE": ["DUB", "SNN", "ORK"],
    "SE": ["ARN", "GOT"],
    "NO": ["OSL", "BGO", "TRD"],
    "DK": ["CPH", "BLL"],
    "FI": ["HEL"],
    "PL": ["WAW", "KRK", "GDN"],
    "CZ": ["PRG"],
    "HU": ["BUD"],
    "RO": ["OTP", "CLJ"],
    "JP": ["HND", "NRT", "KIX"],
    "CN": ["PEK", "PVG", "CAN"],
    "KR": ["ICN", "GMP", "PUS"],
    "IN": ["DEL", "BOM", "BLR"],
    "PK": ["KHI", "ISB", "LHE"],
    "BD": ["DAC", "CGP"],
    "SG": ["SIN"],
    "MY": ["KUL", "PEN"],
    "TH": ["BKK", "HKT", "CNX"],
    "VN": ["SGN", "HAN", "DAD"],
    "ID": ["CGK", "DPS", "SUB"],
    "PH": ["MNL", "CEB"],
    "AU": ["SYD", "MEL", "BNE"],
    "NZ": ["AKL", "CHC"],
    "CA": ["YYZ", "YVR", "YUL"],
    "MX": ["MEX", "CUN", "GDL"],
    "BR": ["GRU", "GIG", "BSB"],
    "AR": ["EZE", "AEP"],
    "CL": ["SCL"],
    "CO": ["BOG", "MDE"],
    "PE": ["LIM", "CUZ"],
    "ZA": ["JNB", "CPT", "DUR"],
    "MA": ["CMN", "RAK"],
    "TN": ["TUN"],
    "DZ": ["ALG", "ORN"],
    "ET": ["ADD"],
    "KE": ["NBO", "MBA"],
    "NG": ["LOS", "ABV"],
    "GH": ["ACC"],
    "SN": ["DSS"],
}

COUNTRY_NAMES = {
    "SA": "Saudi Arabia", "AE": "United Arab Emirates", "QA": "Qatar", "KW": "Kuwait",
    "BH": "Bahrain", "OM": "Oman", "EG": "Egypt", "JO": "Jordan", "TR": "Turkey",
    "US": "United States", "GB": "United Kingdom", "FR": "France", "DE": "Germany",
    "ES": "Spain", "IT": "Italy", "NL": "Netherlands", "CH": "Switzerland", "AT": "Austria",
    "BE": "Belgium", "PT": "Portugal", "GR": "Greece", "IE": "Ireland", "SE": "Sweden",
    "NO": "Norway", "DK": "Denmark", "FI": "Finland", "PL": "Poland", "CZ": "Czech Republic",
    "HU": "Hungary", "RO": "Romania", "JP": "Japan", "CN": "China", "KR": "South Korea",
    "IN": "India", "PK": "Pakistan", "BD": "Bangladesh", "SG": "Singapore", "MY": "Malaysia",
    "TH": "Thailand", "VN": "Vietnam", "ID": "Indonesia", "PH": "Philippines", "AU": "Australia",
    "NZ": "New Zealand", "CA": "Canada", "MX": "Mexico", "BR": "Brazil", "AR": "Argentina",
    "CL": "Chile", "CO": "Colombia", "PE": "Peru", "ZA": "South Africa", "MA": "Morocco",
    "TN": "Tunisia", "DZ": "Algeria", "ET": "Ethiopia", "KE": "Kenya", "NG": "Nigeria",
    "GH": "Ghana", "SN": "Senegal"
}

def generate_airport_sample(target_total=100, max_per_country=2):
    print("Downloading global airport records from OurAirports...")
    req = urllib.request.Request(OURAIRPORTS_URL, headers={"User-Agent": "AviationSampling/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        content = resp.read().decode("utf-8", errors="ignore")

    reader = csv.DictReader(io.StringIO(content))
    iata_map = {}

    for row in reader:
        iata = row.get("iata_code", "").strip().upper()
        if len(iata) == 3 and iata.isalpha():
            iata_map[iata] = row

    selected = []
    country_counts = defaultdict(int)

    # 1. First priority: pick 1st preferred hub for each defined country
    for country, hubs in PREFERRED_HUBS.items():
        if len(selected) >= target_total:
            break
        for h in hubs:
            if h in iata_map and country_counts[country] < 1:
                selected.append(iata_map[h])
                country_counts[country] += 1
                break

    # 2. Second priority: pick 2nd preferred hub for countries (max 2 per country)
    for country, hubs in PREFERRED_HUBS.items():
        if len(selected) >= target_total:
            break
        for h in hubs:
            if h in iata_map and iata_map[h] not in selected and country_counts[country] < max_per_country:
                selected.append(iata_map[h])
                country_counts[country] += 1
                break

    print(f"Sampled {len(selected)} airports across {len(country_counts)} countries.")
    print(f"Verification: Max airports in any country = {max(country_counts.values())} (Limit: {max_per_country})")

    output_rows = []
    for apt in selected:
        iata = apt.get("iata_code", "").strip().upper()
        icao = apt.get("icao_code", "").strip().upper() or apt.get("ident", "").strip().upper()
        ccode = apt.get("iso_country", "").strip().upper()
        cname = COUNTRY_NAMES.get(ccode, ccode)

        output_rows.append({
            "iata_code": iata,
            "icao_code": icao,
            "airport_name": apt.get("name", "").strip(),
            "city": apt.get("municipality", "").strip(),
            "country_code": ccode,
            "country_name": cname,
            "continent": apt.get("continent", "").strip(),
            "latitude_deg": apt.get("latitude_deg", "").strip(),
            "longitude_deg": apt.get("longitude_deg", "").strip(),
            "elevation_ft": apt.get("elevation_ft", "").strip(),
            "airport_type": apt.get("type", "").strip(),
            "planefinder_departures_url": f"https://planefinder.net/data/airport/{iata}/departures",
            "planefinder_arrivals_url": f"https://planefinder.net/data/airport/{iata}/arrivals",
        })

    # Sort alphabetically by country, then airport name
    output_rows.sort(key=lambda x: (x["country_name"], x["airport_name"]))

    output_file = "airports_sample_100.csv"
    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(output_rows[0].keys()))
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"[✓] Successfully wrote {len(output_rows)} airports to '{output_file}'!")

if __name__ == "__main__":
    generate_airport_sample(target_total=100, max_per_country=2)

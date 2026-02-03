#!/usr/bin/env python3
"""
Script to extract hospital data from AHA Hospital Guide PDF.

Extracts: name, address, county, zip code, state, contacts, web address,
control, services, and number of staffed beds for each hospital.
"""

import re
import json
import csv
import fitz  # PyMuPDF
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Hospital:
    name: str = ""
    medicare_provider_number: str = ""
    address: str = ""
    city: str = ""
    county: str = ""
    state: str = ""
    zip_code: str = ""
    telephone: str = ""
    primary_contact: str = ""
    coo: str = ""  # Chief Operating Officer
    cfo: str = ""  # Chief Financial Officer
    cmo: str = ""  # Chief Medical Officer
    cio: str = ""  # Chief Information Officer
    chr: str = ""  # Chief Human Resources
    cno: str = ""  # Chief Nursing Officer
    web_address: str = ""
    control: str = ""
    services: str = ""
    staffed_beds: str = ""
    personnel: str = ""


def normalize_text(text: str) -> str:
    """Normalize Unicode characters for easier parsing."""
    # Replace em-dashes (U+2013) and en-dashes (U+2014) with regular hyphens
    text = text.replace('\u2013', '-').replace('\u2014', '-')
    # Replace curly apostrophes (U+2018, U+2019) with straight ones
    text = text.replace('\u2019', "'").replace('\u2018', "'")
    # Replace curly double quotes (U+201C, U+201D) with straight ones
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    # Replace non-breaking spaces (U+00A0) with regular spaces
    text = text.replace('\u00a0', ' ')
    return text


def extract_text_from_pdf(pdf_path: str) -> tuple[str, list[dict]]:
    """Extract text from PDF with font info for hospital detection.

    Returns:
        tuple: (full_text, hospital_entries) where hospital_entries is a list of
               dicts with 'name', 'provider_number', 'line_text', 'x', 'y' keys
    """
    full_text = ""
    hospital_entries = []
    doc = fitz.open(pdf_path)

    # Skip patterns - headers and footers
    skip_patterns = [
        'Hospital, Medicare Provider Number',
        'Hospitals in the United States',
        'by State',
        '© 20',
        'Hospitals   A',
    ]

    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        page_width = page.rect.width
        col_split = page_width / 2

        # Collect text items with position and detect hospital entries by font
        left_items = []
        right_items = []

        for block in blocks:
            if block["type"] == 0:  # Text block
                for line in block["lines"]:
                    spans = line["spans"]
                    bbox = line["bbox"]
                    x, y = bbox[0], bbox[1]

                    line_text = "".join(span["text"] for span in spans)

                    # Skip header/footer lines
                    if any(skip in line_text for skip in skip_patterns):
                        if line_text.strip():
                            if x < col_split:
                                left_items.append((x, y, line_text))
                            else:
                                right_items.append((x, y, line_text))
                        continue

                    # Detect hospital entries by font pattern:
                    # Look for bold hospital name + bold provider number
                    if len(spans) >= 2:
                        # Find bold spans that could be hospital name
                        bold_name = ""
                        provider_num = ""
                        rest_text = ""
                        found_bold_name = False

                        for i, span in enumerate(spans):
                            span_bold = bool(span["flags"] & 16) or "Bold" in span.get("font", "")
                            text = span["text"]

                            # Skip accreditation symbol spans (single char, non-bold, special fonts)
                            if len(text.strip()) <= 2 and not span_bold:
                                continue

                            # Check if this is a provider number in parentheses
                            if span_bold and re.match(r'^\s*\(\d{6}\)\s*$', text):
                                provider_num = re.search(r'\d{6}', text).group(0)
                            elif span_bold and not found_bold_name:
                                # This could be the hospital name
                                name_text = text.strip()
                                # Normalize apostrophes in name
                                name_text = name_text.replace('\u2019', "'").replace('\u2018', "'")
                                # Check if it looks like a hospital name (mostly caps, reasonable length)
                                # Allow apostrophes, periods, hyphens, dashes, ampersands, commas, +, /
                                if name_text and len(name_text) > 5:
                                    # Match if mostly uppercase letters with allowed punctuation
                                    if re.match(r"^[A-Z][A-Z0-9\s\.'\-\u2013\u2014&,+/]+$", name_text):
                                        bold_name = name_text
                                        found_bold_name = True
                            elif not span_bold and found_bold_name:
                                rest_text += text

                        # Validate the entry
                        if bold_name:
                            # Skip "See" cross-references
                            if rest_text.strip().startswith("See "):
                                pass
                            # Skip state names and county headers
                            elif bold_name in ['ALABAMA', 'ALASKA', 'ARIZONA', 'ARKANSAS', 'CALIFORNIA',
                                              'COLORADO', 'CONNECTICUT', 'DELAWARE', 'FLORIDA', 'GEORGIA']:
                                pass
                            # Check if it has a provider number or address pattern
                            elif provider_num or (rest_text.strip().startswith(",") and re.search(r'\d+\s+[A-Za-z]', rest_text)):
                                hospital_entries.append({
                                    'name': bold_name,
                                    'provider_number': provider_num,
                                    'line_text': normalize_text(line_text),
                                    'x': x,
                                    'y': y
                                })

                    # Add to column lists
                    if line_text.strip():
                        if x < col_split:
                            left_items.append((x, y, line_text))
                        else:
                            right_items.append((x, y, line_text))

        # Sort each column by y position
        left_items.sort(key=lambda item: item[1])
        right_items.sort(key=lambda item: item[1])

        # Combine columns
        for _, _, text in left_items:
            full_text += text + "\n"
        for _, _, text in right_items:
            full_text += text + "\n"

    doc.close()
    return normalize_text(full_text), hospital_entries


def parse_hospitals_from_font_detection(text: str, hospital_entries: list[dict]) -> list[Hospital]:
    """Parse hospital entries using font-detected entries for reliable identification.

    Args:
        text: Full normalized text from PDF
        hospital_entries: List of hospital entries detected by font analysis

    Returns:
        List of Hospital objects
    """
    hospitals = []
    lines = text.split('\n')

    # Build a mapping of state and county from the text
    current_state = ""
    current_county = ""
    current_city = ""

    # First pass: identify state/county headers and their line positions
    state_county_map = []  # List of (line_index, state, city, county)

    for i, line in enumerate(lines):
        line = line.strip()

        # Detect state headers
        state_match = re.match(r'^(ALABAMA|ALASKA|ARIZONA|ARKANSAS|CALIFORNIA|COLORADO|CONNECTICUT|DELAWARE|FLORIDA|GEORGIA|HAWAII|IDAHO|ILLINOIS|INDIANA|IOWA|KANSAS|KENTUCKY|LOUISIANA|MAINE|MARYLAND|MASSACHUSETTS|MICHIGAN|MINNESOTA|MISSISSIPPI|MISSOURI|MONTANA|NEBRASKA|NEVADA|NEW HAMPSHIRE|NEW JERSEY|NEW MEXICO|NEW YORK|NORTH CAROLINA|NORTH DAKOTA|OHIO|OKLAHOMA|OREGON|PENNSYLVANIA|RHODE ISLAND|SOUTH CAROLINA|SOUTH DAKOTA|TENNESSEE|TEXAS|UTAH|VERMONT|VIRGINIA|WASHINGTON|WEST VIRGINIA|WISCONSIN|WYOMING)$', line)
        if state_match:
            current_state = state_match.group(1)
            continue

        # Detect city-county headers
        county_match = re.match(r'^([A-Z][A-Z\s\.]+)[-—](.+\s+County)$', line)
        if county_match:
            current_city = county_match.group(1).strip()
            current_county = county_match.group(2).strip()
            state_county_map.append((i, current_state, current_city, current_county))

    # Process each font-detected hospital entry
    for entry in hospital_entries:
        hospital = Hospital()
        hospital.name = entry['name']
        hospital.medicare_provider_number = entry.get('provider_number', '')

        # Find the entry's line in the text to get surrounding context
        entry_line = entry['line_text']

        # Find which state/county this entry belongs to
        # Look for the most recent county header before this entry
        for i, line in enumerate(lines):
            if entry_line in line or line.startswith(entry_line[:30]):
                # Find the most recent state/county before this line
                for idx, state, city, county in reversed(state_county_map):
                    if idx < i:
                        hospital.state = state
                        hospital.city = city
                        hospital.county = county
                        break
                break

        # Collect the full entry text (from this line until next hospital or section)
        entry_text = ""
        found_start = False
        for i, line in enumerate(lines):
            if not found_start:
                if entry_line in line or line.startswith(entry_line[:30]):
                    found_start = True
                    entry_text = line
            else:
                line_stripped = line.strip()
                # Stop at next hospital, county header, or page markers
                if re.match(r'^[A-Z][A-Z\s\.]+[-—].+County$', line_stripped):
                    break
                if line_stripped.startswith('Hospitals, U.S.') or line_stripped.startswith('© 20'):
                    continue
                if line_stripped.startswith('Hospital, Medicare Provider'):
                    continue
                # Check if this line starts a new hospital entry (bold name with provider number pattern)
                if re.match(r"^[★□⇑uenwW\s\t]*[A-Z][A-Za-z0-9\s\.'\-&,+/]+\s*\(\d{6}\)", line_stripped):
                    break
                # Check for military hospital pattern (all caps + comma + address)
                if re.match(r"^[★□⇑uenwW\s\t]*[A-Z][A-Z0-9\s\.'\-&,+/]+,\s*\d+\s+[A-Za-z]", line_stripped):
                    break

                entry_text += " " + line_stripped

        # Parse the hospital entry details
        parse_hospital_entry(hospital, entry_text)
        hospitals.append(hospital)

    return hospitals


def parse_hospitals(text: str) -> list[Hospital]:
    """Legacy function - parse hospitals using regex patterns.

    Note: For better accuracy, use parse_hospitals_from_font_detection() instead.
    """
    hospitals = []
    current_state = ""
    current_county = ""
    current_city = ""

    lines = text.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Detect state headers
        state_match = re.match(r'^(ALABAMA|ALASKA|ARIZONA|ARKANSAS|CALIFORNIA|COLORADO|CONNECTICUT|DELAWARE|FLORIDA|GEORGIA|HAWAII|IDAHO|ILLINOIS|INDIANA|IOWA|KANSAS|KENTUCKY|LOUISIANA|MAINE|MARYLAND|MASSACHUSETTS|MICHIGAN|MINNESOTA|MISSISSIPPI|MISSOURI|MONTANA|NEBRASKA|NEVADA|NEW HAMPSHIRE|NEW JERSEY|NEW MEXICO|NEW YORK|NORTH CAROLINA|NORTH DAKOTA|OHIO|OKLAHOMA|OREGON|PENNSYLVANIA|RHODE ISLAND|SOUTH CAROLINA|SOUTH DAKOTA|TENNESSEE|TEXAS|UTAH|VERMONT|VIRGINIA|WASHINGTON|WEST VIRGINIA|WISCONSIN|WYOMING)$', line)
        if state_match:
            current_state = state_match.group(1)
            i += 1
            continue

        # Detect city-county headers
        county_match = re.match(r'^([A-Z][A-Z\s\.]+)[-—](.+\s+County)$', line)
        if county_match:
            current_city = county_match.group(1).strip()
            current_county = county_match.group(2).strip()
            i += 1
            continue

        # Skip cross-references and sub-facilities
        if ' See ' in line or line.endswith(' See') or '(Includes ' in line:
            i += 1
            continue

        # Detect hospital entry with provider number
        hospital_match = re.match(r"^(?:[★□⇑uenwW][\s\t]+|[\s\t])*([A-Z][A-Za-z0-9\s\.'\-&,+/]+)\s*\((\d{6})\)", line)

        # Or hospital without provider number (generalized pattern)
        hospital_no_id_match = None
        if not hospital_match:
            hospital_no_id_match = re.match(
                r"^(?:[★□⇑uenwW][\s\t]+|[\s\t])*"
                r"([A-Z][A-Z0-9\s\.'\-&,+/]+)"
                r",\s*\d+\s+[A-Za-z]",
                line
            )

        if hospital_match or hospital_no_id_match:
            hospital = Hospital()
            if hospital_match:
                hospital.name = hospital_match.group(1).strip()
                hospital.medicare_provider_number = hospital_match.group(2)
            else:
                hospital.name = hospital_no_id_match.group(1).strip()
                hospital.medicare_provider_number = ""
            hospital.state = current_state
            hospital.county = current_county
            hospital.city = current_city

            entry_text = line
            i += 1

            # Read until next hospital or section
            while i < len(lines):
                next_line = lines[i].strip()
                if re.match(r'^[A-Z][A-Z\s\.]+[-—].+County$', next_line):
                    break
                if re.match(r"^(?:[★□⇑uenwW][\s\t]+|[\s\t])*[A-Z][A-Za-z0-9\s\.'\-&,+/]+\s*\(\d{6}\)", next_line):
                    break
                if re.match(r"^(?:[★□⇑uenwW][\s\t]+|[\s\t])*[A-Z][A-Z0-9\s\.'\-&,+/]+,\s*\d+\s+[A-Za-z]", next_line):
                    break
                if next_line.startswith('Hospitals, U.S.') or next_line.startswith('© 20'):
                    i += 1
                    continue
                if next_line.startswith('Hospital, Medicare Provider'):
                    i += 1
                    continue
                entry_text += " " + next_line
                i += 1

            parse_hospital_entry(hospital, entry_text)
            hospitals.append(hospital)
            continue

        i += 1

    return hospitals


def parse_hospital_entry(hospital: Hospital, text: str) -> None:
    """Parse individual hospital entry text into Hospital object."""

    # Extract address and zip code
    # Pattern: street address, Zip XXXXX-XXXX
    zip_match = re.search(r'Zip\s+(\d{5}(?:–\d{4})?)', text)
    if zip_match:
        hospital.zip_code = zip_match.group(1).replace('–', '-')

    # Extract address (between provider number/hospital name and Zip)
    addr_match = re.search(r'\(\d{6}\),?\s*(.+?),?\s*Zip', text)
    if addr_match:
        hospital.address = addr_match.group(1).strip().rstrip(',')
    else:
        # Fallback for hospitals without provider numbers (e.g., VA hospitals)
        # Look for address after hospital name (all caps followed by comma and street)
        addr_fallback = re.search(r'^[A-Z][A-Z\s\.\'\-&,+/]+,\s*(.+?),?\s*Zip', text)
        if addr_fallback:
            hospital.address = addr_fallback.group(1).strip().rstrip(',')

    # Clean up address - remove any accreditation symbols that may have been captured
    if hospital.address:
        # Remove common accreditation symbols and clean up
        hospital.address = re.sub(r'\s+[uenwWs□★⇑]\s*,?\s*$', '', hospital.address)
        hospital.address = re.sub(r',\s+[uenwWs□★⇑]\s*,', ',', hospital.address)
        hospital.address = hospital.address.strip().rstrip(',')

    # Extract telephone
    tel_match = re.search(r'tel\.\s*([\d/–\-]+)', text)
    if tel_match:
        hospital.telephone = tel_match.group(1).replace('–', '-')

    # Extract contacts
    contact_patterns = {
        'primary_contact': r'Primary Contact:\s*([^,\n]+(?:,\s*[^,\n]+)?)',
        'coo': r'COO:\s*([^,\n]+(?:,\s*[^,\n]+)?)',
        'cfo': r'CFO:\s*([^,\n]+(?:,\s*[^,\n]+)?)',
        'cmo': r'CMO:\s*([^,\n]+(?:,\s*M\.D\.[^,\n]*)?)',
        'cio': r'CIO:\s*([^,\n]+(?:,\s*[^,\n]+)?)',
        'chr': r'CHR:\s*([^,\n]+(?:,\s*[^,\n]+)?)',
        'cno': r'CNO:\s*([^,\n]+(?:,\s*[^,\n]+)?)',
    }

    for field_name, pattern in contact_patterns.items():
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            # Clean up the value - stop at next field marker
            value = re.split(r'\s+(?:COO|CFO|CMO|CIO|CHR|CNO|Web address|Control):', value)[0]
            setattr(hospital, field_name, value.strip())

    # Extract web address
    web_match = re.search(r'Web address[:\s]+([^\s]+(?:www\.[^\s]+|https?://[^\s]+))', text)
    if web_match:
        hospital.web_address = web_match.group(1).strip()
    else:
        # Alternative pattern
        web_match = re.search(r'(https?://[^\s]+|www\.[^\s]+)', text)
        if web_match:
            hospital.web_address = web_match.group(1).strip()

    # Extract control type
    control_match = re.search(r'Control:\s*([^S]+?)(?:\s+Service:|$)', text)
    if control_match:
        hospital.control = control_match.group(1).strip()

    # Extract services
    service_match = re.search(r'Service:\s*([^\n]+?)(?:\s+Staffed Beds:|$)', text)
    if service_match:
        hospital.services = service_match.group(1).strip()

    # Extract staffed beds
    beds_match = re.search(r'Staffed Beds:\s*(\d+)', text)
    if beds_match:
        hospital.staffed_beds = beds_match.group(1)

    # Extract personnel count
    personnel_match = re.search(r'Personnel:\s*(\d+)', text)
    if personnel_match:
        hospital.personnel = personnel_match.group(1)


def save_to_csv(hospitals: list[Hospital], output_path: str) -> None:
    """Save hospital data to CSV file."""
    if not hospitals:
        print("No hospitals to save")
        return

    fieldnames = [
        'name', 'medicare_provider_number', 'address', 'city', 'county',
        'state', 'zip_code', 'telephone', 'primary_contact', 'coo', 'cfo',
        'cmo', 'cio', 'chr', 'cno', 'web_address', 'control', 'services',
        'staffed_beds', 'personnel'
    ]

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for hospital in hospitals:
            writer.writerow(asdict(hospital))

    print(f"Saved {len(hospitals)} hospitals to {output_path}")


def save_to_json(hospitals: list[Hospital], output_path: str) -> None:
    """Save hospital data to JSON file."""
    data = [asdict(h) for h in hospitals]
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    print(f"Saved {len(hospitals)} hospitals to {output_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Extract hospital data from AHA Guide PDF')
    parser.add_argument('pdf_path', help='Path to the PDF file')
    parser.add_argument('--output', '-o', default='hospitals', help='Output filename (without extension)')
    parser.add_argument('--format', '-f', choices=['csv', 'json', 'both'], default='both',
                       help='Output format (default: both)')

    args = parser.parse_args()

    print(f"Extracting text from {args.pdf_path}...")
    text, hospital_entries = extract_text_from_pdf(args.pdf_path)

    print("Parsing hospital data using font-based detection...")
    hospitals = parse_hospitals_from_font_detection(text, hospital_entries)

    print(f"Found {len(hospitals)} hospitals")

    if args.format in ('csv', 'both'):
        save_to_csv(hospitals, f"{args.output}.csv")

    if args.format in ('json', 'both'):
        save_to_json(hospitals, f"{args.output}.json")

    # Print summary
    if hospitals:
        print("\nSample extracted data:")
        for hospital in hospitals[:3]:
            print(f"\n  Name: {hospital.name}")
            print(f"  Address: {hospital.address}")
            print(f"  City: {hospital.city}, County: {hospital.county}, State: {hospital.state}")
            print(f"  Zip: {hospital.zip_code}")
            print(f"  Phone: {hospital.telephone}")
            print(f"  Primary Contact: {hospital.primary_contact}")
            print(f"  Web: {hospital.web_address}")
            print(f"  Control: {hospital.control}")
            print(f"  Services: {hospital.services}")
            print(f"  Staffed Beds: {hospital.staffed_beds}")


if __name__ == '__main__':
    main()

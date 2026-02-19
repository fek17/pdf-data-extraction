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


# All US state names for header detection
US_STATES = {
    'ALABAMA', 'ALASKA', 'ARIZONA', 'ARKANSAS', 'CALIFORNIA', 'COLORADO',
    'CONNECTICUT', 'DELAWARE', 'FLORIDA', 'GEORGIA', 'HAWAII', 'IDAHO',
    'ILLINOIS', 'INDIANA', 'IOWA', 'KANSAS', 'KENTUCKY', 'LOUISIANA',
    'MAINE', 'MARYLAND', 'MASSACHUSETTS', 'MICHIGAN', 'MINNESOTA',
    'MISSISSIPPI', 'MISSOURI', 'MONTANA', 'NEBRASKA', 'NEVADA',
    'NEW HAMPSHIRE', 'NEW JERSEY', 'NEW MEXICO', 'NEW YORK',
    'NORTH CAROLINA', 'NORTH DAKOTA', 'OHIO', 'OKLAHOMA', 'OREGON',
    'PENNSYLVANIA', 'RHODE ISLAND', 'SOUTH CAROLINA', 'SOUTH DAKOTA',
    'TENNESSEE', 'TEXAS', 'UTAH', 'VERMONT', 'VIRGINIA', 'WASHINGTON',
    'WEST VIRGINIA', 'WISCONSIN', 'WYOMING'
}

US_STATES_PATTERN = re.compile(r'^(' + '|'.join(sorted(US_STATES, key=len, reverse=True)) + r')$')


def extract_text_from_pdf(pdf_path: str) -> tuple[list[str], list[dict], dict]:
    """Extract text from PDF with font info for hospital detection.

    Returns:
        tuple: (all_lines, hospital_entries, page_line_ranges)
            - all_lines: list of normalized text lines
            - hospital_entries: list of dicts with hospital detection info including 'page_num'
            - page_line_ranges: dict mapping page_num to (start_line_idx, end_line_idx)
    """
    all_lines = []
    hospital_entries = []
    page_line_ranges = {}
    doc = fitz.open(pdf_path)

    # Skip patterns - headers and footers
    skip_patterns = [
        'Hospital, Medicare Provider Number',
        'Hospitals in the United States',
        'by State',
        '© 20',
        'Hospitals   A',
    ]

    for page_num, page in enumerate(doc):
        start_line_idx = len(all_lines)

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
                                name_text = text.strip()
                                name_text = name_text.replace('\u2019', "'").replace('\u2018', "'")
                                if name_text and len(name_text) > 5:
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
                            # Skip state names
                            elif bold_name in US_STATES:
                                pass
                            # Check if it has a provider number or address pattern
                            elif provider_num or (rest_text.strip().startswith(",") and re.search(r'\d+\s+[A-Za-z]', rest_text)):
                                hospital_entries.append({
                                    'name': bold_name,
                                    'provider_number': provider_num,
                                    'line_text': normalize_text(line_text),
                                    'x': x,
                                    'y': y,
                                    'page_num': page_num,
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

        # Combine columns: left first, then right
        for _, _, text in left_items:
            all_lines.append(normalize_text(text))
        for _, _, text in right_items:
            all_lines.append(normalize_text(text))

        page_line_ranges[page_num] = (start_line_idx, len(all_lines))

    doc.close()
    return all_lines, hospital_entries, page_line_ranges


def parse_hospitals_from_font_detection(
    lines: list[str],
    hospital_entries: list[dict],
    page_line_ranges: dict,
) -> list[Hospital]:
    """Parse hospital entries using font-detected entries for reliable identification.

    Uses page-scoped searching: each hospital entry is matched only within its
    own page's line range, avoiding cross-page mismatches.
    """
    hospitals = []

    # First pass: identify state/county headers and their line positions
    current_state = ""
    state_county_map = []  # List of (line_index, state, city, county)

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Detect state headers
        if US_STATES_PATTERN.match(stripped):
            current_state = stripped
            continue

        # Detect city-county headers (e.g., "ABBEVILLE-Vermilion Parish")
        # Note: first part must be ALL CAPS (city name), so no IGNORECASE
        county_match = re.match(r'^([A-Z][A-Z\s\.]+)[-\u2013\u2014\u2014](.+\s+(?:County|Parish|Borough|Census Area|Municipality|city))$', stripped)
        if county_match:
            city = county_match.group(1).strip()
            county = county_match.group(2).strip()
            state_county_map.append((i, current_state, city, county))

    # Process each font-detected hospital entry
    for entry in hospital_entries:
        hospital = Hospital()
        hospital.name = entry['name']
        hospital.medicare_provider_number = entry.get('provider_number', '')

        entry_line = entry['line_text']
        page_num = entry['page_num']

        # Get the line range for this hospital's page
        page_start, page_end = page_line_ranges[page_num]

        # Find the entry's line within its page
        entry_line_idx = None
        for i in range(page_start, page_end):
            if entry_line in lines[i]:
                entry_line_idx = i
                break

        # Fallback: match by provider number within the page
        if entry_line_idx is None and entry.get('provider_number'):
            prov = f"({entry['provider_number']})"
            first_word = hospital.name.split()[0]
            for i in range(page_start, page_end):
                if prov in lines[i] and first_word in lines[i]:
                    entry_line_idx = i
                    break

        if entry_line_idx is None:
            # Could not find the entry in the text - skip
            hospitals.append(hospital)
            continue

        # Find the most recent state/county before this line
        for idx, state, city, county in reversed(state_county_map):
            if idx < entry_line_idx:
                hospital.state = state
                hospital.city = city
                hospital.county = county
                break

        # Collect the full entry text from entry line until next hospital or section
        entry_text = lines[entry_line_idx]
        paren_depth = entry_text.count('(') - entry_text.count(')')

        for i in range(entry_line_idx + 1, len(lines)):
            line_stripped = lines[i].strip()

            # Stop at county/city headers (city name is ALL CAPS)
            if re.match(r'^[A-Z][A-Z\s\.]+[-\u2013\u2014\u2014](.+\s+(?:County|Parish|Borough|Census Area|Municipality|city))$', line_stripped):
                break
            # Stop at state headers
            if line_stripped in US_STATES:
                break
            # Skip page headers/footers
            if line_stripped.startswith('Hospitals, U.S.') or line_stripped.startswith('© 20'):
                paren_depth += line_stripped.count('(') - line_stripped.count(')')
                continue
            if line_stripped.startswith('Hospital, Medicare Provider'):
                paren_depth += line_stripped.count('(') - line_stripped.count(')')
                continue
            # Skip license/copyright boilerplate
            if 'This document is licensed to' in line_stripped:
                continue
            if 'copyrighted by the American Hospital Association' in line_stripped:
                continue
            if 'Distribution or duplication is prohibited' in line_stripped:
                continue

            # Only check for new hospital patterns if not inside parentheses
            if paren_depth <= 0:
                if re.match(r"^[★□⇑uenwW\s\t]*[A-Z][A-Za-z0-9\s\.'\-&,+/]+\s*\(\d{6}\)", line_stripped):
                    break
                if re.match(r"^[★□⇑uenwW\s\t]*[A-Z][A-Z0-9\s\.'\-&,+/]+,\s*\d+\s+[A-Za-z]", line_stripped):
                    break

            # Update parentheses depth after pattern checks
            paren_depth += line_stripped.count('(') - line_stripped.count(')')

            entry_text += " " + line_stripped

        # Parse the hospital entry details
        parse_hospital_entry(hospital, entry_text)
        hospitals.append(hospital)

    return hospitals


def parse_hospital_entry(hospital: Hospital, text: str) -> None:
    """Parse individual hospital entry text into Hospital object."""

    # Extract address and zip code
    # Pattern: street address, Zip XXXXX-XXXX
    zip_match = re.search(r'Zip\s+(\d{5}(?:[-\u2013]\d{4})?)', text)
    if zip_match:
        hospital.zip_code = zip_match.group(1).replace('\u2013', '-')

    # Extract address (between provider number/hospital name and Zip)
    addr_match = re.search(r'\(\d{6}\),?\s*(.+?),?\s*Zip', text)
    if addr_match:
        hospital.address = addr_match.group(1).strip().rstrip(',')
    else:
        # Fallback for hospitals without provider numbers (e.g., VA hospitals)
        addr_fallback = re.search(r'^[A-Z][A-Z\s\.\'\-&,+/]+,\s*(.+?),?\s*Zip', text)
        if addr_fallback:
            hospital.address = addr_fallback.group(1).strip().rstrip(',')

    # Clean up address - remove any accreditation symbols that may have been captured
    if hospital.address:
        hospital.address = re.sub(r'\s+[uenwWs\u25a1\u2605\u21d1]\s*,?\s*$', '', hospital.address)
        hospital.address = re.sub(r',\s+[uenwWs\u25a1\u2605\u21d1]\s*,', ',', hospital.address)
        hospital.address = hospital.address.strip().rstrip(',')

    # Extract telephone
    tel_match = re.search(r'tel\.\s*([\d/\u2013\-]+)', text)
    if tel_match:
        hospital.telephone = tel_match.group(1).replace('\u2013', '-')

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

    # Extract staffed beds - handle various spacing including non-breaking spaces
    beds_match = re.search(r'Staffed\s*Beds[:\s\xa0]+(\d+)', text)
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
    lines, hospital_entries, page_line_ranges = extract_text_from_pdf(args.pdf_path)

    print("Parsing hospital data using font-based detection...")
    hospitals = parse_hospitals_from_font_detection(lines, hospital_entries, page_line_ranges)

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

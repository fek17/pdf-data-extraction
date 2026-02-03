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


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from PDF file."""
    full_text = ""
    doc = fitz.open(pdf_path)
    for page in doc:
        text = page.get_text()
        if text:
            full_text += text + "\n"
    doc.close()
    return normalize_text(full_text)


def parse_hospitals(text: str) -> list[Hospital]:
    """Parse hospital entries from extracted text."""
    hospitals = []

    # Track current state and county
    current_state = ""
    current_county = ""
    current_city = ""

    # Split text into lines for processing
    lines = text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Detect state headers (e.g., "ALABAMA")
        state_match = re.match(r'^(ALABAMA|ALASKA|ARIZONA|ARKANSAS|CALIFORNIA|COLORADO|CONNECTICUT|DELAWARE|FLORIDA|GEORGIA|HAWAII|IDAHO|ILLINOIS|INDIANA|IOWA|KANSAS|KENTUCKY|LOUISIANA|MAINE|MARYLAND|MASSACHUSETTS|MICHIGAN|MINNESOTA|MISSISSIPPI|MISSOURI|MONTANA|NEBRASKA|NEVADA|NEW HAMPSHIRE|NEW JERSEY|NEW MEXICO|NEW YORK|NORTH CAROLINA|NORTH DAKOTA|OHIO|OKLAHOMA|OREGON|PENNSYLVANIA|RHODE ISLAND|SOUTH CAROLINA|SOUTH DAKOTA|TENNESSEE|TEXAS|UTAH|VERMONT|VIRGINIA|WASHINGTON|WEST VIRGINIA|WISCONSIN|WYOMING)$', line)
        if state_match:
            current_state = state_match.group(1)
            i += 1
            continue

        # Detect city-county headers (e.g., "ALABASTER-Shelby County")
        # After normalization, em-dashes become regular hyphens
        county_match = re.match(r'^([A-Z][A-Z\s\.]+)[-—](.+\s+County)$', line)
        if county_match:
            current_city = county_match.group(1).strip()
            current_county = county_match.group(2).strip()
            i += 1
            continue

        # Detect hospital entry (starts with symbol or hospital name with provider number)
        # Hospital names are in caps followed by Medicare Provider Number in parentheses
        # Include apostrophes (with possible lowercase after), hyphens, ampersands, commas, periods
        hospital_match = re.match(r"^[★□⇑uenwW\s\t]*([A-Z][A-Za-z0-9\s\.'\-&,]+)\s*\((\d{6})\)", line)
        if hospital_match:
            hospital = Hospital()
            hospital.name = hospital_match.group(1).strip()
            hospital.medicare_provider_number = hospital_match.group(2)
            hospital.state = current_state
            hospital.county = current_county
            hospital.city = current_city

            # Continue reading the hospital entry
            entry_text = line
            i += 1

            # Read until we hit next hospital, county header, or state header
            while i < len(lines):
                next_line = lines[i].strip()

                # Check for end markers
                if re.match(r'^(ALABAMA|ALASKA|ARIZONA|ARKANSAS|CALIFORNIA|COLORADO|CONNECTICUT|DELAWARE|FLORIDA|GEORGIA|HAWAII|IDAHO|ILLINOIS|INDIANA|IOWA|KANSAS|KENTUCKY|LOUISIANA|MAINE|MARYLAND|MASSACHUSETTS|MICHIGAN|MINNESOTA|MISSISSIPPI|MISSOURI|MONTANA|NEBRASKA|NEVADA|NEW HAMPSHIRE|NEW JERSEY|NEW MEXICO|NEW YORK|NORTH CAROLINA|NORTH DAKOTA|OHIO|OKLAHOMA|OREGON|PENNSYLVANIA|RHODE ISLAND|SOUTH CAROLINA|SOUTH DAKOTA|TENNESSEE|TEXAS|UTAH|VERMONT|VIRGINIA|WASHINGTON|WEST VIRGINIA|WISCONSIN|WYOMING)$', next_line):
                    break
                if re.match(r'^[A-Z][A-Z\s\.]+[-—].+County$', next_line):
                    break
                if re.match(r"^[★□⇑uenwW\s\t]*[A-Z][A-Za-z0-9\s\.'\-&,]+\s*\(\d{6}\)", next_line):
                    break
                if next_line.startswith('Hospitals, U.S.') or next_line.startswith('© 2026'):
                    i += 1
                    continue
                if next_line.startswith('Hospital, Medicare Provider'):
                    i += 1
                    continue

                entry_text += " " + next_line
                i += 1

            # Parse the hospital entry
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

    # Extract address (between provider number and Zip)
    addr_match = re.search(r'\(\d{6}\),?\s*(.+?),?\s*Zip', text)
    if addr_match:
        hospital.address = addr_match.group(1).strip().rstrip(',')

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


def save_to_csv(hospitals: list[Hospital], output_path: str) -> None:
    """Save hospital data to CSV file."""
    if not hospitals:
        print("No hospitals to save")
        return

    fieldnames = [
        'name', 'medicare_provider_number', 'address', 'city', 'county',
        'state', 'zip_code', 'telephone', 'primary_contact', 'coo', 'cfo',
        'cmo', 'cio', 'chr', 'cno', 'web_address', 'control', 'services',
        'staffed_beds'
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
    text = extract_text_from_pdf(args.pdf_path)

    print("Parsing hospital data...")
    hospitals = parse_hospitals(text)

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

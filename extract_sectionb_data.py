#!/usr/bin/env python3
"""
Script to extract hospital and healthcare system/network data from AHA Guide Section B PDF.

Extracts: healthcare system name, system ID, system type, hospital name, ownership type,
staffed beds, address, city, state, zip code, telephone, contact person, and web address.
"""

import re
import json
import csv
import fitz  # PyMuPDF
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class HospitalEntry:
    healthcare_system: str = ""
    system_id: str = ""
    system_type: str = ""  # IO, NP, CO, CC, etc.
    system_classification: str = ""  # Decentralized, Independent, Centralized, etc.
    system_address: str = ""
    system_city: str = ""
    system_state: str = ""
    system_zip: str = ""
    system_telephone: str = ""
    system_ceo: str = ""
    section: str = ""  # "Systems" or "Networks"
    hospital_name: str = ""
    ownership_type: str = ""  # O=Owned, L=Leased, C=Contract-managed, S=Sponsored, PART=Part of system
    staffed_beds: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    state_abbrev: str = ""
    zip_code: str = ""
    telephone: str = ""
    contact: str = ""
    web_address: str = ""


def normalize_text(text: str) -> str:
    """Normalize Unicode characters for easier parsing."""
    text = text.replace('\u2013', '-').replace('\u2014', '-')
    text = text.replace('\u2019', "'").replace('\u2018', "'")
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u00a0', ' ')
    return text


# US state abbreviations mapping
STATE_ABBREVS = {
    'ALABAMA': 'AL', 'ALASKA': 'AK', 'ARIZONA': 'AZ', 'ARKANSAS': 'AR',
    'CALIFORNIA': 'CA', 'COLORADO': 'CO', 'CONNECTICUT': 'CT', 'DELAWARE': 'DE',
    'FLORIDA': 'FL', 'GEORGIA': 'GA', 'HAWAII': 'HI', 'IDAHO': 'ID',
    'ILLINOIS': 'IL', 'INDIANA': 'IN', 'IOWA': 'IA', 'KANSAS': 'KS',
    'KENTUCKY': 'KY', 'LOUISIANA': 'LA', 'MAINE': 'ME', 'MARYLAND': 'MD',
    'MASSACHUSETTS': 'MA', 'MICHIGAN': 'MI', 'MINNESOTA': 'MN',
    'MISSISSIPPI': 'MS', 'MISSOURI': 'MO', 'MONTANA': 'MT', 'NEBRASKA': 'NE',
    'NEVADA': 'NV', 'NEW HAMPSHIRE': 'NH', 'NEW JERSEY': 'NJ',
    'NEW MEXICO': 'NM', 'NEW YORK': 'NY', 'NORTH CAROLINA': 'NC',
    'NORTH DAKOTA': 'ND', 'OHIO': 'OH', 'OKLAHOMA': 'OK', 'OREGON': 'OR',
    'PENNSYLVANIA': 'PA', 'RHODE ISLAND': 'RI', 'SOUTH CAROLINA': 'SC',
    'SOUTH DAKOTA': 'SD', 'TENNESSEE': 'TN', 'TEXAS': 'TX', 'UTAH': 'UT',
    'VERMONT': 'VT', 'VIRGINIA': 'VA', 'WASHINGTON': 'WA',
    'WEST VIRGINIA': 'WV', 'WISCONSIN': 'WI', 'WYOMING': 'WY',
    'DISTRICT OF COLUMBIA': 'DC', 'PUERTO RICO': 'PR',
    'AMERICAN SAMOA': 'AS', 'GUAM': 'GU',
    'NORTHERN MARIANA ISLANDS': 'MP', 'VIRGIN ISLANDS': 'VI',
}

US_STATES = set(STATE_ABBREVS.keys())
# Reverse lookup: abbreviation -> full name
ABBREV_TO_STATE = {v: k for k, v in STATE_ABBREVS.items()}
# Sort by length (longest first) so "NEW HAMPSHIRE" matches before "NEW"
SORTED_STATES = sorted(US_STATES, key=len, reverse=True)

# Skip patterns for headers/footers/boilerplate
SKIP_PATTERNS = [
    'For explanation of codes following names',
    'Indicates Type III membership',
    'Section B',
    '© 2026',
    '©  2026',
    'Health Care Systems, Networks and Alliances',
    'Health Care Systems   B',
    'Health Care Systems Index',
    'Headquarters of Health Care Systems',
    'This document is licensed to',
    'copyrighted by the American Hospital Association',
    'Distribution or duplication is prohibited',
    'Networks and',
    'their Hospitals',
]


def classify_page(page) -> str:
    """Classify a PDF page as 'systems', 'networks', 'index', or 'skip'.

    Uses the running header at the top of each page to determine the section.
    """
    text = page.get_text()

    if 'Health Care Systems Index' in text:
        return 'index'
    if 'Headquarters of Health Care Systems' in text:
        return 'index'

    # Check the running header (typically in the top ~50px)
    blocks = page.get_text("dict")["blocks"]
    for block in blocks:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            y = line["bbox"][1]
            if y < 50:
                line_text = "".join(s["text"] for s in line["spans"])
                if line_text.strip().startswith('Networks /'):
                    return 'networks'
                if line_text.strip().startswith('Systems /'):
                    return 'systems'

    # Default to systems for Section B content pages
    if 'Section B' in text:
        return 'systems'

    return 'skip'


def extract_section_b(pdf_path: str) -> list[HospitalEntry]:
    """Extract healthcare system and hospital data from Section B PDF."""
    doc = fitz.open(pdf_path)

    # Phase 1: Classify pages and collect text with font info
    all_lines = []
    system_headers = []
    network_headers = []
    page_ranges = {}

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_type = classify_page(page)

        if page_type in ('index', 'skip'):
            continue

        start_idx = len(all_lines)
        blocks = page.get_text("dict")["blocks"]
        page_width = page.rect.width
        col_split = page_width / 2

        # Collect items with position, text, and optional header info
        # Each item: (column, y, text, header_info_or_None)
        left_items = []
        right_items = []

        for block in blocks:
            if block["type"] != 0:
                continue
            block_lines = block["lines"]
            skip_line_indices = set()

            for line_i, line in enumerate(block_lines):
                if line_i in skip_line_indices:
                    continue

                spans = line["spans"]
                bbox = line["bbox"]
                x, y = bbox[0], bbox[1]

                line_text = "".join(span["text"] for span in spans)
                line_text_norm = normalize_text(line_text)

                # Skip header/footer/boilerplate lines
                if any(skip in line_text for skip in SKIP_PATTERNS):
                    continue

                # Skip page number lines (e.g., "B4", "B5", "B169")
                if re.match(r'^B\d+$', line_text.strip()):
                    continue

                header_info = None

                if page_type == 'systems':
                    # Detect healthcare system headers:
                    # Bold span at size >= 7.7 containing "XXXX:" pattern
                    has_bold_system_span = any(
                        (bool(s["flags"] & 16) or "Bold" in s.get("font", ""))
                        and s.get("size", 0) >= 7.7
                        and re.search(r'\d{4}:', s["text"])
                        for s in spans
                    )

                    if has_bold_system_span:
                        header_match = re.match(
                            r'^[w\s]*(\d{4}):\s+(.+?)\s*\(([A-Z]{2,4})\)\s*$',
                            line_text_norm.strip()
                        )
                        if header_match:
                            header_info = {
                                'name': header_match.group(2).strip(),
                                'id': header_match.group(1),
                                'type': header_match.group(3),
                                'page_num': page_num,
                                'section': 'Systems',
                                'target': 'system',
                            }
                        else:
                            # Multi-line header: name is too long, type code
                            # is on the next bold line(s). Look ahead to find
                            # the line ending with (XX).
                            combined_text = line_text_norm.strip()
                            for ahead_i in range(line_i + 1, len(block_lines)):
                                ahead_line = block_lines[ahead_i]
                                ahead_spans = ahead_line["spans"]
                                ahead_bold = any(
                                    (bool(s["flags"] & 16) or "Bold" in s.get("font", ""))
                                    and s.get("size", 0) >= 7.7
                                    for s in ahead_spans
                                )
                                if not ahead_bold:
                                    break
                                ahead_text = normalize_text(
                                    "".join(s["text"] for s in ahead_spans)
                                ).strip()
                                combined_text += " " + ahead_text
                                skip_line_indices.add(ahead_i)
                                # Check if combined text now matches
                                header_match = re.match(
                                    r'^[w\s]*(\d{4}):\s+(.+?)\s*\(([A-Z]{2,4})\)\s*$',
                                    combined_text
                                )
                                if header_match:
                                    header_info = {
                                        'name': header_match.group(2).strip(),
                                        'id': header_match.group(1),
                                        'type': header_match.group(3),
                                        'page_num': page_num,
                                        'section': 'Systems',
                                        'target': 'system',
                                    }
                                    break

                elif page_type == 'networks':
                    # Detect network organization headers:
                    # Bold text at size ~6.3, ALL CAPS organization name
                    if len(spans) >= 1:
                        first_span = spans[0]
                        span_size = first_span.get("size", 0)
                        span_bold = (bool(first_span["flags"] & 16)
                                    or "Bold" in first_span.get("font", ""))

                        if span_bold and 6.0 <= span_size <= 6.5:
                            text_stripped = line_text_norm.strip()
                            if (re.match(r'^[A-Z][A-Z\s\.\',&\-/]+$', text_stripped)
                                    and text_stripped not in US_STATES
                                    and len(text_stripped) > 3
                                    and ',' not in text_stripped[:20]
                                    and not re.search(r'\d', text_stripped)
                                    and 'Zip' not in text_stripped
                                    and 'tel.' not in text_stripped):
                                header_info = {
                                    'name': text_stripped,
                                    'id': '',
                                    'type': 'NET',
                                    'page_num': page_num,
                                    'section': 'Networks',
                                    'target': 'network',
                                }

                if line_text_norm.strip():
                    if x < col_split:
                        left_items.append((y, line_text_norm, header_info))
                    else:
                        right_items.append((y, line_text_norm, header_info))

        # Sort by y position within each column
        left_items.sort(key=lambda item: item[0])
        right_items.sort(key=lambda item: item[0])

        # Add to all_lines and record actual header positions
        for _, text, hdr in left_items:
            if hdr:
                hdr['line_idx'] = len(all_lines)
                if hdr['target'] == 'system':
                    system_headers.append(hdr)
                else:
                    network_headers.append(hdr)
            all_lines.append(text)
        for _, text, hdr in right_items:
            if hdr:
                hdr['line_idx'] = len(all_lines)
                if hdr['target'] == 'system':
                    system_headers.append(hdr)
                else:
                    network_headers.append(hdr)
            all_lines.append(text)

        page_ranges[page_num] = (start_idx, len(all_lines))

    doc.close()

    # Phase 2: Parse Systems section
    entries = parse_systems(all_lines, system_headers)

    # Phase 3: Parse Networks section
    entries += parse_networks(all_lines, network_headers)

    return entries


def parse_system_address_block(lines: list[str], start_idx: int, end_idx: int) -> tuple[dict, int]:
    """Parse the system address block that follows a system header.

    Returns (result_dict, next_line_index).
    """
    result = {
        'address': '', 'city': '', 'state': '', 'zip': '',
        'telephone': '', 'ceo': '', 'classification': '',
    }

    block_text = ""
    i = start_idx
    while i < end_idx:
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Classification line like "(Decentralized Health System)"
        class_match = re.match(r'^\((.+?)\)\s*$', line)
        if class_match:
            val = class_match.group(1)
            if 'System' in val or 'Health' in val:
                result['classification'] = val
                i += 1
                break

        # Stop at state header
        for state_name in SORTED_STATES:
            if line.startswith(state_name + ':'):
                break
        else:
            # Stop at hospital entry (beds on same line)
            if re.match(r'^[A-Z].*\((?:[OLCS]|PART),\s*\d+\s*beds?\)', line):
                break
            # Stop at wrapped hospital entry (beds on next 1-2 lines)
            if re.match(r'^[A-Z]', line):
                look = line
                for la in range(1, 3):
                    if i + la >= end_idx:
                        break
                    nl = lines[i + la].strip()
                    if not nl:
                        continue
                    look += " " + nl
                    if re.search(r'\((?:[OLCS]|PART),\s*\d+\s*beds?\)', look):
                        break
                else:
                    look = None  # didn't find bed pattern
                if look and re.search(r'\((?:[OLCS]|PART),\s*\d+\s*beds?\)', look):
                    break
            block_text += " " + line
            i += 1
            continue
        break  # hit a state header

    block_text = block_text.strip()

    # Parse address components
    zip_match = re.search(r'Zip\s+(\d{5}(?:-\d{4})?)', block_text)
    if zip_match:
        result['zip'] = zip_match.group(1)

    tel_match = re.search(r'tel\.\s*([\d/\-]+)', block_text)
    if tel_match:
        result['telephone'] = tel_match.group(1)

    if tel_match:
        after_tel = block_text[tel_match.end():]
        after_tel = re.sub(r'^[,;\s]+', '', after_tel)
        if after_tel:
            result['ceo'] = after_tel.strip().rstrip('.')

    addr_parts = block_text.split('Zip')[0] if 'Zip' in block_text else ''
    if addr_parts:
        state_match = re.search(r',?\s*([A-Z]{2})\s*$', addr_parts.strip())
        if state_match:
            result['state'] = state_match.group(1)
            before_state = addr_parts[:state_match.start()].strip()
            parts = before_state.rsplit(',', 1)
            if len(parts) == 2:
                result['address'] = parts[0].strip()
                result['city'] = parts[1].strip()
            else:
                result['address'] = before_state

    return result, i


def parse_systems(lines: list[str], system_headers: list[dict]) -> list[HospitalEntry]:
    """Parse the Systems section into hospital entries grouped by healthcare system."""
    entries = []

    for si, sys_hdr in enumerate(system_headers):
        sys_start = sys_hdr['line_idx']
        sys_end = system_headers[si + 1]['line_idx'] if si + 1 < len(system_headers) else len(lines)

        # Parse system address block
        sys_addr, i = parse_system_address_block(lines, sys_start + 1, sys_end)

        current_state = ""
        current_state_abbrev = ""

        while i < sys_end:
            line = lines[i].strip()

            if not line:
                i += 1
                continue

            # Skip summary blocks
            if (line.startswith('Owned, leased, sponsored:')
                    or line.startswith('Contract-managed:')
                    or line.startswith('Totals:')):
                i += 1
                while i < sys_end:
                    l = lines[i].strip()
                    if not l:
                        i += 1
                        break
                    if re.match(r'^(\d+\s+(hospitals|beds)|Contract|Totals)', l):
                        i += 1
                        continue
                    break
                continue

            # Skip classification lines
            if re.match(r'^\(.+\)\s*$', line) and ('System' in line or 'Health' in line):
                if not sys_addr['classification']:
                    cls_match = re.match(r'^\((.+)\)\s*$', line)
                    if cls_match:
                        sys_addr['classification'] = cls_match.group(1)
                i += 1
                continue

            # Check for state header: "STATE: HOSPITAL NAME (O, XX beds)..."
            state_found = None
            for state_name in SORTED_STATES:
                if line.startswith(state_name + ':'):
                    state_found = state_name
                    break

            if state_found:
                current_state = state_found
                current_state_abbrev = STATE_ABBREVS.get(current_state, '')
                after_state = line[len(state_found) + 1:].strip()
                if after_state:
                    i += 1
                    more_text, i = collect_hospital_text(lines, i, sys_end)
                    hospital_text = after_state + " " + more_text

                    result = parse_hospital_text(hospital_text, current_state, current_state_abbrev)
                    entry = build_entry(sys_hdr, sys_addr, result)
                    if entry.hospital_name:
                        entries.append(entry)
                else:
                    i += 1
                continue

            # Check for hospital entry: "HOSPITAL NAME (O, XX beds) address..."
            # The bed pattern may be on the same line, or split across 1-2 lines
            # when the hospital name is very long.
            if re.match(r'^[A-Z]', line) and not re.match(r'^[w\s]*\d{4}:\s+[A-Z]', line):
                # Try combining up to 2 following lines to find the bed pattern
                combined = line
                lines_consumed = 0
                found_beds = bool(re.search(
                    r'\((?:[OLCS]|PART),\s*\d+\s*beds?\)', combined))

                if not found_beds:
                    for lookahead in range(1, 3):
                        if i + lookahead >= sys_end:
                            break
                        next_l = lines[i + lookahead].strip()
                        if not next_l:
                            continue
                        # Stop if next line is a state header, system header,
                        # summary block, or a new standalone hospital
                        is_state = any(next_l.startswith(sn + ':')
                                      for sn in SORTED_STATES)
                        is_system = bool(re.match(
                            r'^[w\s]*\d{4}:\s+[A-Z]', next_l))
                        is_summary = (next_l.startswith('Owned, leased')
                                     or next_l.startswith('Contract-managed')
                                     or next_l.startswith('Totals:'))
                        is_new_hosp = bool(re.match(
                            r'^[A-Z].*\((?:[OLCS]|PART),\s*\d+\s*beds?\)',
                            next_l))
                        if is_state or is_system or is_summary or is_new_hosp:
                            break
                        combined += " " + next_l
                        lines_consumed = lookahead
                        if re.search(r'\((?:[OLCS]|PART),\s*\d+\s*beds?\)',
                                    combined):
                            found_beds = True
                            break

                if found_beds:
                    hospital_text = combined
                    i += 1 + lines_consumed
                    more_text, i = collect_hospital_text(lines, i, sys_end)
                    hospital_text = hospital_text + " " + more_text

                    result = parse_hospital_text(
                        hospital_text, current_state, current_state_abbrev)
                    entry = build_entry(sys_hdr, sys_addr, result)
                    if entry.hospital_name:
                        entries.append(entry)
                    continue

            i += 1

    return entries


def parse_networks(lines: list[str], network_headers: list[dict]) -> list[HospitalEntry]:
    """Parse the Networks section into hospital entries grouped by network."""
    entries = []

    for ni, net_hdr in enumerate(network_headers):
        net_start = net_hdr['line_idx']
        net_end = network_headers[ni + 1]['line_idx'] if ni + 1 < len(network_headers) else len(lines)

        # Parse network address block (bold lines after the name)
        net_addr = {'address': '', 'city': '', 'state': '', 'zip': '',
                    'telephone': '', 'ceo': '', 'classification': ''}
        block_text = ""
        i = net_start + 1
        while i < net_end:
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # Network address lines contain Zip or tel. and end the block
            block_text += " " + line
            if 'tel.' in line:
                i += 1
                break
            i += 1

        block_text = block_text.strip()
        zip_match = re.search(r'Zip\s+(\d{5}(?:-\d{4})?)', block_text)
        if zip_match:
            net_addr['zip'] = zip_match.group(1)
        tel_match = re.search(r'tel\.\s*([\d/\-]+)', block_text)
        if tel_match:
            net_addr['telephone'] = tel_match.group(1)
            after_tel = block_text[tel_match.end():]
            after_tel = re.sub(r'^[,;\s]+', '', after_tel)
            if after_tel:
                net_addr['ceo'] = after_tel.strip().rstrip('.')

        addr_parts = block_text.split('Zip')[0] if 'Zip' in block_text else ''
        if addr_parts:
            state_match = re.search(r',?\s*([A-Z]{2})\s*$', addr_parts.strip())
            if state_match:
                net_addr['state'] = state_match.group(1)
                before_state = addr_parts[:state_match.start()].strip()
                parts = before_state.rsplit(',', 1)
                if len(parts) == 2:
                    net_addr['address'] = parts[0].strip()
                    net_addr['city'] = parts[1].strip()

        # Determine state context from network address or first state header
        current_state = ""
        current_state_abbrev = ""

        # Try to determine from the page's state header
        # Look backward from net_start for a state header
        for j in range(net_start - 1, max(0, net_start - 30), -1):
            if j < len(lines):
                for state_name in SORTED_STATES:
                    if lines[j].strip() == state_name:
                        current_state = state_name
                        current_state_abbrev = STATE_ABBREVS.get(state_name, '')
                        break
                if current_state:
                    break

        # Now parse hospital entries in the network
        while i < net_end:
            line = lines[i].strip()

            if not line:
                i += 1
                continue

            # Check for state header (standalone state name)
            if line in US_STATES:
                current_state = line
                current_state_abbrev = STATE_ABBREVS.get(line, '')
                i += 1
                continue

            # Hospital entries: "HOSPITAL NAME, address, State, Zip..."
            hosp_match = re.match(r'^[A-Z][A-Z\s\.\'\-&,+/()]+,\s*\d+', line)
            if hosp_match:
                hospital_text = line
                i += 1
                more_text, i = collect_network_hospital_text(lines, i, net_end)
                hospital_text = hospital_text + " " + more_text

                result = parse_network_hospital_text(hospital_text, current_state, current_state_abbrev)
                entry = build_entry(net_hdr, net_addr, result)
                if entry.hospital_name:
                    entries.append(entry)
                continue

            i += 1

    return entries


def collect_hospital_text(lines: list[str], i: int, end: int) -> tuple[str, int]:
    """Collect continuation lines for a Systems hospital entry."""
    collected = ""
    while i < end:
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Stop at next state header
        for state_name in SORTED_STATES:
            if line.startswith(state_name + ':'):
                return collected.strip(), i
        # for/else: didn't break

        # Stop at summary blocks
        if (line.startswith('Owned, leased, sponsored:')
                or line.startswith('Contract-managed:')
                or line.startswith('Totals:')):
            break

        # Stop at classification lines
        if re.match(r'^\(.+\)\s*$', line) and ('System' in line or 'Health' in line):
            break

        # Stop at next hospital entry (has beds pattern on same line)
        if collected and re.match(r'^[A-Z].*\((?:[OLCS]|PART),\s*\d+\s*beds?\)', line):
            break

        # Stop at wrapped hospital entry: line looks like a hospital name
        # (ALL CAPS start, not address/contact text) and combining with
        # the next 1-2 lines produces a bed pattern
        if collected and re.match(r'^[A-Z][A-Z\s\.\'\-&+/]+', line):
            # Exclude address/contact continuation lines
            is_continuation = bool(
                re.match(r'^(Web address|Zip\s|tel\.|www\.)', line, re.IGNORECASE)
                or re.search(r'(,\s*[A-Z]{2},\s*Zip|beds?\))', line)
                or re.match(r'^\d', line)
            )
            if not is_continuation:
                look = line
                for la in range(1, 3):
                    if i + la >= end:
                        break
                    nl = lines[i + la].strip()
                    if not nl:
                        continue
                    look += " " + nl
                    if re.search(r'\((?:[OLCS]|PART),\s*\d+\s*beds?\)', look):
                        return collected.strip(), i
                # Also check if next line starts with bed pattern directly
                next_l = lines[i + 1].strip() if i + 1 < end else ''
                if re.match(r'^\((?:[OLCS]|PART),\s*\d+\s*beds?\)', next_l):
                    return collected.strip(), i

        # Stop at next system header
        if re.match(r'^[w\s]*\d{4}:\s+[A-Z]', line):
            break

        collected += " " + line
        i += 1

    return collected.strip(), i


def collect_network_hospital_text(lines: list[str], i: int, end: int) -> tuple[str, int]:
    """Collect continuation lines for a Networks hospital entry."""
    collected = ""
    while i < end:
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Stop at standalone state name
        if line in US_STATES:
            break

        # Stop at next hospital entry (ALL CAPS followed by comma and number)
        if collected and re.match(r'^[A-Z][A-Z\s\.\'\-&,+/()]+,\s*\d+', line):
            break

        collected += " " + line
        i += 1

    return collected.strip(), i


def parse_hospital_text(text: str, state: str, state_abbrev: str) -> dict:
    """Parse a Systems hospital entry text block."""
    result = {
        'hospital_name': '', 'ownership_type': '', 'staffed_beds': '',
        'address': '', 'city': '', 'state': state, 'state_abbrev': state_abbrev,
        'zip_code': '', 'telephone': '', 'contact': '', 'web_address': '',
        'section': 'Systems',
    }

    text = text.strip()

    # Match: HOSPITAL NAME (O, 123 beds) address...
    # Handle hospital names that may contain "(PART OF ...)" notation
    hosp_match = re.match(
        r'^(.+?)\s*\(([OLCS]|PART),\s*(\d+)\s*beds?\)\s*(.*)',
        text, re.DOTALL
    )

    if not hosp_match:
        return result

    result['hospital_name'] = hosp_match.group(1).strip()
    result['ownership_type'] = hosp_match.group(2)
    result['staffed_beds'] = hosp_match.group(3)
    remainder = hosp_match.group(4).strip()

    _parse_address_block(result, remainder)
    return result


def parse_network_hospital_text(text: str, state: str, state_abbrev: str) -> dict:
    """Parse a Networks hospital entry text block."""
    result = {
        'hospital_name': '', 'ownership_type': '', 'staffed_beds': '',
        'address': '', 'city': '', 'state': state, 'state_abbrev': state_abbrev,
        'zip_code': '', 'telephone': '', 'contact': '', 'web_address': '',
        'section': 'Networks',
    }

    text = text.strip()

    # Networks format: HOSPITAL NAME, street address, City, ST, Zip XXXXX; tel. ...
    # Split name from the rest at the first comma followed by address content
    name_match = re.match(r'^(.+?),\s*(\d+\s+.+)', text, re.DOTALL)
    if not name_match:
        name_match = re.match(r'^(.+?),\s*(P\s*O\s+Box.+)', text, re.DOTALL)

    if name_match:
        result['hospital_name'] = name_match.group(1).strip()
        remainder = name_match.group(2).strip()
        _parse_address_block(result, remainder)
    else:
        result['hospital_name'] = text

    return result


def _parse_address_block(result: dict, remainder: str) -> None:
    """Parse address, zip, telephone, contact, and web from remainder text."""
    # Zip code
    zip_match = re.search(r'Zip\s+(\d{5}(?:-\d{4})?)', remainder)
    if zip_match:
        result['zip_code'] = zip_match.group(1)

    # Address and state abbreviation
    addr_match = re.match(r'^(.+?),\s*([A-Z]{2}),\s*Zip', remainder)
    if addr_match:
        result['address'] = addr_match.group(1).strip().rstrip(',')
        result['state_abbrev'] = addr_match.group(2)
    else:
        addr_match2 = re.match(r'^(.+?),\s*Zip', remainder)
        if addr_match2:
            addr_text = addr_match2.group(1).strip()
            state_at_end = re.search(r',\s*([A-Z]{2})\s*$', addr_text)
            if state_at_end:
                result['state_abbrev'] = state_at_end.group(1)
                result['address'] = addr_text[:state_at_end.start()].strip().rstrip(',')
            else:
                result['address'] = addr_text

    # Telephone - handle numbers split across line breaks (e.g., "tel. 302/328- 3330")
    tel_match = re.search(r'tel\.\s*([\d/\-]+(?:\s+\d+)?)', remainder)
    if tel_match:
        phone = tel_match.group(1)
        # If phone ends with hyphen followed by space and digits, merge them
        phone = re.sub(r'-\s+(\d+)', r'-\1', phone)
        result['telephone'] = phone

    # Contact: after telephone, before "Web address"
    if tel_match:
        after_tel = remainder[tel_match.end():]
        after_tel = re.sub(r'^[,;\s]+', '', after_tel)
        # If the phone was truncated, the continuation digits may start the contact
        # Remove leading digits followed by comma (they were part of the phone number)
        if result['telephone'].endswith('-'):
            # Phone still truncated - try to grab continuation digits from after_tel
            digits_match = re.match(r'^(\d+)[,;\s]*(.*)', after_tel)
            if digits_match:
                result['telephone'] += digits_match.group(1)
                after_tel = digits_match.group(2).strip()
                after_tel = re.sub(r'^[,;\s]+', '', after_tel)
        web_split = re.split(r'\s*Web address\s*:', after_tel, maxsplit=1)
        contact_text = web_split[0].strip()
        if contact_text:
            result['contact'] = contact_text.rstrip('.')

    # Web address
    web_match = re.search(r'Web address\s*:\s*(\S+)', remainder)
    if web_match:
        result['web_address'] = web_match.group(1).strip()


def build_entry(hdr: dict, addr: dict, result: dict) -> HospitalEntry:
    """Build a HospitalEntry from header, address, and parsed hospital data."""
    entry = HospitalEntry()
    entry.healthcare_system = hdr['name']
    entry.system_id = hdr['id']
    entry.system_type = hdr['type']
    entry.system_classification = addr.get('classification', '')
    entry.system_address = addr.get('address', '')
    entry.system_city = addr.get('city', '')
    entry.system_state = addr.get('state', '')
    entry.system_zip = addr.get('zip', '')
    entry.system_telephone = addr.get('telephone', '')
    entry.system_ceo = addr.get('ceo', '')
    entry.section = result.get('section', hdr.get('section', ''))
    entry.hospital_name = result.get('hospital_name', '')
    entry.ownership_type = result.get('ownership_type', '')
    entry.staffed_beds = result.get('staffed_beds', '')
    entry.address = result.get('address', '')
    entry.city = result.get('city', '')
    entry.state = result.get('state', '')
    entry.state_abbrev = result.get('state_abbrev', '')
    entry.zip_code = result.get('zip_code', '')
    entry.telephone = result.get('telephone', '')
    entry.contact = result.get('contact', '')
    entry.web_address = result.get('web_address', '')

    # Derive full state name from abbreviation if missing
    if not entry.state and entry.state_abbrev:
        entry.state = ABBREV_TO_STATE.get(entry.state_abbrev, '')

    return entry


def save_to_csv(entries: list[HospitalEntry], output_path: str) -> None:
    """Save hospital data to CSV file."""
    if not entries:
        print("No entries to save")
        return

    fieldnames = [
        'healthcare_system', 'system_id', 'system_type', 'system_classification',
        'system_address', 'system_city', 'system_state', 'system_zip',
        'system_telephone', 'system_ceo', 'section',
        'hospital_name', 'ownership_type', 'staffed_beds',
        'address', 'city', 'state', 'state_abbrev', 'zip_code',
        'telephone', 'contact', 'web_address',
    ]

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow(asdict(entry))

    print(f"Saved {len(entries)} hospital entries to {output_path}")


def save_to_json(entries: list[HospitalEntry], output_path: str) -> None:
    """Save hospital data to JSON file."""
    data = [asdict(e) for e in entries]
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    print(f"Saved {len(entries)} hospital entries to {output_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Extract hospital & healthcare system data from AHA Guide Section B PDF')
    parser.add_argument('pdf_path', help='Path to the Section B PDF file')
    parser.add_argument('--output', '-o', default='sectionb_hospitals', help='Output filename (without extension)')
    parser.add_argument('--format', '-f', choices=['csv', 'json', 'both'], default='both',
                       help='Output format (default: both)')

    args = parser.parse_args()

    print(f"Extracting data from {args.pdf_path}...")
    entries = extract_section_b(args.pdf_path)

    print(f"Found {len(entries)} hospital entries across healthcare systems/networks")

    systems_count = len(set(e.healthcare_system for e in entries if e.section == 'Systems'))
    networks_count = len(set(e.healthcare_system for e in entries if e.section == 'Networks'))
    print(f"  Systems: {systems_count} healthcare systems, {sum(1 for e in entries if e.section == 'Systems')} hospitals")
    print(f"  Networks: {networks_count} networks, {sum(1 for e in entries if e.section == 'Networks')} hospitals")

    if args.format in ('csv', 'both'):
        save_to_csv(entries, f"{args.output}.csv")

    if args.format in ('json', 'both'):
        save_to_json(entries, f"{args.output}.json")

    # Print sample
    if entries:
        print("\nSample extracted data:")
        seen_systems = set()
        count = 0
        for entry in entries:
            if entry.healthcare_system not in seen_systems and count < 3:
                seen_systems.add(entry.healthcare_system)
                count += 1
                print(f"\n  Healthcare System: {entry.healthcare_system}")
                print(f"  System ID: {entry.system_id}")
                print(f"  System Type: {entry.system_type}")
                print(f"  Classification: {entry.system_classification}")
                print(f"  Section: {entry.section}")
                print(f"  ---")
                print(f"  Hospital: {entry.hospital_name}")
                print(f"  Ownership: {entry.ownership_type}")
                print(f"  Beds: {entry.staffed_beds}")
                print(f"  Address: {entry.address}")
                print(f"  State: {entry.state} ({entry.state_abbrev})")
                print(f"  Zip: {entry.zip_code}")
                print(f"  Phone: {entry.telephone}")
                print(f"  Contact: {entry.contact}")
                print(f"  Web: {entry.web_address}")


if __name__ == '__main__':
    main()

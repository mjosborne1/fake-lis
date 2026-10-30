#!/usr/bin/env python3
"""
Load laboratory test result templates into SQLite database.
Reads TSV files from result_templates directory and populates the database.
"""

import sqlite3
import csv
from pathlib import Path


def parse_value(value):
    """
    Parse a value from TSV, handling empty strings and converting to appropriate type.
    """
    if not value or value.strip() == '':
        return None
    try:
        # Try to convert to float if it looks like a number
        return float(value)
    except ValueError:
        # Return as string if not a number
        return value


def parse_dps_value(value):
    """
    Parse a DPS (Decimal Places) value.
    Returns: integer (0-3) for numeric types, 'S' for string type, or None if invalid.
    """
    if not value or value.strip() == '':
        return None
    
    # Check if it's the string type indicator
    if value.strip().upper() == 'S':
        return 'S'
    
    try:
        return int(value)
    except ValueError:
        # Return None for non-integer, non-S values
        return None


def parse_age_range(age_string):
    """
    Parse age range string like '6574 ��dʲ 43829' into (age_from, age_upto) tuple.
    Returns (None, None) if parsing fails.
    """
    if not age_string or age_string.strip() == '':
        return (None, None)
    
    # Split by various potential separators (special characters, spaces, dashes, etc.)
    import re
    # Extract all numbers from the string
    numbers = re.findall(r'\d+', age_string)
    
    if len(numbers) >= 2:
        return (int(numbers[0]), int(numbers[1]))
    elif len(numbers) == 1:
        # Single number, treat as both from and to
        return (int(numbers[0]), int(numbers[0]))
    else:
        return (None, None)


def load_template_file(cursor, template_path):
    """
    Load a single template file into the database.
    
    Args:
        cursor: Database cursor
        template_path: Path to the template TSV file
    """
    print(f"Loading: {template_path.name}")
    
    with open(template_path, 'r', encoding='iso-8859-1') as file:
        # Read TSV file
        reader = csv.DictReader(file, delimiter='\t')
        
        records_loaded = 0
        for row in reader:
            # Skip empty rows
            if not any(row.values()):
                continue
            
            # Parse age range
            age_from, age_upto = parse_age_range(row.get('Age', ''))
            
            # Insert data
            cursor.execute('''
            INSERT INTO test_reference_ranges (
                report_local_code,
                report_local_display,
                report_loinc,
                report_sct,
                result_code,
                result_code_name,
                unit_of_measure,
                result_loinc,
                decimal_places,
                age_from,
                age_upto,
                low_value,
                high_value,
                male_low,
                male_high,
                female_low,
                female_high,
                pregnant_low,
                pregnant_high
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                row['Report_LOCAL_Code'],
                row['Report_LOCAL_Display'],
                row['Report_LOINC'] or None,
                row['Report_SCT'] or None,
                row['Result_Code'],
                row['Result_Code_Name'],
                row['UofM'] or None,
                row['Result_LOINC'] or None,
                parse_dps_value(row.get('DPS')),
                age_from,
                age_upto,
                parse_value(row.get('Low')),
                parse_value(row.get('High')),
                parse_value(row.get('Male_Low')),
                parse_value(row.get('Male_High')),
                parse_value(row.get('Female_Low')),
                parse_value(row.get('Female_High')),
                parse_value(row.get('Pregnant_Low')),
                parse_value(row.get('Pregnant_High'))
            ))
            records_loaded += 1
    
    print(f"  ✓ Loaded {records_loaded} records")
    return records_loaded


def load_all_templates(db_path='lis_results.db', templates_dir='result_templates'):
    """
    Load all template files from the templates directory into the database.
    
    Args:
        db_path: Path to the SQLite database
        templates_dir: Directory containing template TSV files
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    templates_path = Path(templates_dir)
    template_files = list(templates_path.glob('*.txt'))
    
    if not template_files:
        print(f"No template files found in {templates_dir}/")
        return
    
    print(f"Found {len(template_files)} template file(s)")
    print("-" * 50)
    
    total_records = 0
    for template_file in sorted(template_files):
        records = load_template_file(cursor, template_file)
        total_records += records
    
    conn.commit()
    
    # Display summary
    print("-" * 50)
    print(f"Total records loaded: {total_records}")
    
    cursor.execute('SELECT COUNT(*) FROM test_reference_ranges')
    count = cursor.fetchone()[0]
    print(f"Records in database: {count}")
    
    cursor.execute('SELECT COUNT(DISTINCT report_local_code) FROM test_reference_ranges')
    test_types = cursor.fetchone()[0]
    print(f"Unique test types: {test_types}")
    
    conn.close()
    print(f"\nDatabase updated: {db_path}")


if __name__ == '__main__':
    load_all_templates()

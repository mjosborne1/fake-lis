#!/usr/bin/env python3
"""
Create SQLite database for Laboratory Information System (LIS) test results.
This script creates the database schema for storing laboratory test reference ranges.
"""

import sqlite3
from pathlib import Path

import credentials
import order_entry


def create_database(db_path='lis_results.db'):
    """
    Create the SQLite database and schema.
    
    Args:
        db_path: Path to the SQLite database file
    """
    # Remove existing database if it exists
    db_file = Path(db_path)
    if db_file.exists():
        print(f"Removing existing database: {db_path}")
        db_file.unlink()
    
    # Create connection and database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create main table for test results and reference ranges
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS test_reference_ranges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_local_code TEXT NOT NULL,
        report_local_display TEXT NOT NULL,
        report_loinc TEXT,
        report_sct TEXT,
        result_code TEXT NOT NULL,
        result_code_name TEXT NOT NULL,
        unit_of_measure TEXT,
        result_loinc TEXT,
        decimal_places TEXT,
        age_from INTEGER,
        age_upto INTEGER,
        low_value REAL,
        high_value REAL,
        male_low REAL,
        male_high REAL,
        female_low REAL,
        female_high REAL,
        pregnant_low REAL,
        pregnant_high REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create indexes for common queries
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_report_code 
    ON test_reference_ranges(report_local_code)
    ''')
    
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_result_code 
    ON test_reference_ranges(result_code)
    ''')
    
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_result_loinc 
    ON test_reference_ranges(result_loinc)
    ''')
    
    # Create a view for easier querying
    cursor.execute('''
    CREATE VIEW IF NOT EXISTS test_summary AS
    SELECT DISTINCT 
        report_local_code,
        report_local_display,
        result_code,
        result_code_name,
        unit_of_measure,
        result_loinc
    FROM test_reference_ranges
    ORDER BY report_local_code, result_code
    ''')
    
    # Create report format tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS report_formats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        test_type TEXT NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS report_format_sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        format_id INTEGER NOT NULL,
        section_name TEXT NOT NULL,
        section_order INTEGER NOT NULL,
        FOREIGN KEY (format_id) REFERENCES report_formats(id) ON DELETE CASCADE,
        UNIQUE(format_id, section_order)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS report_format_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section_id INTEGER NOT NULL,
        item_type TEXT NOT NULL,
        item_order INTEGER NOT NULL,
        result_code TEXT,
        custom_text TEXT,
        FOREIGN KEY (section_id) REFERENCES report_format_sections(id) ON DELETE CASCADE
    )
    ''')
    
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_format_test_type 
    ON report_formats(test_type)
    ''')
    
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_section_format 
    ON report_format_sections(format_id)
    ''')
    
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_item_section 
    ON report_format_items(section_id)
    ''')
    
    conn.commit()

    # Service requests received through the order entry facade
    order_entry.ensure_schema(conn)
    credentials.ensure_schema(conn)

    print(f"Database created successfully: {db_path}")
    print(f"  - Table: test_reference_ranges")
    print(f"  - Indexes: idx_report_code, idx_result_code, idx_result_loinc")
    print(f"  - View: test_summary")
    print(f"  - Tables: report_formats, report_format_sections, report_format_items")
    print(f"  - Indexes: idx_format_test_type, idx_section_format, idx_item_section")
    print(f"  - Table: service_requests")
    print(f"  - Table: credentials")
    
    conn.close()


if __name__ == '__main__':
    create_database()

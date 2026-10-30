#!/usr/bin/env python3
"""
Example queries for the Laboratory Information System database.
Demonstrates how to query test reference ranges.
"""

import sqlite3
from pathlib import Path


def connect_db(db_path='lis_results.db'):
    """Connect to the database."""
    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        print("Please run create_database.py and load_data.py first.")
        return None
    return sqlite3.connect(db_path)


def get_all_test_types(conn):
    """Get all available test types."""
    cursor = conn.cursor()
    cursor.execute('''
    SELECT DISTINCT report_local_code, report_local_display
    FROM test_reference_ranges
    ORDER BY report_local_code
    ''')
    return cursor.fetchall()


def get_test_components(conn, test_code):
    """Get all components/results for a specific test."""
    cursor = conn.cursor()
    cursor.execute('''
    SELECT DISTINCT 
        result_code,
        result_code_name,
        unit_of_measure,
        result_loinc
    FROM test_reference_ranges
    WHERE report_local_code = ?
    ORDER BY result_code
    ''', (test_code,))
    return cursor.fetchall()


def get_reference_range(conn, test_code, result_code, age_days=None, gender=None, is_pregnant=False):
    """
    Get reference range for a specific test result.
    
    Args:
        conn: Database connection
        test_code: Report local code (e.g., 'CBC', 'ELF')
        result_code: Result code (e.g., 'WBC', 'NaS')
        age_days: Patient age in days (optional)
        gender: 'M' or 'F' (optional)
        is_pregnant: Boolean for pregnancy status
    """
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        result_code_name,
        unit_of_measure,
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
    FROM test_reference_ranges
    WHERE report_local_code = ? AND result_code = ?
    '''
    
    # Add age filtering if provided
    if age_days is not None:
        query += ' AND (age_from IS NULL OR age_from <= ?) AND (age_upto IS NULL OR age_upto >= ?)'
        cursor.execute(query, (test_code, result_code, age_days, age_days))
    else:
        cursor.execute(query, (test_code, result_code))
    
    results = cursor.fetchall()
    
    # Find the most appropriate reference range
    for row in results:
        age_range_str = None
        if row[2] is not None or row[3] is not None:  # age_from or age_upto
            age_from = row[2] if row[2] is not None else 0
            age_upto = row[3] if row[3] is not None else '∞'
            age_range_str = f"{age_from} - {age_upto} days"
        
        if is_pregnant and row[10] is not None:  # pregnant_low
            return {
                'name': row[0],
                'unit': row[1],
                'age_range': age_range_str,
                'low': row[10],
                'high': row[11],
                'category': 'Pregnant'
            }
        elif gender == 'M' and row[6] is not None:  # male_low
            return {
                'name': row[0],
                'unit': row[1],
                'age_range': age_range_str,
                'low': row[6],
                'high': row[7],
                'category': 'Male'
            }
        elif gender == 'F' and row[8] is not None:  # female_low
            return {
                'name': row[0],
                'unit': row[1],
                'age_range': age_range_str,
                'low': row[8],
                'high': row[9],
                'category': 'Female'
            }
        elif row[4] is not None:  # low_value (general)
            return {
                'name': row[0],
                'unit': row[1],
                'age_range': age_range_str,
                'low': row[4],
                'high': row[5],
                'category': 'General'
            }
    
    return None


def main():
    """Run example queries."""
    conn = connect_db()
    if not conn:
        return
    
    print("=" * 70)
    print("Laboratory Information System - Example Queries")
    print("=" * 70)
    
    # Example 1: List all test types
    print("\n1. Available Test Types:")
    print("-" * 70)
    tests = get_all_test_types(conn)
    for code, display in tests:
        print(f"  {code}: {display}")
    
    # Example 2: Get components of CBC test
    print("\n2. Components of CBC (Full Blood Count):")
    print("-" * 70)
    components = get_test_components(conn, 'CBC')
    for code, name, unit, loinc in components:
        unit_str = f" ({unit})" if unit else ""
        loinc_str = f" [LOINC: {loinc}]" if loinc else ""
        print(f"  {code}: {name}{unit_str}{loinc_str}")
    
    # Example 3: Get reference range for WBC
    print("\n3. Reference Range for WBC (White Blood Cells):")
    print("-" * 70)
    ref_range = get_reference_range(conn, 'CBC', 'WBC', age_days=10000)
    if ref_range:
        print(f"  Test: {ref_range['name']}")
        print(f"  Unit: {ref_range['unit']}")
        print(f"  Range: {ref_range['low']} - {ref_range['high']} ({ref_range['category']})")
        if ref_range['age_range']:
            print(f"  Age Range: {ref_range['age_range']}")
    
    # Example 4: Get gender-specific reference range for Haemoglobin
    print("\n4. Gender-Specific Reference Range for Haemoglobin:")
    print("-" * 70)
    
    male_ref = get_reference_range(conn, 'CBC', 'HEB', gender='M', age_days=10000)
    if male_ref:
        print(f"  Male: {male_ref['low']} - {male_ref['high']} {male_ref['unit']}")
    
    female_ref = get_reference_range(conn, 'CBC', 'HEB', gender='F', age_days=10000)
    if female_ref:
        print(f"  Female: {female_ref['low']} - {female_ref['high']} {female_ref['unit']}")
    
    # Example 5: Search by LOINC code
    print("\n5. Find Test by LOINC Code (6690-2 - WBC):")
    print("-" * 70)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT report_local_code, result_code, result_code_name, unit_of_measure
    FROM test_reference_ranges
    WHERE result_loinc = ?
    LIMIT 1
    ''', ('6690-2',))
    result = cursor.fetchone()
    if result:
        print(f"  Test: {result[0]} / {result[1]}")
        print(f"  Name: {result[2]}")
        print(f"  Unit: {result[3]}")
    
    # Example 6: Database statistics
    print("\n6. Age-Based Reference Ranges for Potassium:")
    print("-" * 70)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT age_from, age_upto, low_value, high_value, unit_of_measure
    FROM test_reference_ranges
    WHERE result_code = 'KKS' AND low_value IS NOT NULL
    ORDER BY age_from
    ''')
    results = cursor.fetchall()
    if results:
        for age_from, age_upto, low, high, unit in results:
            age_str = f"{age_from if age_from else 0} - {age_upto if age_upto else '∞'} days"
            years_from = (age_from / 365.25) if age_from else 0
            years_to = (age_upto / 365.25) if age_upto else float('inf')
            years_str = f"({years_from:.1f} - {years_to:.1f} years)" if years_to != float('inf') else f"({years_from:.1f}+ years)"
            print(f"  {age_str:30} {years_str:25} {low} - {high} {unit}")
    
    # Example 7: Database statistics
    print("\n7. Database Statistics:")
    print("-" * 70)
    cursor.execute('SELECT COUNT(*) FROM test_reference_ranges')
    total = cursor.fetchone()[0]
    print(f"  Total reference ranges: {total}")
    
    cursor.execute('SELECT COUNT(DISTINCT report_local_code) FROM test_reference_ranges')
    tests = cursor.fetchone()[0]
    print(f"  Unique test types: {tests}")
    
    cursor.execute('SELECT COUNT(DISTINCT result_code) FROM test_reference_ranges')
    components = cursor.fetchone()[0]
    print(f"  Unique test components: {components}")
    
    print("\n" + "=" * 70)
    conn.close()


if __name__ == '__main__':
    main()

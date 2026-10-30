#!/usr/bin/env python3
"""
Example: Query reference ranges by patient age.
Demonstrates how to use age_from and age_upto columns.
"""

import sqlite3


def get_reference_for_patient(db_path, test_code, result_code, age_days, gender=None):
    """
    Get the appropriate reference range for a patient based on age and gender.
    
    Args:
        db_path: Path to the database
        test_code: Test code (e.g., 'CBC', 'ELF')
        result_code: Result code (e.g., 'WBC', 'KKS')
        age_days: Patient age in days
        gender: 'M' for male, 'F' for female, None for general
    
    Returns:
        Dictionary with reference range information
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Query for age-appropriate reference range
    cursor.execute('''
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
            female_high
        FROM test_reference_ranges
        WHERE report_local_code = ?
          AND result_code = ?
          AND (age_from IS NULL OR age_from <= ?)
          AND (age_upto IS NULL OR age_upto >= ?)
        LIMIT 1
    ''', (test_code, result_code, age_days, age_days))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return None
    
    # Determine which range to use based on gender
    low, high = None, None
    range_type = "General"
    
    if gender == 'M' and result[6] is not None:
        low, high = result[6], result[7]
        range_type = "Male"
    elif gender == 'F' and result[8] is not None:
        low, high = result[8], result[9]
        range_type = "Female"
    elif result[4] is not None:
        low, high = result[4], result[5]
        range_type = "General"
    
    return {
        'test_name': result[0],
        'unit': result[1],
        'age_from_days': result[2],
        'age_upto_days': result[3],
        'age_from_years': round(result[2] / 365.25, 1) if result[2] else None,
        'age_upto_years': round(result[3] / 365.25, 1) if result[3] else None,
        'low': low,
        'high': high,
        'range_type': range_type
    }


def years_to_days(years):
    """Convert years to days."""
    return int(years * 365.25)


def main():
    """Run example queries for different patient ages."""
    
    print("=" * 70)
    print("Reference Ranges by Patient Age")
    print("=" * 70)
    
    # Test cases: different ages and genders
    patients = [
        {'name': 'Newborn (3 days)', 'age_days': 3, 'gender': None},
        {'name': '6-month-old baby', 'age_days': years_to_days(0.5), 'gender': None},
        {'name': '5-year-old child', 'age_days': years_to_days(5), 'gender': None},
        {'name': '10-year-old boy', 'age_days': years_to_days(10), 'gender': 'M'},
        {'name': '10-year-old girl', 'age_days': years_to_days(10), 'gender': 'F'},
        {'name': '25-year-old man', 'age_days': years_to_days(25), 'gender': 'M'},
        {'name': '25-year-old woman', 'age_days': years_to_days(25), 'gender': 'F'},
        {'name': '70-year-old adult', 'age_days': years_to_days(70), 'gender': None},
    ]
    
    # Test for Potassium (has age-specific ranges)
    print("\n1. Potassium (KKS) Reference Ranges")
    print("-" * 70)
    for patient in patients:
        ref = get_reference_for_patient(
            'lis_results.db', 'ELF', 'KKS', 
            patient['age_days'], patient['gender']
        )
        if ref:
            gender_str = f" ({ref['range_type']})" if patient['gender'] else ""
            age_range = f"[{ref['age_from_years']}-{ref['age_upto_years']} years]"
            print(f"  {patient['name']:25} {age_range:20} {ref['low']} - {ref['high']} {ref['unit']}{gender_str}")
    
    # Test for Haemoglobin (has gender-specific ranges)
    print("\n2. Haemoglobin (HEB) Reference Ranges")
    print("-" * 70)
    for patient in patients:
        ref = get_reference_for_patient(
            'lis_results.db', 'CBC', 'HEB', 
            patient['age_days'], patient['gender']
        )
        if ref:
            gender_str = f" ({ref['range_type']})" if patient['gender'] else ""
            age_range = f"[{ref['age_from_years']}-{ref['age_upto_years']} years]"
            print(f"  {patient['name']:25} {age_range:20} {ref['low']} - {ref['high']} {ref['unit']}{gender_str}")
    
    # Test for Creatinine (has both age and gender-specific ranges)
    print("\n3. Creatinine (CRS) Reference Ranges")
    print("-" * 70)
    for patient in patients[:6]:  # Just show a few examples
        ref = get_reference_for_patient(
            'lis_results.db', 'ELF', 'CRS', 
            patient['age_days'], patient['gender']
        )
        if ref:
            gender_str = f" ({ref['range_type']})" if patient['gender'] else ""
            age_range = f"[{ref['age_from_years']}-{ref['age_upto_years']} years]"
            print(f"  {patient['name']:25} {age_range:20} {ref['low']} - {ref['high']} {ref['unit']}{gender_str}")
    
    print("\n" + "=" * 70)


if __name__ == '__main__':
    main()

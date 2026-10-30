# 50 Cent LIS - Laboratory Information System Database

A SQLite database for storing and querying laboratory test reference ranges with a modern web interface.

## Overview

This project provides a local SQLite database for laboratory test results with reference ranges that vary by age, gender, and pregnancy status. The data is loaded from TSV template files containing clinical chemistry and hematology test parameters.

**Features:**
- 🔬 SQLite database for lab test reference ranges
- 🌐 Flask + HTMX web interface for easy browsing
- 🔍 Real-time search functionality
- 📊 Age, gender, and pregnancy-specific reference ranges
- 🎨 Modern, responsive UI design
- 📨 HL7 v2 order entry facade (ORM^O01 / OML^O21 over HTTP or MLLP)
- 🧾 Service Request viewer with FHIR ServiceRequest rendering

## Database Schema

The database contains:
- **Table**: `test_reference_ranges` - Stores all test reference ranges with age/gender-specific values
- **View**: `test_summary` - Simplified view of unique test types and components
- **Indexes**: On report codes, result codes, and LOINC codes for fast queries

### Fields
- Report information (local codes, LOINC, SNOMED CT)
- Result codes and names
- Units of measure
- Age ranges (age_from and age_upto in days)
- Gender-specific ranges (male/female)
- Pregnancy-specific ranges
- Decimal places for result precision

## Setup and Usage

### Installation

```bash
# Optional: Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies (only Flask is required)
pip install -r requirements.txt
```

### 1. Create the Database

```bash
python create_database.py
```

This creates `lis_results.db` with the schema.

### 2. Load Template Data

```bash
python load_data.py
```

This loads all TSV files from the `result_templates/` directory into the database.

### 3. Run the Web Application

```bash
python app.py
```

Then open your browser to: **http://127.0.0.1:5000**

The web interface provides:
- 🔍 Real-time search for laboratory tests
- 📋 Browse all available tests
- 📊 View detailed reference ranges with age/gender/pregnancy specifics
- 📈 Database statistics

### 4. Order Entry Facade (HL7 v2)

The LIS accepts laboratory orders as HL7 v2 `ORM^O01` or `OML^O21` messages, parsed with the
[`hl7`](https://python-hl7.readthedocs.io/) package. Each `OBR` becomes a service request.

- `ORC-1` order control: `NW` creates an order; `CA`, `OC` and `DC` revoke one
- `ORC-2` / `OBR-2` placer order number (required); the LIS assigns a filler number
- `OBR-4.1` test code must match a catalogue `Report_LOCAL_Code`, `Report_LOINC` or `Report_SCT`
- Priority comes from `TQ1-9`, `OBR-27.6` or `ORC-7.6` (`S` stat, `A` asap, `R` routine)
- Unknown tests, duplicates and cancels of unknown orders get `MSA|AE`; unsupported messages get `MSA|AR`

**Over HTTP** (served by `app.py`):

```bash
printf 'MSH|^~\\&|EMR|HOSP|FAKE-LIS|LAB|20261030120000||ORM^O01|MSG1|P|2.5\rPID|1||MRN1||Doe^Jane||19800101|F\rORC|NW|PO-1\rOBR|1|PO-1||CBC^Full Blood Count^L' \
  | curl -s --data-binary @- http://127.0.0.1:5000/hl7/orders | tr '\r' '\n'
```

**Over MLLP** (separate process, default port 2575):

```bash
python mllp_listener.py --port 2575
```

**Test harness** — send local message files (`.orm`, `.oml`, `.hl7`, `.txt`) and check the ACKs:

```bash
python send_orm.py v2-examples/0001.orm            # one file, prints the ACK
python send_orm.py v2-examples/ -q                 # every message file in a directory
python send_orm.py v2-examples/0001.orm --fresh-ids   # new MSH-10 and placer numbers, so it can be resent
python send_orm.py v2-examples/0001.orm --mllp 127.0.0.1:2575
```

Exits non-zero if any message is not accepted (`MSA|AA`), so it can be used in scripts.

**Viewer and FHIR:**
- `/orders` lists service requests (live refresh, search, status filter), with a detail page showing the
  FHIR ServiceRequest and the original HL7 message, plus a cancel button
- `/orders/new` places an order from a form, or sends a pasted raw HL7 message, and shows the ACK
- `GET /fhir/ServiceRequest/<id>` and `GET /fhir/ServiceRequest?status=&patient=` return FHIR R4 JSON

The `service_requests` table is created automatically by `create_database.py` and on `app.py` startup.

### Deploying to Render

`render.yaml` defines a web service that runs the app under gunicorn. Push the repo to GitHub, then in Render
choose **New > Blueprint** and select the repo. Orders are then posted to:

```bash
python send_orm.py v2-examples/0001.orm --url https://<service>.onrender.com/hl7/orders
```

- The database path comes from `LIS_DATABASE` (default `lis_results.db`). If the file does not exist, the app
  builds it from `result_templates/` on startup.
- The blueprint puts the database on a persistent disk at `/var/data`, which needs a paid instance. On the free
  plan, drop the disk; the database is rebuilt on each restart and orders are lost.
- Render exposes HTTPS only, so orders must be sent by HTTP POST; the MLLP listener is for local use.

### 5. Run Example Queries (Optional)

```bash
python example_queries.py
python query_by_age.py
```

This demonstrates various ways to query the database programmatically.

## Quick Start (One Command)

```bash
python create_database.py && python load_data.py && python example_queries.py
```

## Template File Format

Template files are tab-separated (TSV) with these columns:
- `Report_LOCAL_Code` - Local test code (e.g., CBC, ELF)
- `Report_LOCAL_Display` - Display name
- `Report_LOINC` - LOINC code for the report
- `Report_SCT` - SNOMED CT code
- `Result_Code` - Individual result code
- `Result_Code_Name` - Result display name
- `UofM` - Unit of measure
- `Result_LOINC` - LOINC code for the result
- `DPS` - Decimal places
- `Age` - Age range in days (parsed into age_from and age_upto columns)
  - Format: "6574 ≤ to ≤ 43829" (18 years to 120 years)
  - Parsed automatically by the loader
- `Low`, `High` - General reference range
- `Male_Low`, `Male_High` - Male-specific range
- `Female_Low`, `Female_High` - Female-specific range
- `Pregnant_Low`, `Pregnant_High` - Pregnancy-specific range

**Note**: The Age column in templates contains ranges like "6574 ≤ to ≤ 43829" representing age in days. The loader automatically parses these into separate `age_from` (6574) and `age_upto` (43829) columns in the database.

## Example Queries

### Python API

```python
import sqlite3

conn = sqlite3.connect('lis_results.db')
cursor = conn.cursor()

# Get reference range for WBC (White Blood Cells)
cursor.execute('''
    SELECT result_code_name, unit_of_measure, low_value, high_value
    FROM test_reference_ranges
    WHERE report_local_code = 'CBC' AND result_code = 'WBC'
    LIMIT 1
''')
result = cursor.fetchone()
print(f"{result[0]}: {result[2]} - {result[3]} {result[1]}")

# Get age-appropriate reference range for a 5-year-old (1826 days)
patient_age_days = 1826  # 5 years
cursor.execute('''
    SELECT result_code_name, low_value, high_value, unit_of_measure
    FROM test_reference_ranges
    WHERE result_code = 'KKS'  -- Potassium
      AND age_from <= ?
      AND age_upto >= ?
''', (patient_age_days, patient_age_days))
result = cursor.fetchone()
print(f"Potassium for 5-year-old: {result[1]} - {result[2]} {result[3]}")

# Get all components of Full Blood Count
cursor.execute('''
    SELECT DISTINCT result_code, result_code_name, unit_of_measure
  Flask 3.0+ (for web interface)
- SQLite3 (included with Python)

Install Flask: `pip install -r requirements.txt`
''')
for code, name, unit in cursor.fetchall():
    print(f"{code}: {name} ({unit})")

conn.close()
```

### Command-Line Queries

```bash
# View all data
sqlite3 lis_results.db "SELECT * FROM test_reference_ranges LIMIT 10;"

# Get test summary
sqlite3 lis_results.db "SELECT * FROM test_summary;"

# Count records
sqlite3 lis_results.db "SELECT COUNT(*) FROM test_reference_ranges;"
```

## Requirements

- Python 3.6+
- SQLite3 (included with Python)

No external dependencies required!

## File Structure

```
fakeapp.py                  # Flask web application
├── create_database.py      # Creates the database schema
├── load_data.py            # Loads template data into database
├── example_queries.py      # Example usage and queries
├── query_by_age.py         # Query by patient age examples
├── order_entry.py          # HL7 v2 order entry facade (parse, store, ACK, FHIR mapping)
├── mllp_listener.py        # MLLP listener for HL7 v2 orders
├── requirements.txt        # Python dependencies
├── lis_results.db          # SQLite database (created by scripts)
├── templates/              # HTML templates for web app
│   ├── base.html
│   ├── index.html
│   ├── search_results.html
│   ├── report_details.html
│   └── stats.html
├── static/                 # Static assets (CSS)
│   └── css/
│       └── style.css
├── lis_results.db          # SQLite database (created by scripts)
└── result_templates/       # TSV template files
    ├── CBC_FullBloodCount.txt
    └── ELFT_GeneralChemistry.txt
```

## Use Cases

- **Clinical decision support**: Retrieve age/gender-specific reference ranges
- **Laboratory systems**: Mock LIS data for testing
- **Medical applications**: Validate test results against reference ranges
- **Education**: Learn about laboratory test parameters and reference ranges

## Notes

- Age ranges are stored in two INTEGER columns: `age_from` and `age_upto` (in days)
  - Example: age_from=6574, age_upto=43829 represents ages 18-120 years
  - To convert to years: divide by 365.25
  - Query by patient age: `WHERE age_from <= patient_days AND age_upto >= patient_days`
- Reference ranges can be general, gender-specific, or pregnancy-specific
- LOINC and SNOMED CT codes are included for standardization
- The database is recreated fresh each time you run `create_database.py`

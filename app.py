#!/usr/bin/env python3
"""
Flask web application for browsing laboratory test reference ranges.
Uses HTMX for dynamic content loading.
"""

from flask import Flask, render_template, request, jsonify, redirect, Response
import hmac
import os
import sqlite3
from pathlib import Path

import credentials
import order_entry
from create_database import create_database
from load_data import load_all_templates


app = Flask(__name__)
app.config['DATABASE'] = os.environ.get('LIS_DATABASE', 'lis_results.db')
# Owner's bearer token: manages credentials and can also send orders.
# If unset, the credentials page is locked and only issued tokens can send orders.
app.config['ADMIN_TOKEN'] = os.environ.get('LIS_ADMIN_TOKEN', '')


def get_db():
    """Get database connection."""
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db


def init_db():
    """Build the database from the templates if missing, and ensure the order tables exist."""
    db_path = Path(app.config['DATABASE'])
    if not db_path.exists():
        print(f"Database not found, creating {db_path}")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        create_database(str(db_path))
        load_all_templates(str(db_path), str(Path(__file__).parent / 'result_templates'))

    db = get_db()
    order_entry.ensure_schema(db)
    credentials.ensure_schema(db)
    db.close()


init_db()


def format_age_range(age_from, age_upto):
    """Format age range in days to readable format with appropriate units."""
    if age_from is None and age_upto is None:
        return "All ages", None, None
    
    age_from_val = age_from if age_from is not None else 0
    age_upto_val = age_upto if age_upto is not None else None
    
    # Determine the best unit to display
    # If range is under 30 days, show days
    # If range is between 30 and 365 days, show months
    # Otherwise show years
    
    def format_age_component(days):
        if days is None:
            return None, None
        if days < 30:
            return days, "days"
        elif days < 365:  # < 1 year
            months = round(days / 30.44)
            return months, "months"
        else:
            years = int(round(days / 365.25))
            return years, "years"
    
    from_val, from_unit = format_age_component(age_from_val)
    to_val, to_unit = format_age_component(age_upto_val) if age_upto_val else (None, None)
    
    # Build display string
    if to_val is None:
        display = f"{from_val}+ {from_unit}"
    elif from_unit == to_unit:
        display = f"{from_val}-{to_val} {from_unit}"
    else:
        # Different units, show separately
        display = f"{from_val} {from_unit} - {to_val} {to_unit}"
    
    # Always include days in data attributes for tooltips
    days_display = f"{age_from_val}-{age_upto_val if age_upto_val else '∞'} days"
    
    return display, days_display, age_from_val


def format_value(value, dps):
    """
    Format a numeric value according to decimal places specification.
    
    Args:
        value: The numeric value to format
        dps: Decimal places (0-3) or 'S' for string
    
    Returns:
        Formatted string
    """
    if value is None:
        return '-'
    
    # Check if DPS indicates string type
    if dps == 'S' or (isinstance(dps, str) and dps.upper() == 'S'):
        return str(value)
    
    if dps is None:
        return str(value)
    
    try:
        dps_int = int(dps)
        if dps_int == 0:
            return f"{float(value):.0f}"
        elif dps_int == 1:
            return f"{float(value):.1f}"
        elif dps_int == 2:
            return f"{float(value):.2f}"
        elif dps_int == 3:
            return f"{float(value):.3f}"
        else:
            return str(value)
    except (ValueError, TypeError):
        return str(value)


def format_reference_range(row):
    """Format reference range based on available values and DPS."""
    ranges = []
    dps = row['decimal_places']
    
    # General range
    if row['low_value'] is not None or row['high_value'] is not None:
        low = format_value(row['low_value'], dps)
        high = format_value(row['high_value'], dps)
        ranges.append(('General', f"{low} - {high}"))
    
    # Male range
    if row['male_low'] is not None or row['male_high'] is not None:
        low = format_value(row['male_low'], dps)
        high = format_value(row['male_high'], dps)
        ranges.append(('Male', f"{low} - {high}"))
    
    # Female range
    if row['female_low'] is not None or row['female_high'] is not None:
        low = format_value(row['female_low'], dps)
        high = format_value(row['female_high'], dps)
        ranges.append(('Female', f"{low} - {high}"))
    
    # Pregnant range
    if row['pregnant_low'] is not None or row['pregnant_high'] is not None:
        low = format_value(row['pregnant_low'], dps)
        high = format_value(row['pregnant_high'], dps)
        ranges.append(('Pregnant', f"{low} - {high}"))
    
    return ranges


@app.route('/')
def index():
    """Main page."""
    db = get_db()
    
    # Get all available tests
    cursor = db.execute('''
        SELECT DISTINCT report_local_code, report_local_display
        FROM test_reference_ranges
        ORDER BY report_local_code
    ''')
    tests = cursor.fetchall()
    
    db.close()
    
    return render_template('index.html', tests=tests)


@app.route('/search')
def search():
    """Search for tests by code or display name."""
    query = request.args.get('q', '').strip()
    
    if not query:
        return render_template('search_results.html', results=[])
    
    db = get_db()
    
    # Search in both code and display name
    cursor = db.execute('''
        SELECT DISTINCT report_local_code, report_local_display
        FROM test_reference_ranges
        WHERE report_local_code LIKE ? OR report_local_display LIKE ?
        ORDER BY report_local_code
    ''', (f'%{query}%', f'%{query}%'))
    
    results = cursor.fetchall()
    db.close()
    
    return render_template('search_results.html', results=results)


@app.route('/report/<report_code>')
def report_details(report_code):
    """Get detailed information for a specific report."""
    db = get_db()
    
    # Get report header
    cursor = db.execute('''
        SELECT DISTINCT 
            report_local_code,
            report_local_display,
            report_loinc,
            report_sct
        FROM test_reference_ranges
        WHERE report_local_code = ?
        LIMIT 1
    ''', (report_code,))
    
    report = cursor.fetchone()
    
    if not report:
        db.close()
        return "Report not found", 404
    
    # Get all test components with their reference ranges
    cursor = db.execute('''
        SELECT 
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
        FROM test_reference_ranges
        WHERE report_local_code = ?
        ORDER BY result_code, age_from
    ''', (report_code,))
    
    components = cursor.fetchall()
    db.close()
    
    # Process components to include formatted data
    processed_components = []
    for comp in components:
        # Determine result type based on DPS
        dps_value = comp['decimal_places']
        # Check if DPS is 'S' (string type indicator)
        if dps_value is not None and str(dps_value).upper() == 'S':
            result_type = "String"
            dps_display = "S"
        elif dps_value is None:
            result_type = "Numeric"
            dps_display = ""
        else:
            result_type = "Numeric"
            dps_display = str(dps_value)
        
        # For string types, don't show age ranges or reference intervals
        if result_type == "String":
            age_display = "-"
            age_days_display = None
            reference_ranges = []
        else:
            age_display, age_days_display, age_from_val = format_age_range(comp['age_from'], comp['age_upto'])
            reference_ranges = format_reference_range(comp)
        
        processed_components.append({
            'result_code': comp['result_code'],
            'result_code_name': comp['result_code_name'],
            'unit_of_measure': comp['unit_of_measure'] or '',
            'result_loinc': comp['result_loinc'] or '',
            'decimal_places': dps_display,
            'result_type': result_type,
            'age_range': age_display,
            'age_range_days': age_days_display,
            'reference_ranges': reference_ranges
        })
    
    return render_template('report_details.html', 
                         report=report, 
                         components=processed_components)


@app.route('/stats')
def stats():
    """Get database statistics."""
    db = get_db()
    
    cursor = db.execute('SELECT COUNT(*) as count FROM test_reference_ranges')
    total_records = cursor.fetchone()['count']
    
    cursor = db.execute('SELECT COUNT(DISTINCT report_local_code) as count FROM test_reference_ranges')
    total_tests = cursor.fetchone()['count']
    
    cursor = db.execute('SELECT COUNT(DISTINCT result_code) as count FROM test_reference_ranges')
    total_components = cursor.fetchone()['count']
    
    db.close()
    
    return render_template('stats.html',
                         total_records=total_records,
                         total_tests=total_tests,
                         total_components=total_components)


def generate_fhir_narrative(format_obj, sections):
    """Generate a FHIR DiagnosticReport narrative from a format."""
    narrative = "<div xmlns=\"http://www.w3.org/1999/xhtml\">\n"
    
    # Use description as heading if available, otherwise use test type
    heading = format_obj.get('description') or format_obj['test_type']
    narrative += f"  <h2>{heading}</h2>\n"
    
    for section in sections:
        narrative += f"  <h3>{section['section_name']}</h3>\n"
        narrative += "  <ul>\n"
        for item in section.get('section_items', []):
            if item['item_type'] == 'component':
                narrative += f"    <li>{item.get('component_name', item['result_code'])}</li>\n"
            elif item['item_type'] == 'text':
                narrative += f"    <li>{item['custom_text']}</li>\n"
        narrative += "  </ul>\n"
    
    narrative += "</div>"
    return narrative


@app.route('/api/components/<test_type>')
def get_components_by_type(test_type):
    """Get components for a specific test type."""
    db = get_db()
    
    cursor = db.execute('''
        SELECT DISTINCT result_code, result_code_name
        FROM test_reference_ranges
        WHERE report_local_code = ?
        ORDER BY result_code
    ''', (test_type,))
    
    components = [dict(row) for row in cursor.fetchall()]
    db.close()
    
    return jsonify(components)


@app.route('/formats')
def list_formats():
    """List all report formats."""
    db = get_db()
    
    cursor = db.execute('''
        SELECT id, name, test_type, description, created_at
        FROM report_formats
        ORDER BY test_type, name
    ''')
    
    formats = cursor.fetchall()
    db.close()
    
    return render_template('format_list.html', formats=formats)


@app.route('/format/new', methods=['GET', 'POST'])
def create_format():
    """Create a new report format."""
    db = get_db()
    
    if request.method == 'POST':
        name = request.form.get('name')
        test_type = request.form.get('test_type')
        description = request.form.get('description')
        
        if not name or not test_type:
            db.close()
            return "Name and test type are required", 400
        
        try:
            cursor = db.execute('''
                INSERT INTO report_formats (name, test_type, description)
                VALUES (?, ?, ?)
            ''', (name, test_type, description))
            
            format_id = cursor.lastrowid
            
            # Process sections from form
            section_order = 0
            section_mapping = {}  # temp_id -> db_id
            
            # Parse form data for sections and items
            import json
            section_data = request.form.get('sections_data')
            if section_data:
                sections = json.loads(section_data)
                for section in sections:
                    section_order += 1
                    section_cursor = db.execute('''
                        INSERT INTO report_format_sections (format_id, section_name, section_order)
                        VALUES (?, ?, ?)
                    ''', (format_id, section['name'], section_order))
                    
                    section_id = section_cursor.lastrowid
                    
                    item_order = 0
                    for item in section.get('items', []):
                        item_order += 1
                        db.execute('''
                            INSERT INTO report_format_items (section_id, item_type, item_order, result_code, custom_text)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (section_id, item['type'], item_order, item.get('code'), item.get('text')))
            
            db.commit()
            db.close()
            return redirect('/formats')
        
        except Exception as e:
            db.rollback()
            db.close()
            return f"Error creating format: {str(e)}", 500
    
    # Get all test types for dropdown
    cursor = db.execute('''
        SELECT DISTINCT report_local_code
        FROM test_reference_ranges
        ORDER BY report_local_code
    ''')
    
    test_types = [row['report_local_code'] for row in cursor.fetchall()]
    
    # Get all available components for this test type
    cursor = db.execute('''
        SELECT DISTINCT result_code, result_code_name
        FROM test_reference_ranges
        ORDER BY result_code
    ''')
    
    all_components = cursor.fetchall()
    db.close()
    
    return render_template('format_builder.html', 
                         test_types=test_types,
                         all_components=all_components,
                         format=None,
                         sections=None)


@app.route('/format/<int:format_id>/edit', methods=['GET', 'POST'])
def edit_format(format_id):
    """Edit an existing report format."""
    db = get_db()
    
    # Get format
    cursor = db.execute('''
        SELECT id, name, test_type, description
        FROM report_formats
        WHERE id = ?
    ''', (format_id,))
    
    format_row = cursor.fetchone()
    
    if not format_row:
        db.close()
        return "Format not found", 404
    
    if request.method == 'POST':
        name = request.form.get('name')
        test_type = request.form.get('test_type')
        description = request.form.get('description')
        
        try:
            db.execute('''
                UPDATE report_formats
                SET name = ?, test_type = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (name, test_type, description, format_id))
            
            # Delete existing sections
            db.execute('DELETE FROM report_format_sections WHERE format_id = ?', (format_id,))
            
            # Add new sections
            import json
            section_data = request.form.get('sections_data')
            if section_data:
                sections = json.loads(section_data)
                for section_order, section in enumerate(sections, 1):
                    section_cursor = db.execute('''
                        INSERT INTO report_format_sections (format_id, section_name, section_order)
                        VALUES (?, ?, ?)
                    ''', (format_id, section['name'], section_order))
                    
                    section_id = section_cursor.lastrowid
                    
                    for item_order, item in enumerate(section.get('items', []), 1):
                        db.execute('''
                            INSERT INTO report_format_items (section_id, item_type, item_order, result_code, custom_text)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (section_id, item['type'], item_order, item.get('code'), item.get('text')))
            
            db.commit()
            db.close()
            return redirect('/formats')
        
        except Exception as e:
            db.rollback()
            db.close()
            return f"Error updating format: {str(e)}", 500
    
    # Get sections for this format
    cursor = db.execute('''
        SELECT id, section_name, section_order
        FROM report_format_sections
        WHERE format_id = ?
        ORDER BY section_order
    ''', (format_id,))
    
    sections = [dict(row) for row in cursor.fetchall()]
    
    # Get items for each section
    for section in sections:
        cursor = db.execute('''
            SELECT id, item_type, item_order, result_code, custom_text
            FROM report_format_items
            WHERE section_id = ?
            ORDER BY item_order
        ''', (section['id'],))
        section['section_items'] = [dict(row) for row in cursor.fetchall()]
    
    # Get test types
    cursor = db.execute('''
        SELECT DISTINCT report_local_code
        FROM test_reference_ranges
        ORDER BY report_local_code
    ''')
    
    test_types = [row['report_local_code'] for row in cursor.fetchall()]
    
    # Get all available components
    cursor = db.execute('''
        SELECT DISTINCT result_code, result_code_name
        FROM test_reference_ranges
        ORDER BY result_code
    ''')
    
    all_components = cursor.fetchall()
    db.close()
    
    return render_template('format_builder.html',
                         format=format_row,
                         sections=sections,
                         test_types=test_types,
                         all_components=all_components)


@app.route('/format/<int:format_id>/delete', methods=['POST'])
def delete_format(format_id):
    """Delete a report format."""
    db = get_db()
    
    db.execute('DELETE FROM report_formats WHERE id = ?', (format_id,))
    db.commit()
    db.close()
    
    return redirect('/formats')


@app.route('/format/<int:format_id>/preview')
def preview_format(format_id):
    """Generate a preview/narrative for a format."""
    db = get_db()
    
    # Get format
    cursor = db.execute('''
        SELECT id, name, test_type, description
        FROM report_formats
        WHERE id = ?
    ''', (format_id,))
    
    format_row = cursor.fetchone()
    
    if not format_row:
        db.close()
        return "Format not found", 404
    
    # Convert to dict for easier access
    format_row = dict(format_row)
    
    # Get sections with items
    cursor = db.execute('''
        SELECT id, section_name, section_order
        FROM report_format_sections
        WHERE format_id = ?
        ORDER BY section_order
    ''', (format_id,))
    
    sections = [dict(row) for row in cursor.fetchall()]
    
    # Get items for each section
    for section in sections:
        cursor = db.execute('''
            SELECT id, item_type, item_order, result_code, custom_text
            FROM report_format_items
            WHERE section_id = ?
            ORDER BY item_order
        ''', (section['id'],))
        section['section_items'] = [dict(row) for row in cursor.fetchall()]
        
        # Get component details
        for item in section['section_items']:
            if item['item_type'] == 'component':
                cursor = db.execute('''
                    SELECT result_code_name, unit_of_measure
                    FROM test_reference_ranges
                    WHERE result_code = ?
                    LIMIT 1
                ''', (item['result_code'],))
                comp_detail = cursor.fetchone()
                if comp_detail:
                    item['component_name'] = comp_detail['result_code_name']
                    item['unit'] = comp_detail['unit_of_measure']
    
    db.close()
    
    # Generate FHIR narrative
    fhir_narrative = generate_fhir_narrative(format_row, sections)
    
    return render_template('format_preview.html',
                         format=format_row,
                         sections=sections,
                         fhir_narrative=fhir_narrative)


# ---------------------------------------------------------------------------
# Order entry facade (HL7 v2) and Service Request viewer
# ---------------------------------------------------------------------------

HL7_MIMETYPE = 'x-application/hl7-v2+er7'
TOKEN_REQUIRED_MESSAGE = 'A bearer token is required to send orders. Contact the repo owner for a bearer token.'


def bearer_token():
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    return token.strip() if scheme.lower() == 'bearer' else ''


def is_admin():
    """True if the request carries the owner's admin token."""
    expected = app.config['ADMIN_TOKEN']
    return bool(expected) and hmac.compare_digest(bearer_token(), expected)


def has_order_token(db):
    """True if the request carries the admin token or an active issued credential."""
    return is_admin() or credentials.verify(db, bearer_token()) is not None


def token_required_response(message=TOKEN_REQUIRED_MESSAGE):
    return Response(message, 401, {'WWW-Authenticate': 'Bearer'}, mimetype='text/plain')


def query_service_requests(db, statuses=None, q=None, patient=None):
    """Fetch service requests with optional workflow status, free-text and patient filters."""
    sql = 'SELECT * FROM service_requests WHERE 1=1'
    params = []
    if statuses is not None:
        sql += f" AND status IN ({','.join('?' * len(statuses)) or 'NULL'})"
        params.extend(statuses)
    if patient:
        sql += ' AND patient_id = ?'
        params.append(patient)
    if q:
        sql += (' AND (placer_order_number LIKE ? OR filler_order_number LIKE ?'
                ' OR patient_id LIKE ? OR patient_family LIKE ? OR test_code LIKE ?)')
        params.extend([f'%{q}%'] * 5)
    sql += ' ORDER BY received_at DESC, id DESC'
    return db.execute(sql, params).fetchall()


def get_service_request(db, order_id):
    return db.execute('SELECT * FROM service_requests WHERE id = ?', (order_id,)).fetchone()


@app.route('/hl7/orders', methods=['POST'])
def hl7_order_endpoint():
    """HL7 v2 over HTTP: accept an ORM^O01 / OML^O21 body, return an ACK."""
    db = get_db()
    if not has_order_token(db):
        db.close()
        return token_required_response()
    ack, _ = order_entry.process_message(db, request.get_data(as_text=True))
    db.close()
    return Response(ack, mimetype=HL7_MIMETYPE)


@app.route('/orders')
def list_orders():
    """Service Request viewer."""
    return render_template('orders.html')


@app.route('/orders/table')
def orders_table():
    """HTMX fragment: filtered service request table."""
    db = get_db()
    status = request.args.get('status')
    rows = query_service_requests(db,
                                  statuses=[status] if status else None,
                                  q=request.args.get('q', '').strip() or None)
    db.close()
    return render_template('order_table.html', orders=rows, actions=order_entry.STATUS_ACTIONS)


@app.route('/orders/<int:order_id>')
def order_detail(order_id):
    """Show a single service request with its FHIR and HL7 representations."""
    db = get_db()
    row = get_service_request(db, order_id)
    db.close()
    if not row:
        return "Service request not found", 404
    return render_template('order_detail.html',
                           order=row,
                           actions=order_entry.STATUS_ACTIONS[row['status']],
                           fhir_json=order_entry.to_fhir_json(row),
                           raw_hl7=(row['raw_message'] or '').replace('\r', '\n'))


@app.route('/orders/<int:order_id>/status', methods=['POST'])
def change_order_status(order_id):
    """Accept, complete or cancel an order from the LIS side."""
    db = get_db()
    if not get_service_request(db, order_id):
        db.close()
        return "Service request not found", 404
    try:
        order_entry.change_status(db, order_id, request.form.get('status', ''))
        db.commit()
    except order_entry.OrderError as e:
        db.rollback()
        return str(e), 409
    finally:
        db.close()

    if request.headers.get('HX-Request'):
        # Table action: tell the viewer to refresh rather than navigate
        return '', 204, {'HX-Trigger': 'orders-changed'}
    return redirect(f'/orders/{order_id}')


@app.route('/orders/new', methods=['GET', 'POST'])
def new_order():
    """Order entry form. Builds an ORM^O01 (or takes raw HL7) and submits it through the facade."""
    if request.method == 'POST':
        db = get_db()
        if not has_order_token(db):
            db.close()
            return token_required_response()
        form = request.form
        message = form.get('raw_message', '').strip()
        if not message:
            message = order_entry.build_orm(
                {'id': form.get('patient_id', '').strip(),
                 'family': form.get('patient_family', '').strip(),
                 'given': form.get('patient_given', '').strip(),
                 'dob': form.get('patient_dob', ''),
                 'sex': form.get('patient_sex', '')},
                form.get('test_code', ''),
                form.get('test_display', ''),
                form.get('placer_order_number', '').strip(),
                priority=form.get('priority', 'R'),
                requester=form.get('requester', '').strip(),
                clinical_info=form.get('clinical_info', '').strip())

        ack, ids = order_entry.process_message(db, message)
        db.close()
        return render_template('order_ack.html',
                               sent=order_entry.normalise_message(message).replace('\r', '\n'),
                               ack=ack.replace('\r', '\n'),
                               accepted='MSA|AA' in ack,
                               ids=ids)

    db = get_db()
    tests = db.execute('''
        SELECT DISTINCT report_local_code, report_local_display
        FROM test_reference_ranges
        ORDER BY report_local_code
    ''').fetchall()
    db.close()
    return render_template('order_new.html', tests=tests)


# ---------------------------------------------------------------------------
# Credentials: bearer tokens issued per email address, managed with the admin token
# ---------------------------------------------------------------------------

ADMIN_REQUIRED_MESSAGE = 'The admin token is required to manage credentials. Contact the repo owner.'


@app.route('/credentials')
def credentials_page():
    return render_template('credentials.html')


@app.route('/credentials/table')
def credentials_table():
    """HTMX fragment: issued credentials."""
    if not is_admin():
        return token_required_response(ADMIN_REQUIRED_MESSAGE)
    db = get_db()
    rows = credentials.list_all(db)
    db.close()
    return render_template('credentials_table.html', credentials=rows)


@app.route('/credentials', methods=['POST'])
def create_credential():
    """Issue a token for an email address and show it once."""
    if not is_admin():
        return token_required_response(ADMIN_REQUIRED_MESSAGE)
    db = get_db()
    email = request.form.get('email', '')
    try:
        token = credentials.create(db, email)
    except credentials.CredentialError as e:
        return render_template('credential_created.html', error=str(e))
    finally:
        db.close()
    return (render_template('credential_created.html', email=email.strip().lower(), token=token),
            200, {'HX-Trigger': 'credentials-changed'})


@app.route('/credentials/<int:credential_id>/revoke', methods=['POST'])
def revoke_credential(credential_id):
    if not is_admin():
        return token_required_response(ADMIN_REQUIRED_MESSAGE)
    db = get_db()
    credentials.revoke(db, credential_id)
    db.close()
    return '', 204, {'HX-Trigger': 'credentials-changed'}


@app.route('/fhir/ServiceRequest/<int:order_id>')
def fhir_service_request(order_id):
    """FHIR read of a single ServiceRequest."""
    db = get_db()
    row = get_service_request(db, order_id)
    db.close()
    if not row:
        return jsonify({'resourceType': 'OperationOutcome', 'issue': [
            {'severity': 'error', 'code': 'not-found',
             'diagnostics': f'ServiceRequest/{order_id} not found'}]}), 404
    return Response(order_entry.to_fhir_json(row), mimetype='application/fhir+json')


@app.route('/fhir/ServiceRequest')
def fhir_service_request_search():
    """FHIR search for ServiceRequests by status and patient identifier."""
    # FHIR status values (comma separated) -> LIS workflow statuses
    fhir_statuses = [s for s in request.args.get('status', '').split(',') if s]
    statuses = None
    if fhir_statuses:
        statuses = [lis for lis, fhir in order_entry.FHIR_STATUS.items() if fhir in fhir_statuses]

    db = get_db()
    rows = query_service_requests(db,
                                  statuses=statuses,
                                  patient=request.args.get('patient') or None)
    db.close()
    bundle = {
        'resourceType': 'Bundle',
        'type': 'searchset',
        'total': len(rows),
        'entry': [{'fullUrl': f"{request.host_url}fhir/ServiceRequest/{row['id']}",
                   'resource': order_entry.to_fhir(row),
                   'search': {'mode': 'match'}} for row in rows],
    }
    return jsonify(bundle), 200, {'Content-Type': 'application/fhir+json'}


if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("Laboratory Information System - Web Interface")
    print("=" * 70)
    print("\nStarting server at http://127.0.0.1:5000")
    print("HL7 v2 order endpoint: POST http://127.0.0.1:5000/hl7/orders")
    print("Press CTRL+C to stop\n")
    
    app.run(debug=True, host='127.0.0.1', port=5000)

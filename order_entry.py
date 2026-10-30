#!/usr/bin/env python3
"""
HL7 v2 order entry facade for the 50 Cent LIS.

Accepts ORM^O01 / OML^O21 order messages, validates the ordered tests against
the test catalogue (test_reference_ranges), stores each OBR as a service
request and builds an HL7 ACK. Kept free of Flask so the MLLP listener can
reuse it.
"""

import json
import sqlite3
import uuid
from datetime import datetime

import hl7


SUPPORTED_MESSAGES = {'ORM^O01', 'OML^O21'}

# ORC-1 order control -> FHIR ServiceRequest.status
ORDER_CONTROL_STATUS = {
    'NW': 'active',
    'CA': 'revoked',
    'OC': 'revoked',
    'DC': 'revoked',
}

# OBR-27.6 / TQ1-9 priority -> FHIR ServiceRequest.priority
PRIORITY_MAP = {
    'S': 'stat',
    'A': 'asap',
    'R': 'routine',
    'T': 'urgent',
}

LOCAL_CODE_SYSTEM = 'http://fake-lis.example.org/CodeSystem/test-code'


class OrderError(Exception):
    """Raised when an order message is rejected."""

    def __init__(self, message, ack_code='AE'):
        super().__init__(message)
        self.ack_code = ack_code


def ensure_schema(db):
    """Create the service request table if it does not exist."""
    db.execute('''
    CREATE TABLE IF NOT EXISTS service_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        placer_order_number TEXT NOT NULL,
        filler_order_number TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'routine',
        test_code TEXT NOT NULL,
        test_display TEXT,
        test_loinc TEXT,
        patient_id TEXT,
        patient_family TEXT,
        patient_given TEXT,
        patient_dob TEXT,
        patient_sex TEXT,
        requester TEXT,
        clinical_info TEXT,
        authored_on TEXT,
        sending_application TEXT,
        sending_facility TEXT,
        message_control_id TEXT,
        message_type TEXT,
        raw_message TEXT,
        received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(placer_order_number, test_code)
    )
    ''')
    db.execute('''
    CREATE INDEX IF NOT EXISTS idx_sr_placer
    ON service_requests(placer_order_number)
    ''')
    db.execute('''
    CREATE INDEX IF NOT EXISTS idx_sr_patient
    ON service_requests(patient_id)
    ''')
    db.commit()


def normalise_message(text):
    """Strip MLLP framing and convert any line endings to HL7 segment separators."""
    text = text.strip().strip('\x0b\x1c')
    return '\r'.join(line for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n') if line.strip())


def _field(segment, field, component=1):
    """Return a field component from a non-MSH segment, or '' if absent."""
    if segment is None:
        return ''
    try:
        return segment.extract_field(field_num=field, component_num=component) or ''
    except (IndexError, KeyError):
        return ''


def _msg_field(message, path):
    """Return a value from the message by accessor path, or '' if absent."""
    try:
        return str(message[path] or '')
    except (IndexError, KeyError):
        return ''


def _hl7_datetime_to_iso(value):
    """Convert an HL7 TS (YYYYMMDD[HHMM[SS]]) to ISO 8601."""
    value = value.split('+')[0].split('-')[0].split('.')[0]
    for length, fmt, out in ((14, '%Y%m%d%H%M%S', '%Y-%m-%dT%H:%M:%S'),
                             (12, '%Y%m%d%H%M', '%Y-%m-%dT%H:%M'),
                             (8, '%Y%m%d', '%Y-%m-%d')):
        if len(value) >= length:
            try:
                return datetime.strptime(value[:length], fmt).strftime(out)
            except ValueError:
                continue
    return value or None


def _lookup_test(db, code):
    """Find a catalogue test by local report code, report LOINC or report SNOMED CT code."""
    return db.execute('''
        SELECT report_local_code, report_local_display, report_loinc
        FROM test_reference_ranges
        WHERE report_local_code = ? OR report_loinc = ? OR report_sct = ?
        LIMIT 1
    ''', (code, code, code)).fetchone()


def parse_orders(db, message):
    """
    Extract order requests from a parsed HL7 message.

    Walks segments in order so each OBR picks up the most recent ORC.
    Returns a list of dicts, one per OBR.
    """
    pid = None
    for segment in message:
        if str(segment[0]) == 'PID':
            pid = segment
            break
    if pid is None:
        raise OrderError('PID segment is required')

    patient = {
        'patient_id': _field(pid, 3, 1),
        'patient_family': _field(pid, 5, 1),
        'patient_given': _field(pid, 5, 2),
        'patient_dob': _hl7_datetime_to_iso(_field(pid, 7)),
        'patient_sex': _field(pid, 8),
    }
    if not patient['patient_id']:
        raise OrderError('PID-3 patient identifier is required')

    header = {
        'sending_application': _msg_field(message, 'MSH.F3.R1.C1'),
        'sending_facility': _msg_field(message, 'MSH.F4.R1.C1'),
        'message_control_id': _msg_field(message, 'MSH.F10'),
        'message_type': f"{_msg_field(message, 'MSH.F9.R1.C1')}^{_msg_field(message, 'MSH.F9.R1.C2')}",
    }

    orders = []
    orc = None
    tq1 = None
    for segment in message:
        name = str(segment[0])
        if name == 'ORC':
            orc, tq1 = segment, None
        elif name == 'TQ1':
            tq1 = segment
        elif name == 'OBR':
            control = _field(orc, 1) or 'NW'
            placer = _field(orc, 2) or _field(segment, 2)
            if not placer:
                raise OrderError('Placer order number (ORC-2 or OBR-2) is required')

            code = _field(segment, 4, 1)
            if not code:
                raise OrderError(f'OBR-4 universal service identifier is required for order {placer}')

            priority_code = _field(tq1, 9) or _field(segment, 27, 6) or _field(orc, 7, 6)

            requester_seg, requester_field = (orc, 12) if _field(orc, 12, 1) or _field(orc, 12, 2) else (segment, 16)
            requester = ' '.join(p for p in (
                _field(requester_seg, requester_field, 3),
                _field(requester_seg, requester_field, 2),
            ) if p) or _field(requester_seg, requester_field, 1)

            orders.append({
                **patient,
                **header,
                'order_control': control,
                'placer_order_number': placer,
                'requested_code': code,
                'requested_display': _field(segment, 4, 2),
                'priority': PRIORITY_MAP.get(priority_code.upper(), 'routine'),
                'requester': requester,
                'clinical_info': _field(segment, 13),
                'authored_on': _hl7_datetime_to_iso(_field(orc, 9) or _field(segment, 6) or _field(segment, 7)),
            })

    if not orders:
        raise OrderError('Message contains no OBR segments')
    return orders


def process_message(db, raw_text):
    """
    Process an inbound order message.

    Returns (ack_text, service_request_ids). Never raises for message-level
    problems; those are reported in the ACK.
    """
    text = normalise_message(raw_text)
    try:
        message = hl7.parse(text)
    except Exception as e:
        return build_error_ack(text, 'AR', f'Unable to parse message: {e}'), []

    msg_type = f"{_msg_field(message, 'MSH.F9.R1.C1')}^{_msg_field(message, 'MSH.F9.R1.C2')}"
    if msg_type not in SUPPORTED_MESSAGES:
        return make_ack(message, 'AR', f'Unsupported message type {msg_type}'), []

    try:
        orders = parse_orders(db, message)
        ids = []
        for order in orders:
            ids.append(_apply_order(db, order, text))
        db.commit()
    except OrderError as e:
        db.rollback()
        return make_ack(message, e.ack_code, str(e)), []

    return make_ack(message, 'AA'), ids


def _apply_order(db, order, raw_text):
    """Insert or update a single service request according to its order control."""
    control = order['order_control'].upper()
    if control not in ORDER_CONTROL_STATUS:
        raise OrderError(f'Unsupported order control {control}', 'AR')

    test = _lookup_test(db, order['requested_code'])
    if test is None:
        raise OrderError(f"Unknown test code {order['requested_code']}")

    if control == 'NW':
        try:
            cursor = db.execute('''
                INSERT INTO service_requests (
                    placer_order_number, filler_order_number, status, priority,
                    test_code, test_display, test_loinc,
                    patient_id, patient_family, patient_given, patient_dob, patient_sex,
                    requester, clinical_info, authored_on,
                    sending_application, sending_facility, message_control_id, message_type,
                    raw_message
                ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                order['placer_order_number'], f'LIS-{uuid.uuid4().hex[:8].upper()}', order['priority'],
                test['report_local_code'], test['report_local_display'], test['report_loinc'],
                order['patient_id'], order['patient_family'], order['patient_given'],
                order['patient_dob'], order['patient_sex'],
                order['requester'], order['clinical_info'], order['authored_on'],
                order['sending_application'], order['sending_facility'],
                order['message_control_id'], order['message_type'],
                raw_text,
            ))
        except sqlite3.IntegrityError:
            raise OrderError(
                f"Order {order['placer_order_number']} for {test['report_local_code']} already exists")
        return cursor.lastrowid

    # Cancel / discontinue an existing order
    row = db.execute('''
        SELECT id FROM service_requests
        WHERE placer_order_number = ? AND test_code = ?
    ''', (order['placer_order_number'], test['report_local_code'])).fetchone()
    if row is None:
        raise OrderError(
            f"Order {order['placer_order_number']} for {test['report_local_code']} not found")
    db.execute('''
        UPDATE service_requests
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (ORDER_CONTROL_STATUS[control], row['id']))
    return row['id']


def make_ack(message, ack_code, text=None):
    """Build an ACK for a parsed message, adding MSA-3 and ERR when rejecting."""
    ack = str(message.create_ack(ack_code=ack_code,
                                 message_id=f'ACK{uuid.uuid4().hex[:12].upper()}',
                                 application='FAKE-LIS',
                                 facility='LAB')).rstrip('\r')
    if text:
        text = _escape(text)
        ack += f'|{text}\rERR|||{"207" if ack_code == "AR" else "100"}^{text}^HL70357|E'
    return ack


def build_error_ack(text, ack_code, error):
    """Build a minimal ACK when the inbound message could not be parsed."""
    control_id = ''
    first = text.split('\r', 1)[0]
    if first.startswith('MSH'):
        fields = first.split(first[3:4] or '|')
        if len(fields) > 9:
            control_id = fields[9]
    now = datetime.now().strftime('%Y%m%d%H%M%S')
    error = _escape(error)
    return (f'MSH|^~\\&|FAKE-LIS|LAB|||{now}||ACK|ACK{uuid.uuid4().hex[:12].upper()}|P|2.5\r'
            f'MSA|{ack_code}|{control_id}|{error}\r'
            f'ERR|||102^{error}^HL70357|E')


def _escape(text):
    """Escape HL7 delimiters in free text."""
    return (text.replace('\\', '\\E\\').replace('|', '\\F\\').replace('^', '\\S\\')
            .replace('&', '\\T\\').replace('~', '\\R\\').replace('\r', ' ').replace('\n', ' '))


def build_orm(patient, test_code, test_display, placer_order_number,
              priority='R', requester='', clinical_info='', order_control='NW'):
    """Build an ORM^O01 message, used by the web order form."""
    now = datetime.now().strftime('%Y%m%d%H%M%S')
    segments = [
        f'MSH|^~\\&|FAKE-LIS-UI|WARD|FAKE-LIS|LAB|{now}||ORM^O01|{uuid.uuid4().hex[:12].upper()}|P|2.5',
        f"PID|1||{patient['id']}^^^HOSP^MR||{patient.get('family', '')}^{patient.get('given', '')}"
        f"||{patient.get('dob', '').replace('-', '')}|{patient.get('sex', '')}",
        f'ORC|{order_control}|{placer_order_number}|||||^^^^^{priority}||{now}|||{requester}',
        f'OBR|1|{placer_order_number}||{test_code}^{test_display}^L|||{now}||||||{_escape(clinical_info)}'
        f'|||{requester}|||||||||||^^^^^{priority}',
    ]
    return '\r'.join(segments)


def to_fhir(row):
    """Render a service_requests row as a FHIR R4 ServiceRequest."""
    coding = [{'system': LOCAL_CODE_SYSTEM, 'code': row['test_code'], 'display': row['test_display']}]
    if row['test_loinc']:
        coding.insert(0, {'system': 'http://loinc.org', 'code': row['test_loinc'], 'display': row['test_display']})

    resource = {
        'resourceType': 'ServiceRequest',
        'id': str(row['id']),
        'identifier': [
            {
                'type': {'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/v2-0203', 'code': 'PLAC'}]},
                'system': f"urn:fake-lis:placer:{row['sending_facility'] or 'unknown'}",
                'value': row['placer_order_number'],
            },
            {
                'type': {'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/v2-0203', 'code': 'FILL'}]},
                'system': 'urn:fake-lis:filler',
                'value': row['filler_order_number'],
            },
        ],
        'status': row['status'],
        'intent': 'order',
        'category': [{'coding': [{'system': 'http://snomed.info/sct', 'code': '108252007',
                                  'display': 'Laboratory procedure'}]}],
        'priority': row['priority'],
        'code': {'coding': coding, 'text': row['test_display']},
        'subject': {
            'identifier': {'system': 'urn:fake-lis:mrn', 'value': row['patient_id']},
            'display': ' '.join(p for p in (row['patient_given'], row['patient_family']) if p),
        },
    }
    if row['authored_on']:
        resource['authoredOn'] = row['authored_on']
    if row['requester']:
        resource['requester'] = {'display': row['requester']}
    if row['clinical_info']:
        resource['note'] = [{'text': row['clinical_info']}]
    return resource


def to_fhir_json(row):
    return json.dumps(to_fhir(row), indent=2)

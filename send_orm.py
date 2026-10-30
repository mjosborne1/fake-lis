#!/usr/bin/env python3
"""
Test harness: send local HL7 v2 order files to the order entry facade.

Posts each file to the app's HTTP endpoint (or an MLLP listener) and prints
the ACK. Exits non-zero if any message is not accepted (MSA-1 != AA).

Usage:
    python send_orm.py v2-examples/0001.orm
    python send_orm.py v2-examples/                 # every *.orm / *.hl7 in the directory
    python send_orm.py v2-examples/*.orm --fresh-ids
    python send_orm.py v2-examples/0001.orm --mllp 127.0.0.1:2575
"""

import argparse
import socket
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


DEFAULT_URL = 'http://127.0.0.1:5000/hl7/orders'
MESSAGE_SUFFIXES = {'.orm', '.oml', '.hl7', '.txt'}
MLLP_START, MLLP_END = b'\x0b', b'\x1c\r'


def collect_files(paths):
    """Expand directories into their message files, keeping order stable."""
    files = []
    for path in map(Path, paths):
        if path.is_dir():
            files.extend(sorted(p for p in path.iterdir() if p.suffix.lower() in MESSAGE_SUFFIXES))
        elif path.exists():
            files.append(path)
        else:
            print(f'warning: {path} not found', file=sys.stderr)
    return files


def to_segments(text):
    """Split a message file into segments regardless of line ending style."""
    return [s for s in text.replace('\r\n', '\n').replace('\r', '\n').split('\n') if s.strip()]


def freshen_ids(segments):
    """
    Give the message a new MSH-10 and suffix ORC-2 / OBR-2 placer numbers,
    so the same file can be sent repeatedly without duplicate-order errors.
    """
    suffix = uuid.uuid4().hex[:6].upper()
    result = []
    for segment in segments:
        fields = segment.split('|')
        name = fields[0]
        if name == 'MSH' and len(fields) > 9:
            fields[9] = uuid.uuid4().hex[:12].upper()
        elif name in ('ORC', 'OBR') and len(fields) > 2 and fields[2]:
            components = fields[2].split('^')
            components[0] = f'{components[0]}-{suffix}'
            fields[2] = '^'.join(components)
        result.append('|'.join(fields))
    return result


def send_http(message, url, timeout):
    request = urllib.request.Request(url, data=message.encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'x-application/hl7-v2+er7'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'HTTP {e.code}: {e.read().decode("utf-8", "replace")[:200]}')


def send_mllp(message, address, timeout):
    host, _, port = address.rpartition(':')
    with socket.create_connection((host or '127.0.0.1', int(port)), timeout=timeout) as sock:
        sock.sendall(MLLP_START + message.encode('utf-8') + MLLP_END)
        data = b''
        while not data.endswith(MLLP_END):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    return data.strip(MLLP_START + MLLP_END).decode('utf-8')


def ack_code(ack):
    for segment in to_segments(ack):
        if segment.startswith('MSA|'):
            fields = segment.split('|')
            return fields[1], (fields[3] if len(fields) > 3 else '')
    return '??', 'No MSA segment in response'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('paths', nargs='+', help='message files or directories')
    parser.add_argument('--url', default=DEFAULT_URL, help=f'HTTP endpoint (default {DEFAULT_URL})')
    parser.add_argument('--mllp', metavar='HOST:PORT', help='send over MLLP instead of HTTP')
    parser.add_argument('--fresh-ids', action='store_true',
                        help='rewrite MSH-10 and placer order numbers so files can be resent')
    parser.add_argument('--timeout', type=float, default=10.0)
    parser.add_argument('-q', '--quiet', action='store_true', help='print only the summary line per file')
    args = parser.parse_args()

    files = collect_files(args.paths)
    if not files:
        parser.error('no message files found')

    failures = 0
    for path in files:
        segments = to_segments(path.read_text(encoding='utf-8'))
        if args.fresh_ids:
            segments = freshen_ids(segments)
        message = '\r'.join(segments)

        try:
            ack = send_mllp(message, args.mllp, args.timeout) if args.mllp else send_http(message, args.url, args.timeout)
        except (OSError, RuntimeError) as e:
            failures += 1
            print(f'✗ {path}: {e}')
            continue

        code, text = ack_code(ack)
        if code != 'AA':
            failures += 1
        print(f"{'✓' if code == 'AA' else '✗'} {path}: {code}{' - ' + text if text else ''}")
        if not args.quiet:
            for segment in segments if args.fresh_ids else []:
                print(f'  > {segment}')
            for segment in to_segments(ack):
                print(f'  < {segment}')

    print(f'\n{len(files) - failures}/{len(files)} accepted')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()

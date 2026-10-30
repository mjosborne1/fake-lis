#!/usr/bin/env python3
"""
MLLP listener for the HL7 v2 order entry facade.

Receives ORM^O01 / OML^O21 messages over MLLP (TCP) and replies with an ACK,
storing orders in the same database as the web application.

Usage:
    python mllp_listener.py [--host 127.0.0.1] [--port 2575] [--db lis_results.db]
"""

import argparse
import asyncio
import sqlite3

import hl7
from hl7.mllp import start_hl7_server

import order_entry


def make_handler(db_path):
    async def handle_connection(hl7_reader, hl7_writer):
        peer = hl7_writer.get_extra_info('peername')
        print(f'Connection from {peer}')
        try:
            while not hl7_writer.is_closing():
                message = await hl7_reader.readmessage()
                db = sqlite3.connect(db_path)
                db.row_factory = sqlite3.Row
                ack, ids = order_entry.process_message(db, str(message))
                db.close()
                print(f"  {message['MSH.F10']} -> {ack.split(chr(13))[1]} {ids or ''}")
                hl7_writer.writemessage(hl7.parse(ack))
                await hl7_writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            if not hl7_writer.is_closing():
                hl7_writer.close()
            await hl7_writer.wait_closed()
            print(f'Connection closed {peer}')

    return handle_connection


async def main(host, port, db_path):
    db = sqlite3.connect(db_path)
    order_entry.ensure_schema(db)
    db.close()

    async with await start_hl7_server(make_handler(db_path), host, port) as server:
        print(f'MLLP order listener on {host}:{port} (database: {db_path})')
        await server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=2575)
    parser.add_argument('--db', default='lis_results.db')
    args = parser.parse_args()
    try:
        asyncio.run(main(args.host, args.port, args.db))
    except KeyboardInterrupt:
        pass

"""Local-only legacy-style order manager. Python standard library, no packages."""
import argparse
import configparser
import csv
import hashlib
import html
import io
import json
import logging
import re
import secrets
import sqlite3
import uuid
from contextlib import closing
from decimal import Decimal, InvalidOperation
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parent
STATUSES = ('New', 'Processing', 'Shipped', 'Cancelled')
TRANSITIONS = {'New': ('Processing', 'Cancelled'), 'Processing': ('Shipped', 'Cancelled'),
               'Shipped': (), 'Cancelled': ()}
MAX_BODY = 2 * 1024 * 1024
LOG = logging.getLogger('legacy-orders')


class BadRequest(Exception):
    pass


def escape(value):
    return html.escape(str(value), quote=True)


class LegacyOrders:
    def __init__(self, config_path=ROOT / 'config.ini'):
        self.config_path = Path(config_path).resolve()
        self.config = configparser.ConfigParser()
        if not self.config.read(self.config_path):
            raise ValueError('Configuration file not found')
        self.db_path = self.path('database')
        self.documents = self.path('documents')
        self.reports = self.path('reports')
        self.csrf = secrets.token_urlsafe(32)

    def path(self, key):
        return (self.config_path.parent / self.config['storage'][key]).resolve()

    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        return connection

    def initialize(self):
        for directory in (self.db_path.parent, self.documents, self.reports):
            directory.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript((ROOT / 'schema.sql').read_text())
            if db.execute('SELECT COUNT(*) FROM customers').fetchone()[0] == 0:
                with (ROOT / 'sample-data/customers.csv').open(newline='') as source:
                    db.executemany('INSERT INTO customers(name,email) VALUES (?,?)',
                                   [(r['name'], r['email']) for r in csv.DictReader(source)])
                db.executemany('INSERT INTO orders(customer_id,product,quantity,unit_price_cents,status) VALUES (?,?,?,?,?)',
                               [(1, 'Drainage pipe · 100 ft', 12, 24900, 'New'),
                                (2, 'Industrial coupling', 40, 1850, 'Processing'),
                                (3, 'Valve assembly', 8, 7900, 'Shipped')])

    def export_csv(self):
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['order_id', 'customer', 'product', 'quantity', 'unit_price_cents',
                         'total_cents', 'status', 'created_at'])
        with closing(self.connect()) as db:
            for r in db.execute('SELECT o.*, c.name FROM orders o JOIN customers c ON c.id=o.customer_id ORDER BY o.id'):
                # Spreadsheet formula protection applies only to display strings.
                safe = lambda s: "'" + s if s.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else s
                writer.writerow([r['id'], safe(r['name']), safe(r['product']), r['quantity'],
                                 r['unit_price_cents'], r['quantity'] * r['unit_price_cents'], r['status'], r['created_at']])
        return output.getvalue().encode('utf-8')

    def baseline(self):
        with closing(self.connect()) as db:
            return {'customers': db.execute('SELECT COUNT(*) FROM customers').fetchone()[0],
                    'orders': db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],
                    'total_order_value_cents': db.execute('SELECT COALESCE(SUM(quantity*unit_price_cents),0) FROM orders').fetchone()[0],
                    'orders_by_status': {s: db.execute('SELECT COUNT(*) FROM orders WHERE status=?', (s,)).fetchone()[0] for s in STATUSES},
                    'documents': [dict(r) for r in db.execute('SELECT id,order_id,original_name,sha256,size_bytes FROM documents ORDER BY id')]}

    def token_input(self):
        return f'<input type="hidden" name="csrf" value="{self.csrf}">'

    def page(self, title, body):
        return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)} · LedgerWorks</title>
<link rel="stylesheet" href="/style.css"></head><body><header><a class="brand" href="/">LW<span>LedgerWorks</span></a>
<span class="edition">ORDER DESK · LEGACY EDITION</span></header><main><nav><a href="/">Orders</a><a href="/customers">Customers</a><a href="/export">Export CSV ↗</a></nav>
{body}</main><footer>Local office system · SQLite database · Files stored on this computer</footer></body></html>'''.encode()

    def fields(self, env):
        try:
            length = int(env.get('CONTENT_LENGTH') or 0)
        except ValueError:
            raise BadRequest('Invalid request size')
        if not 0 < length <= MAX_BODY:
            raise BadRequest('Request must be between 1 byte and 2 MiB')
        raw = env['wsgi.input'].read(length)
        content_type = env.get('CONTENT_TYPE', '')
        if content_type.startswith('multipart/form-data'):
            message = BytesParser(policy=default).parsebytes(
                f'Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n'.encode() + raw)
            if not message.is_multipart():
                raise BadRequest('Invalid upload')
            result = {}
            for part in message.iter_parts():
                key = part.get_param('name', header='content-disposition')
                data = part.get_payload(decode=True) or b''
                result[key] = (part.get_filename(), data) if part.get_filename() is not None else data.decode('utf-8')
            return result
        if not content_type.startswith('application/x-www-form-urlencoded'):
            raise BadRequest('Unsupported form format')
        return {k: v[0] for k, v in parse_qs(raw.decode('utf-8'), keep_blank_values=True).items()}

    def create_customer(self, fields):
        name, email = fields.get('name', '').strip(), fields.get('email', '').strip()
        if not 1 <= len(name) <= 120 or not 3 <= len(email) <= 180 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise BadRequest('Provide a customer name and a valid email address')
        with closing(self.connect()) as db, db:
            db.execute('INSERT INTO customers(name,email) VALUES (?,?)', (name, email))

    def create_order(self, fields):
        try:
            customer_id, quantity = int(fields.get('customer_id', '')), int(fields.get('quantity', ''))
            amount = Decimal(fields.get('unit_price', ''))
            if not amount.is_finite() or amount != amount.quantize(Decimal('.01')):
                raise ValueError()
            cents = int(amount * 100)
        except (ValueError, InvalidOperation, OverflowError):
            raise BadRequest('Use a valid customer, whole-number quantity, and price with at most two decimal places')
        product = fields.get('product', '').strip()
        if not 1 <= len(product) <= 160 or not 1 <= quantity <= 10000 or not 1 <= cents <= 100000000:
            raise BadRequest('Check the product, quantity (1–10000), and price ($0.01–$1,000,000)')
        with closing(self.connect()) as db, db:
            if not db.execute('SELECT id FROM customers WHERE id=?', (customer_id,)).fetchone():
                raise BadRequest('Customer does not exist')
            return db.execute('INSERT INTO orders(customer_id,product,quantity,unit_price_cents) VALUES (?,?,?,?)',
                              (customer_id, product, quantity, cents)).lastrowid

    def update_status(self, order_id, status):
        with closing(self.connect()) as db, db:
            row = db.execute('SELECT status FROM orders WHERE id=?', (order_id,)).fetchone()
            if not row or status not in TRANSITIONS[row['status']]:
                raise BadRequest('That status transition is not permitted')
            db.execute('UPDATE orders SET status=? WHERE id=?', (status, order_id))

    def upload(self, order_id, upload):
        if not isinstance(upload, tuple):
            raise BadRequest('Choose a document')
        name, data = upload
        name = name.replace('\\', '/').rsplit('/', 1)[-1]
        extension = Path(name).suffix.lower()
        if extension not in ('.pdf', '.txt', '.csv') or not data or len(name) > 180:
            raise BadRequest('Choose a nonempty PDF, TXT, or CSV file; maximum request size is 2 MiB')
        stored = uuid.uuid4().hex + extension
        destination = self.documents / stored
        with closing(self.connect()) as db, db:
            if not db.execute('SELECT id FROM orders WHERE id=?', (order_id,)).fetchone():
                raise BadRequest('Order does not exist')
            try:
                destination.write_bytes(data)
                db.execute('INSERT INTO documents(order_id,original_name,stored_name,sha256,size_bytes) VALUES (?,?,?,?,?)',
                           (order_id, name, stored, hashlib.sha256(data).hexdigest(), len(data)))
            except Exception:
                destination.unlink(missing_ok=True)
                raise

    def orders_page(self, status):
        if status and status not in STATUSES:
            raise BadRequest('Unknown status filter')
        with closing(self.connect()) as db:
            rows = db.execute('SELECT o.*, c.name FROM orders o JOIN customers c ON c.id=o.customer_id '
                              + ('WHERE o.status=? ' if status else '') + 'ORDER BY o.id DESC', (status,) if status else ()).fetchall()
            customers = db.execute('SELECT * FROM customers ORDER BY name').fetchall()
        baseline = self.baseline()
        cards = ''.join(f'<div class="metric"><span>{label}</span><strong>{value}</strong></div>' for label, value in
                        [('TOTAL ORDERS', baseline['orders']), ('OPEN ORDERS', baseline['orders_by_status']['New'] + baseline['orders_by_status']['Processing']),
                         ('ORDER VALUE', f"${baseline['total_order_value_cents']/100:,.2f}")])
        filters = '<a href="/">All orders</a> ' + ' '.join(f'<a href="/?status={s}">{s}</a>' for s in STATUSES)
        table = ''.join(f'<tr><td><a href="/orders/{r["id"]}">ORD-{r["id"]:04d}</a></td><td>{escape(r["name"])}</td><td>{escape(r["product"])}</td><td>{r["quantity"]}</td><td>${r["quantity"]*r["unit_price_cents"]/100:,.2f}</td><td><span class="pill {r["status"].lower()}">{r["status"]}</span></td></tr>' for r in rows)
        options = ''.join(f'<option value="{r["id"]}">{escape(r["name"])}</option>' for r in customers)
        return self.page('Orders', f'''<div class="heading"><div><p class="eyebrow">OPERATIONS / OVERVIEW</p><h1>Your order desk.</h1><p>Customers, orders, and paperwork. In one place.</p></div><span class="local">● Local system</span></div>
<section class="metrics">{cards}</section><section class="panel"><h2>Order register</h2><div class="filters">{filters}</div><div class="scroll"><table><thead><tr><th>Order</th><th>Customer</th><th>Product</th><th>Qty</th><th>Total</th><th>Status</th></tr></thead><tbody>{table or '<tr><td colspan="6">No orders found.</td></tr>'}</tbody></table></div></section>
<section class="panel"><h2>Create an order</h2><form method="post" action="/orders" class="form-grid">{self.token_input()}<label>Customer<select name="customer_id" required>{options}</select></label><label>Product<input name="product" maxlength="160" required placeholder="Product description"></label><label>Quantity<input name="quantity" type="number" min="1" max="10000" value="1" required></label><label>Unit price ($)<input name="unit_price" type="number" min="0.01" max="1000000" step="0.01" required placeholder="0.00"></label><button>Create order</button></form></section>''')

    def customer_page(self):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT c.*, COUNT(o.id) AS orders FROM customers c LEFT JOIN orders o ON o.customer_id=c.id GROUP BY c.id ORDER BY c.name').fetchall()
        table = ''.join(f'<tr><td>{escape(r["name"])}</td><td>{escape(r["email"])}</td><td>{r["orders"]}</td></tr>' for r in rows)
        return self.page('Customers', f'<p class="eyebrow">OPERATIONS / DIRECTORY</p><h1>Customer directory.</h1><section class="panel"><table><thead><tr><th>Customer</th><th>Email</th><th>Orders</th></tr></thead><tbody>{table}</tbody></table></section><section class="panel"><h2>Add customer</h2><form method="post" action="/customers" class="form-grid">{self.token_input()}<label>Name<input name="name" maxlength="120" required></label><label>Email<input name="email" type="email" maxlength="180" required></label><button>Add customer</button></form></section>')

    def detail_page(self, order_id):
        with closing(self.connect()) as db:
            order = db.execute('SELECT o.*,c.name FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.id=?', (order_id,)).fetchone()
            if not order:
                return None
            documents = db.execute('SELECT * FROM documents WHERE order_id=? ORDER BY id', (order_id,)).fetchall()
        r = order
        options = ''.join(f'<option>{s}</option>' for s in TRANSITIONS[r['status']])
        status_form = f'<form method="post" action="/orders/{order_id}/status" class="inline">{self.token_input()}<label>Next status<select name="status">{options}</select></label><button>Update status</button></form>' if options else '<p>This order has reached a final status.</p>'
        docs = ''.join(f'<li><a href="/documents/{d["id"]}">{escape(d["original_name"])}</a> <small>{d["size_bytes"]:,} bytes · SHA-256 {d["sha256"][:12]}…</small></li>' for d in documents)
        return self.page(f'ORD-{order_id:04d}', f'''<p class="eyebrow">OPERATIONS / ORDER DETAIL</p><h1>ORD-{order_id:04d}</h1><section class="panel"><h2>{escape(r['product'])}</h2><p>{escape(r['name'])} · {r['quantity']} units · ${r['quantity']*r['unit_price_cents']/100:,.2f}</p><p>Status: <strong>{r['status']}</strong> · Created {escape(r['created_at'])}</p>{status_form}</section><section class="panel"><h2>Order documents</h2><ul>{docs or '<li>No documents attached.</li>'}</ul><form method="post" action="/orders/{order_id}/documents" enctype="multipart/form-data" class="inline">{self.token_input()}<label>Attach PDF, TXT, or CSV<input type="file" name="document" accept=".pdf,.txt,.csv" required></label><button>Attach document</button></form><p class="muted">Files are stored on this computer. Maximum request size: 2 MiB.</p></section>''')

    def __call__(self, env, start_response):
        status, headers = '200 OK', [('Content-Type', 'text/html; charset=utf-8')]
        body = b''
        method, path = env['REQUEST_METHOD'], env.get('PATH_INFO', '/')
        try:
            if method == 'POST':
                fields = self.fields(env)
                token = fields.get('csrf', '')
                if not isinstance(token, str) or not secrets.compare_digest(token, self.csrf):
                    raise BadRequest('Form expired. Reload the page and try again.')
                destination = '/'
                if path == '/customers':
                    self.create_customer(fields)
                    destination = '/customers'
                elif path == '/orders':
                    destination = f'/orders/{self.create_order(fields)}'
                elif match := re.fullmatch(r'/orders/(\d+)/(status|documents)', path):
                    order_id = int(match[1])
                    if match[2] == 'status':
                        self.update_status(order_id, fields.get('status', ''))
                    else:
                        self.upload(order_id, fields.get('document'))
                    destination = f'/orders/{order_id}'
                else:
                    status = '404 Not Found'
                if status == '200 OK':
                    status, headers = '303 See Other', [('Location', destination)]
            elif method == 'GET':
                if path == '/':
                    body = self.orders_page(parse_qs(env.get('QUERY_STRING', '')).get('status', [''])[0])
                elif path == '/customers':
                    body = self.customer_page()
                elif path == '/style.css':
                    headers, body = [('Content-Type', 'text/css; charset=utf-8')], (ROOT / 'style.css').read_bytes()
                elif path == '/export':
                    headers = [('Content-Type', 'text/csv; charset=utf-8'), ('Content-Disposition', 'attachment; filename="orders.csv"')]
                    body = self.export_csv()
                elif match := re.fullmatch(r'/orders/(\d+)', path):
                    body = self.detail_page(int(match[1]))
                    if body is None:
                        status, body = '404 Not Found', b''
                elif match := re.fullmatch(r'/documents/(\d+)', path):
                    with closing(self.connect()) as db:
                        document = db.execute('SELECT * FROM documents WHERE id=?', (int(match[1]),)).fetchone()
                    if document and (self.documents / document['stored_name']).is_file():
                        body = (self.documents / document['stored_name']).read_bytes()
                        headers = [('Content-Type', 'application/octet-stream'),
                                   ('Content-Disposition', f'attachment; filename="document-{document["id"]}{Path(document["stored_name"]).suffix}"')]
                    else:
                        status = '404 Not Found'
                else:
                    status = '404 Not Found'
            else:
                status, headers = '405 Method Not Allowed', [('Allow', 'GET, POST')]
            if status.startswith(('404', '405')):
                body = self.page('Not found', '<h1>Page not available.</h1><p><a href="/">Return to orders</a></p>')
        except (BadRequest, UnicodeDecodeError) as error:
            status, body = '400 Bad Request', self.page('Check your entry', f'<h1>Check your entry.</h1><p>{escape(error)}</p><p><a href="/">Return to orders</a></p>')
        except Exception:
            LOG.exception('Request failed: %s %s', method, path)
            status, body = '500 Internal Server Error', self.page('Error', '<h1>Unable to complete the request.</h1><p>Check the server log.</p>')
        headers.extend([('Content-Length', str(len(body))), ('X-Content-Type-Options', 'nosniff'),
                        ('Cache-Control', 'no-store'), ('Content-Security-Policy', "default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")])
        start_response(status, headers)
        return [body]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config.ini')
    parser.add_argument('--init', action='store_true', help='Initialize schema and synthetic seed data; existing data is preserved')
    parser.add_argument('--export', action='store_true', help='Write a CSV report and exit')
    parser.add_argument('--baseline', action='store_true', help='Print counts, financial totals, and document hashes as JSON')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    app = LegacyOrders(args.config)
    if args.init:
        app.initialize()
        print('Database initialized. Existing records preserved.')
        return
    if not app.db_path.exists():
        parser.error('Run python app.py --init first')
    if args.export:
        destination = app.reports / 'orders.csv'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(app.export_csv())
        print(destination)
    elif args.baseline:
        print(json.dumps(app.baseline(), indent=2))
    else:
        host = app.config['server'].get('host', '127.0.0.1')
        if host not in ('127.0.0.1', 'localhost', '::1'):
            parser.error('This unauthenticated training application must bind to loopback')
        port = app.config['server'].getint('port', 8080)
        print(f'LedgerWorks running at http://{host}:{port}', flush=True)
        with make_server(host, port, app) as server:
            server.serve_forever()


if __name__ == '__main__':
    main()

import hashlib
import io
import json
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from wsgiref.simple_server import make_server

from app import BadRequest, LegacyOrders


class LegacyOrdersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / 'config.ini'
        config.write_text('[server]\nhost=127.0.0.1\nport=8080\n[storage]\ndatabase=orders.db\ndocuments=documents\nreports=reports\n')
        self.app = LegacyOrders(config)
        self.app.initialize()

    def request(self, path='/', method='GET', data=b'', content_type='application/x-www-form-urlencoded'):
        from urllib.parse import urlsplit
        uri = urlsplit(path)
        env = {'REQUEST_METHOD': method, 'PATH_INFO': uri.path, 'QUERY_STRING': uri.query,
               'CONTENT_LENGTH': str(len(data)), 'CONTENT_TYPE': content_type, 'wsgi.input': io.BytesIO(data)}
        response = {}
        def start(status, headers):
            response.update(status=status, headers=dict(headers))
        response['body'] = b''.join(self.app(env, start))
        return response

    def post(self, path, **fields):
        fields.setdefault('csrf', self.app.csrf)
        return self.request(path, 'POST', urlencode(fields).encode())

    def test_seed_is_repeatable_and_baseline_is_exact(self):
        self.app.initialize()
        baseline = self.app.baseline()
        self.assertEqual((baseline['customers'], baseline['orders'], baseline['total_order_value_cents']), (3, 3, 436000))
        self.assertEqual(baseline['orders_by_status'], {'New': 1, 'Processing': 1, 'Shipped': 1, 'Cancelled': 0})

    def test_customer_and_order_creation_preserve_cents_and_escape_html(self):
        response = self.post('/customers', name='<script>alert(1)</script>', email='test@example.com')
        self.assertTrue(response['status'].startswith('303'))
        response = self.post('/orders', customer_id='4', product='Steel <bracket>', quantity='3', unit_price='19.99')
        self.assertEqual(response['headers']['Location'], '/orders/4')
        page = self.request('/orders/4')['body'].decode()
        self.assertIn('$59.97', page)
        self.assertIn('Steel &lt;bracket&gt;', page)
        self.assertNotIn('<script>', page)
        with closing(self.app.connect()) as db:
            self.assertEqual(db.execute('SELECT unit_price_cents FROM orders WHERE id=4').fetchone()[0], 1999)

    def test_invalid_orders_do_not_change_database(self):
        for changes in ({'quantity': '0'}, {'quantity': '-1'}, {'unit_price': '1.001'},
                        {'unit_price': 'NaN'}, {'unit_price': 'Infinity'}, {'customer_id': '999'},
                        {'product': ''}, {'quantity': '1 OR 1=1'}):
            fields = dict(customer_id='1', product='Pipe', quantity='2', unit_price='2.50')
            fields.update(changes)
            self.assertTrue(self.post('/orders', **fields)['status'].startswith('400'), changes)
        self.assertEqual(self.app.baseline()['orders'], 3)

    def test_status_lifecycle_and_final_status_are_enforced(self):
        self.assertTrue(self.post('/orders/1/status', status='Shipped')['status'].startswith('400'))
        for status in ('Processing', 'Shipped'):
            self.assertTrue(self.post('/orders/1/status', status=status)['status'].startswith('303'))
        self.assertTrue(self.post('/orders/1/status', status='New')['status'].startswith('400'))
        self.assertTrue(self.post('/orders/2/status', status='Cancelled')['status'].startswith('303'))

    def test_upload_download_and_document_manifest(self):
        payload = b'Invoice for order 1\nAmount: $2,988.00\n'
        boundary = 'LegacyTestBoundary'
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="csrf"\r\n\r\n{self.app.csrf}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="../../invoice.txt"\r\n'
                f'Content-Type: text/plain\r\n\r\n').encode() + payload + f'\r\n--{boundary}--\r\n'.encode()
        result = self.request('/orders/1/documents', 'POST', body, f'multipart/form-data; boundary={boundary}')
        self.assertTrue(result['status'].startswith('303'))
        document = self.app.baseline()['documents'][0]
        self.assertEqual(document['original_name'], 'invoice.txt')
        self.assertEqual(document['sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(document['size_bytes'], len(payload))
        download = self.request('/documents/1')
        self.assertEqual(download['body'], payload)
        self.assertEqual(download['headers']['Content-Type'], 'application/octet-stream')
        self.assertEqual(len(list(self.app.documents.iterdir())), 1)

    def test_upload_rejects_unknown_orders_and_executable_files(self):
        for order_id, upload in ((999, ('invoice.txt', b'ok')), (1, ('script.html', b'<script>bad</script>')),
                                 (1, ('empty.txt', b'')), (1, None)):
            with self.assertRaises(BadRequest):
                self.app.upload(order_id, upload)
        self.assertEqual(list(self.app.documents.iterdir()), [])

    def test_csrf_request_size_and_route_boundaries(self):
        self.assertTrue(self.post('/customers', csrf='wrong', name='Bad', email='bad@example.com')['status'].startswith('400'))
        response = {}
        env = {'REQUEST_METHOD': 'POST', 'PATH_INFO': '/orders', 'CONTENT_LENGTH': str(3 * 1024 * 1024), 'wsgi.input': io.BytesIO()}
        self.app(env, lambda status, headers: response.update(status=status))
        self.assertTrue(response['status'].startswith('400'))
        for path in ('/config.ini', '/var/orders.db', '/../../schema.sql', '/orders/999', '/documents/999'):
            self.assertTrue(self.request(path)['status'].startswith('404'))
        self.assertTrue(self.request('/', 'DELETE')['status'].startswith('405'))

    def test_exports_are_ordered_and_formula_safe(self):
        self.post('/orders', customer_id='1', product='=SUM(A1:A2)', quantity='1', unit_price='1.00')
        response = self.request('/export')
        text = response['body'].decode()
        self.assertIn("'=SUM(A1:A2)", text)
        self.assertIn('1,Buckeye Manufacturing,Drainage pipe', text)
        self.assertEqual(len(text.splitlines()), 5)
        self.assertTrue(response['headers']['Content-Disposition'].startswith('attachment'))

    def test_filter_does_not_change_global_metrics(self):
        response = self.request('/?status=Shipped')
        self.assertIn(b'ORD-0003', response['body'])
        self.assertNotIn(b'ORD-0001', response['body'])
        self.assertIn(b'$4,360.00', response['body'])
        self.assertTrue(self.request('/?status=Unknown')['status'].startswith('400'))

    def test_real_http_server_serves_pages_and_validates_posts(self):
        server = make_server('127.0.0.1', 0, self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            for path, content_type in (('/', 'text/html'), ('/customers', 'text/html'),
                                       ('/orders/1', 'text/html'), ('/style.css', 'text/css'), ('/export', 'text/csv')):
                with urlopen(url + path) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(content_type, response.headers['Content-Type'])
            data = urlencode(dict(csrf=self.app.csrf, customer_id=1, product='HTTP item', quantity=2, unit_price='12.34')).encode()
            with urlopen(Request(url + '/orders', data=data)) as response:
                self.assertIn(b'$24.68', response.read())
            with self.assertRaises(HTTPError) as error:
                urlopen(url + '/var/orders.db')
            self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()

PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
    email TEXT NOT NULL CHECK(length(email) BETWEEN 3 AND 180)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    product TEXT NOT NULL CHECK(length(product) BETWEEN 1 AND 160),
    quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 10000),
    unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents BETWEEN 1 AND 100000000),
    status TEXT NOT NULL DEFAULT 'New' CHECK(status IN ('New','Processing','Shipped','Cancelled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

import os
import sqlite3

STORAGE_DIR = os.environ.get("ASMAR_STORAGE_DIR") or os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(STORAGE_DIR, "shop.db")

os.makedirs(STORAGE_DIR, exist_ok=True)


def setup_database():
    conn = sqlite3.connect(DATABASE_PATH)

    try:
        conn.execute("PRAGMA foreign_keys = ON")

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            email TEXT,
            google_id TEXT,
            latitude REAL,
            longitude REAL
        );

        CREATE TABLE IF NOT EXISTS merchants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            subscription_end TEXT,
            commission_rate REAL NOT NULL DEFAULT 0,
            latitude REAL,
            longitude REAL
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT,
            stock INTEGER NOT NULL DEFAULT 0,
            image TEXT,
            merchant_id INTEGER,
            category TEXT DEFAULT 'أخرى',
            image_zoom REAL DEFAULT 1,
            image_x REAL DEFAULT 0,
            image_y REAL DEFAULT 0,
            currency TEXT DEFAULT 'YER',
            status TEXT NOT NULL DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS platform_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS product_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(product_id, session_id)
        );

        CREATE TABLE IF NOT EXISTS product_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(customer_id, product_id)
        );

        CREATE TABLE IF NOT EXISTS platform_followers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER,
            order_id INTEGER,
            message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            customer_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            total REAL NOT NULL,
            status TEXT NOT NULL DEFAULT "جديد",
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            shipping_city TEXT,
            shipping_cost REAL DEFAULT 0,
            grand_total REAL DEFAULT 0,
            customer_id INTEGER,
            payment_method TEXT DEFAULT 'الدفع عند الاستلام',
            shipping_distance_km REAL DEFAULT 0,
            customer_latitude REAL,
            customer_longitude REAL,
            currency TEXT DEFAULT 'YER'
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            merchant_id INTEGER,
            currency TEXT DEFAULT 'YER',
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS merchant_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            merchant_id INTEGER NOT NULL,
            subtotal REAL NOT NULL DEFAULT 0,
            shipping_cost REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'جديد',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            commission_rate REAL NOT NULL DEFAULT 0,
            stock_restored INTEGER NOT NULL DEFAULT 0,
            currency TEXT DEFAULT 'YER',
            UNIQUE(order_id, merchant_id),
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(merchant_id) REFERENCES merchants(id)
        );

        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            image TEXT,
            category TEXT,
            link TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            UNIQUE(session_id, product_id)
        );

        CREATE TABLE IF NOT EXISTS exchange_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency TEXT NOT NULL UNIQUE,
            rate_to_yer REAL NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS shipping_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL UNIQUE,
            cost REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS shipping_rates_multi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'YER',
            cost REAL NOT NULL DEFAULT 0,
            UNIQUE(city, currency)
        );

        CREATE TABLE IF NOT EXISTS shipping_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            base_cost REAL NOT NULL DEFAULT 500,
            cost_per_km REAL NOT NULL DEFAULT 100,
            max_distance_km REAL NOT NULL DEFAULT 50
        );

        CREATE TABLE IF NOT EXISTS shipping_settings_multi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency TEXT NOT NULL UNIQUE,
            base_cost REAL NOT NULL DEFAULT 0,
            cost_per_km REAL NOT NULL DEFAULT 0,
            max_distance_km REAL NOT NULL DEFAULT 50,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            order_id INTEGER,
            merchant_id INTEGER,
            subject TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'أخرى',
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'جديدة',
            admin_reply TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            complainant_type TEXT NOT NULL DEFAULT 'customer',
            FOREIGN KEY(customer_id) REFERENCES customers(id),
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(merchant_id) REFERENCES merchants(id)
        );

        CREATE INDEX IF NOT EXISTS idx_complaints_customer
            ON complaints(customer_id);

        CREATE INDEX IF NOT EXISTS idx_complaints_merchant
            ON complaints(merchant_id);

        CREATE INDEX IF NOT EXISTS idx_complaints_order
            ON complaints(order_id);

        CREATE INDEX IF NOT EXISTS idx_complaints_status
            ON complaints(status);

        CREATE INDEX IF NOT EXISTS idx_shipping_rates_multi_city_currency
            ON shipping_rates_multi(city, currency);

        CREATE INDEX IF NOT EXISTS idx_shipping_rates_multi_currency
            ON shipping_rates_multi(currency);
        """)

        conn.commit()

    finally:
        conn.close()


if __name__ == "__main__":
    setup_database()
    print(f"Database initialized: {DATABASE_PATH}")

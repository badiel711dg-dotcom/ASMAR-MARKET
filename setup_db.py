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

        CREATE TABLE IF NOT EXISTS merchant_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER NOT NULL,
            plan_name TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'USD',
            duration_days INTEGER NOT NULL,
            starts_at TEXT,
            ends_at TEXT,
            payment_method TEXT,
            payment_reference TEXT,
            payment_proof TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            admin_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TIMESTAMP,
            FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE
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

        CREATE TABLE IF NOT EXISTS merchant_promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            promotion_type TEXT NOT NULL DEFAULT 'basic',
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            views INTEGER NOT NULL DEFAULT 0,
            clicks INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_merchant_promotions_active
            ON merchant_promotions(status, starts_at, ends_at);

        CREATE INDEX IF NOT EXISTS idx_merchant_promotions_merchant
            ON merchant_promotions(merchant_id);

        CREATE INDEX IF NOT EXISTS idx_merchant_promotions_product
            ON merchant_promotions(product_id);

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

        CREATE TABLE IF NOT EXISTS visitor_product_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(visitor_id, product_id)
        );

        CREATE INDEX IF NOT EXISTS idx_visitor_product_likes_product
            ON visitor_product_likes(product_id);

        CREATE TABLE IF NOT EXISTS product_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            color TEXT,
            size TEXT,
            stock INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
            UNIQUE(product_id, color, size)
        );

        CREATE INDEX IF NOT EXISTS idx_product_variants_product
            ON product_variants(product_id);

        CREATE TABLE IF NOT EXISTS product_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            review TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
            FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
            UNIQUE(product_id, customer_id),
            CHECK(rating >= 1 AND rating <= 5)
        );

        CREATE INDEX IF NOT EXISTS idx_product_ratings_product
            ON product_ratings(product_id);

        CREATE INDEX IF NOT EXISTS idx_product_ratings_customer
            ON product_ratings(customer_id);

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

        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_push_subscriptions_customer
            ON push_subscriptions(customer_id);

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
            variant_id INTEGER NOT NULL DEFAULT 0,
            color TEXT,
            size TEXT,
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
            sort_order INTEGER NOT NULL DEFAULT 0,
            image_scale REAL NOT NULL DEFAULT 1,
            image_x REAL NOT NULL DEFAULT 0,
            image_y REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            variant_id INTEGER NOT NULL DEFAULT 0,
            color TEXT,
            size TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            UNIQUE(session_id, product_id, variant_id)
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


        # =========================
        # Product original price migration
        # =========================
        product_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(products)").fetchall()
        }

        if "original_price" not in product_columns:
            conn.execute("""
                ALTER TABLE products
                ADD COLUMN original_price REAL
            """)

        # =========================
        # Product card image controls migration
        # =========================
        product_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(products)").fetchall()
        }

        if "card_image_zoom" not in product_columns:
            conn.execute("""
                ALTER TABLE products
                ADD COLUMN card_image_zoom REAL DEFAULT 1
            """)

        if "card_image_x" not in product_columns:
            conn.execute("""
                ALTER TABLE products
                ADD COLUMN card_image_x REAL DEFAULT 0
            """)

        if "card_image_y" not in product_columns:
            conn.execute("""
                ALTER TABLE products
                ADD COLUMN card_image_y REAL DEFAULT 0
            """)

        if "card_height" not in product_columns:
            conn.execute("""
                ALTER TABLE products
                ADD COLUMN card_height REAL DEFAULT 270
            """)

        # =========================
        # Account status / phone recovery migration
        # =========================
        customer_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(customers)").fetchall()
        }

        if "account_status" not in customer_columns:
            conn.execute("""
                ALTER TABLE customers
                ADD COLUMN account_status TEXT NOT NULL DEFAULT 'active'
            """)

        if "old_phone" not in customer_columns:
            conn.execute("""
                ALTER TABLE customers
                ADD COLUMN old_phone TEXT
            """)

        merchant_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(merchants)").fetchall()
        }

        if "account_status" not in merchant_columns:
            conn.execute("""
                ALTER TABLE merchants
                ADD COLUMN account_status TEXT NOT NULL DEFAULT 'active'
            """)

        if "old_phone" not in merchant_columns:
            conn.execute("""
                ALTER TABLE merchants
                ADD COLUMN old_phone TEXT
            """)

        # =========================
        # User demographics migrations
        # =========================

        customer_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(customers)"
            ).fetchall()
        }

        merchant_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(merchants)"
            ).fetchall()
        }

        if "gender" not in customer_columns:
            conn.execute("""
                ALTER TABLE customers
                ADD COLUMN gender TEXT
            """)

        if "country_code" not in customer_columns:
            conn.execute("""
                ALTER TABLE customers
                ADD COLUMN country_code TEXT
            """)

        if "gender" not in merchant_columns:
            conn.execute("""
                ALTER TABLE merchants
                ADD COLUMN gender TEXT
            """)

        if "country_code" not in merchant_columns:
            conn.execute("""
                ALTER TABLE merchants
                ADD COLUMN country_code TEXT
            """)

        if "created_at" not in merchant_columns:
            conn.execute("""
                ALTER TABLE merchants
                ADD COLUMN created_at TIMESTAMP
            """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS phone_recovery_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'جديد',
                matched_account_id INTEGER,
                admin_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_phone_recovery_phone
            ON phone_recovery_requests(phone)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_phone_recovery_status
            ON phone_recovery_requests(status)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_phone_recovery_role_phone
            ON phone_recovery_requests(role, phone)
        """)


        # ===== MERCHANT SUBSCRIPTION PLANS =====
        conn.execute("""
            CREATE TABLE IF NOT EXISTS merchant_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                price REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'USD',
                duration_days INTEGER NOT NULL DEFAULT 365,
                featured INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                features TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        default_plans = [
            (
                "starter",
                "STARTER",
                29,
                "USD",
                365,
                0,
                1,
                1,
                "متجر احترافي|إضافة المنتجات|إدارة الطلبات|إحصائيات أساسية"
            ),
            (
                "business",
                "BUSINESS",
                49,
                "USD",
                365,
                1,
                1,
                2,
                "متجر احترافي متقدم|إضافة المنتجات|إدارة الطلبات|إحصائيات متقدمة|ظهور مميز"
            ),
            (
                "pro",
                "PRO",
                79,
                "USD",
                365,
                0,
                1,
                3,
                "جميع مزايا BUSINESS|تحليلات متقدمة|مزايا ترويجية|أولوية الدعم"
            )
        ]

        for plan in default_plans:
            conn.execute("""
                INSERT OR IGNORE INTO merchant_plans
                (plan_key, name, price, currency, duration_days,
                 featured, active, sort_order, features)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, plan)


        # ===== SAFE MIGRATION: BUSINESS coupon feature =====
        business_plan = conn.execute("""
            SELECT features
            FROM merchant_plans
            WHERE plan_key = 'business'
        """).fetchone()

        if business_plan:
            current_features = business_plan[0] or ""
            coupon_feature = "كوبونات وخصومات للعملاء"

            if coupon_feature not in current_features:
                updated_features = (
                    current_features + "|" + coupon_feature
                    if current_features
                    else coupon_feature
                )

                conn.execute("""
                    UPDATE merchant_plans
                    SET features = ?
                    WHERE plan_key = 'business'
                """, (updated_features,))


        # ===== MERCHANT PAYMENT METHODS =====
        conn.execute("""
            CREATE TABLE IF NOT EXISTS merchant_payment_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                account_name TEXT,
                account_number TEXT,
                currency TEXT NOT NULL DEFAULT 'USD',
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


        # ===== MERCHANT SUBSCRIPTION REQUESTS =====
        conn.execute("""
            CREATE TABLE IF NOT EXISTS merchant_subscription_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id INTEGER NOT NULL,
                plan_id INTEGER NOT NULL,
                payment_method_id INTEGER,
                amount REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'USD',
                payment_reference TEXT,
                payment_proof TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                admin_note TEXT,
                reviewed_by INTEGER,
                reviewed_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE,
                FOREIGN KEY (plan_id) REFERENCES merchant_plans(id) ON DELETE RESTRICT,
                FOREIGN KEY (payment_method_id) REFERENCES merchant_payment_methods(id) ON DELETE SET NULL
            )
        """)


        # =========================================================
        # MODR ADS — مستقل عن نظام الإعلانات القديم
        # =========================================================

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS ad_placements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            placement_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            base_price REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'YER',
            display_mode TEXT NOT NULL DEFAULT 'banner',
            image_ratio TEXT NOT NULL DEFAULT '16:5',
            image_fit TEXT NOT NULL DEFAULT 'cover',
            max_items INTEGER NOT NULL DEFAULT 4,
            card_gap INTEGER NOT NULL DEFAULT 10,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ad_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            advertiser_type TEXT NOT NULL
                CHECK (advertiser_type IN ('external', 'merchant')),
            merchant_id INTEGER,
            product_id INTEGER,
            advertiser_name TEXT NOT NULL,
            advertiser_phone TEXT,
            advertiser_email TEXT,
            title TEXT NOT NULL,
            description TEXT,
            creative_type TEXT NOT NULL DEFAULT 'ready'
                CHECK (creative_type IN ('ready', 'template', 'design_request')),
            image TEXT,
            target_url TEXT,
            placement_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending_review'
                CHECK (status IN (
                    'draft', 'pending_review', 'pending_payment',
                    'approved', 'rejected', 'scheduled', 'active',
                    'paused', 'completed', 'cancelled'
                )),
            starts_at TEXT,
            ends_at TEXT,
            budget REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'YER',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            admin_note TEXT,

            CHECK (
                (advertiser_type = 'merchant' AND merchant_id IS NOT NULL)
                OR
                (advertiser_type = 'external' AND merchant_id IS NULL)
            ),

            FOREIGN KEY (merchant_id)
                REFERENCES merchants(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id)
                REFERENCES products(id) ON DELETE SET NULL,
            FOREIGN KEY (placement_id)
                REFERENCES ad_placements(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS ad_campaign_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            payment_method_id INTEGER,
            amount REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'YER',
            payment_reference TEXT,
            payment_proof TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
            admin_note TEXT,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (campaign_id)
                REFERENCES ad_campaigns(id) ON DELETE CASCADE,
            FOREIGN KEY (payment_method_id)
                REFERENCES merchant_payment_methods(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS ad_campaign_access (
            campaign_id INTEGER PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            revoked_at TEXT,
            FOREIGN KEY (campaign_id)
                REFERENCES ad_campaigns(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS ad_campaign_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            event_type TEXT NOT NULL
                CHECK (event_type IN ('impression', 'click')),
            visitor_key TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (campaign_id)
                REFERENCES ad_campaigns(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_ad_campaigns_status
            ON ad_campaigns(status);

        CREATE INDEX IF NOT EXISTS idx_ad_campaigns_merchant
            ON ad_campaigns(merchant_id);

        CREATE INDEX IF NOT EXISTS idx_ad_campaigns_placement
            ON ad_campaigns(placement_id, status);

        CREATE INDEX IF NOT EXISTS idx_ad_campaign_payments_campaign
            ON ad_campaign_payments(campaign_id, status);

        CREATE INDEX IF NOT EXISTS idx_ad_campaign_events_campaign
            ON ad_campaign_events(campaign_id, event_type, created_at);
        """)


        # =========================================================
        # MODR ADS — Staff, Roles, Permissions & Audit Log
        # =========================================================

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS modr_ads_staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'disabled')),
            created_by_staff_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login_at TIMESTAMP,
            FOREIGN KEY (created_by_staff_id)
                REFERENCES modr_ads_staff(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS modr_ads_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_key TEXT NOT NULL UNIQUE,
            role_name TEXT NOT NULL,
            description TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS modr_ads_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            permission_key TEXT NOT NULL UNIQUE,
            permission_name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS modr_ads_role_permissions (
            role_id INTEGER NOT NULL,
            permission_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (role_id, permission_id),
            FOREIGN KEY (role_id)
                REFERENCES modr_ads_roles(id) ON DELETE CASCADE,
            FOREIGN KEY (permission_id)
                REFERENCES modr_ads_permissions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS modr_ads_staff_roles (
            staff_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            assigned_by_staff_id INTEGER,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (staff_id, role_id),
            FOREIGN KEY (staff_id)
                REFERENCES modr_ads_staff(id) ON DELETE CASCADE,
            FOREIGN KEY (role_id)
                REFERENCES modr_ads_roles(id) ON DELETE CASCADE,
            FOREIGN KEY (assigned_by_staff_id)
                REFERENCES modr_ads_staff(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS modr_ads_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_type TEXT NOT NULL
                CHECK (actor_type IN ('owner', 'staff', 'system')),
            actor_staff_id INTEGER,
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            details_json TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (actor_staff_id)
                REFERENCES modr_ads_staff(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_modr_ads_staff_status
            ON modr_ads_staff(status);

        CREATE INDEX IF NOT EXISTS idx_modr_ads_staff_roles_role
            ON modr_ads_staff_roles(role_id);

        CREATE INDEX IF NOT EXISTS idx_modr_ads_role_permissions_permission
            ON modr_ads_role_permissions(permission_id);

        CREATE INDEX IF NOT EXISTS idx_modr_ads_audit_actor
            ON modr_ads_audit_logs(actor_type, actor_staff_id);

        CREATE INDEX IF NOT EXISTS idx_modr_ads_audit_entity
            ON modr_ads_audit_logs(entity_type, entity_id);

        CREATE INDEX IF NOT EXISTS idx_modr_ads_audit_created
            ON modr_ads_audit_logs(created_at);

        CREATE TABLE IF NOT EXISTS modr_ads_login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username_key TEXT NOT NULL,
            ip_address TEXT,
            succeeded INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_modr_ads_login_username_time
            ON modr_ads_login_attempts(username_key, created_at);

        CREATE INDEX IF NOT EXISTS idx_modr_ads_login_ip_time
            ON modr_ads_login_attempts(ip_address, created_at);
        """)


        # ===== MODR ADS: Default roles and permissions =====
        default_permissions = [
            ("dashboard.view", "عرض لوحة الإعلانات"),
            ("campaigns.view", "عرض الحملات"),
            ("campaigns.create", "إنشاء الحملات"),
            ("campaigns.edit", "تعديل الحملات"),
            ("campaigns.review", "مراجعة الحملات"),
            ("campaigns.approve", "اعتماد الحملات"),
            ("campaigns.reject", "رفض الحملات"),
            ("payments.view", "عرض المدفوعات"),
            ("payments.review", "مراجعة المدفوعات"),
            ("reports.view", "عرض التقارير"),
            ("reports.export", "تصدير التقارير"),
            ("support.view", "عرض طلبات الدعم"),
            ("support.manage", "إدارة طلبات الدعم"),
            ("creatives.view", "عرض المواد الإعلانية"),
            ("creatives.manage", "إدارة المواد الإعلانية"),
            ("placements.view", "عرض المساحات الإعلانية"),
            ("placements.manage", "إدارة المساحات الإعلانية"),
            ("staff.view", "عرض الموظفين"),
            ("staff.manage", "إدارة الموظفين"),
            ("settings.manage", "إدارة إعدادات الإعلانات"),
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO modr_ads_permissions
                (permission_key, permission_name)
            VALUES (?, ?)
        """, default_permissions)

        default_roles = [
            ("ads_manager", "مدير الإعلانات", "إدارة الحملات والمساحات الإعلانية"),
            ("campaign_reviewer", "مراجع الحملات", "مراجعة الحملات واعتمادها أو رفضها"),
            ("payment_officer", "مسؤول المدفوعات", "مراجعة المدفوعات"),
            ("report_analyst", "مسؤول التقارير", "عرض التقارير وتصديرها"),
            ("customer_service", "خدمة العملاء", "متابعة طلبات الدعم"),
            ("designer", "المصمم", "إدارة المواد والتصاميم الإعلانية"),
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO modr_ads_roles
                (role_key, role_name, description)
            VALUES (?, ?, ?)
        """, default_roles)

        role_permission_map = {
            "ads_manager": [
                "dashboard.view", "campaigns.view", "campaigns.create",
                "campaigns.edit", "placements.view", "placements.manage",
                "reports.view"
            ],
            "campaign_reviewer": [
                "dashboard.view", "campaigns.view", "campaigns.review",
                "campaigns.approve", "campaigns.reject"
            ],
            "payment_officer": [
                "dashboard.view", "campaigns.view",
                "payments.view", "payments.review"
            ],
            "report_analyst": [
                "dashboard.view", "reports.view", "reports.export"
            ],
            "customer_service": [
                "dashboard.view", "support.view", "support.manage"
            ],
            "designer": [
                "dashboard.view", "creatives.view", "creatives.manage"
            ],
        }

        for role_key, permission_keys in role_permission_map.items():
            role_row = conn.execute(
                "SELECT id FROM modr_ads_roles WHERE role_key = ?",
                (role_key,)
            ).fetchone()
            for permission_key in permission_keys:
                permission_row = conn.execute(
                    "SELECT id FROM modr_ads_permissions WHERE permission_key = ?",
                    (permission_key,)
                ).fetchone()
                if role_row and permission_row:
                    conn.execute("""
                        INSERT OR IGNORE INTO modr_ads_role_permissions
                            (role_id, permission_id)
                        VALUES (?, ?)
                    """, (role_row[0], permission_row[0]))

        # ===== SAFE MIGRATION: ad image controls =====
        ad_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(ads)").fetchall()
        }

        if "image_scale" not in ad_columns:
            conn.execute(
                "ALTER TABLE ads ADD COLUMN image_scale REAL NOT NULL DEFAULT 1"
            )

        if "image_x" not in ad_columns:
            conn.execute(
                "ALTER TABLE ads ADD COLUMN image_x REAL NOT NULL DEFAULT 0"
            )

        if "image_y" not in ad_columns:
            conn.execute(
                "ALTER TABLE ads ADD COLUMN image_y REAL NOT NULL DEFAULT 0"
            )

        # ===== SAFE MIGRATION: owner ad placement =====
        ad_placement_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(ads)").fetchall()
        }
        if "placement_key" not in ad_placement_columns:
            conn.execute(
                "ALTER TABLE ads ADD COLUMN placement_key TEXT NOT NULL DEFAULT 'home_featured'"
            )

        # ===== SAFE MIGRATION: ad card dimensions =====
        ad_dimension_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(ads)").fetchall()
        }

        ad_dimension_migrations = {
            "card_width": "REAL NOT NULL DEFAULT 100",
            "card_height": "REAL NOT NULL DEFAULT 270",
            "image_width": "REAL NOT NULL DEFAULT 100",
            "image_height": "REAL NOT NULL DEFAULT 270",
        }

        for column_name, column_definition in ad_dimension_migrations.items():
            if column_name not in ad_dimension_columns:
                conn.execute(
                    f"ALTER TABLE ads ADD COLUMN {column_name} {column_definition}"
                )

        # ===== SAFE MIGRATION: MODR ADS campaign fields =====
        campaign_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(ad_campaigns)").fetchall()
        }
        campaign_migrations = {
            "campaign_source": "TEXT NOT NULL DEFAULT 'advertiser'",
            "final_price": "REAL",
        }
        for column_name, column_definition in campaign_migrations.items():
            if column_name not in campaign_columns:
                conn.execute(
                    f"ALTER TABLE ad_campaigns ADD COLUMN {column_name} {column_definition}"
                )

        # ===== SAFE MIGRATION: MODR ADS placement display settings =====
        placement_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(ad_placements)").fetchall()
        }
        placement_migrations = {
            "display_mode": "TEXT NOT NULL DEFAULT 'banner'",
            "image_ratio": "TEXT NOT NULL DEFAULT '16:5'",
            "image_fit": "TEXT NOT NULL DEFAULT 'cover'",
            "max_items": "INTEGER NOT NULL DEFAULT 4",
            "card_gap": "INTEGER NOT NULL DEFAULT 10",
        }
        for column_name, column_definition in placement_migrations.items():
            if column_name not in placement_columns:
                conn.execute(
                    f"ALTER TABLE ad_placements ADD COLUMN {column_name} {column_definition}"
                )

        # ===== SAFE MIGRATION: merchant store image =====
        merchant_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(merchants)").fetchall()
        }

        if "store_image" not in merchant_columns:
            conn.execute("ALTER TABLE merchants ADD COLUMN store_image TEXT")

        # ===== SAFE MIGRATION: merchant phone verification =====
        merchant_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(merchants)").fetchall()
        }

        if "phone_verified" not in merchant_columns:
            conn.execute(
                "ALTER TABLE merchants ADD COLUMN phone_verified INTEGER DEFAULT 0"
            )

        # ===== SAFE MIGRATION: merchant email =====
        merchant_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(merchants)").fetchall()
        }
        if "email" not in merchant_columns:
            conn.execute("ALTER TABLE merchants ADD COLUMN email TEXT")

        # =========================
        # Merchant coupons migration
        # =========================

        # حفظ قيمة خصم الكوبون داخل الطلب الرئيسي
        # حتى تبقى الطلبات القديمة صحيحة حتى لو تغير الكوبون لاحقًا.
        orders_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(orders)"
            ).fetchall()
        }

        if "coupon_discount" not in orders_columns:
            conn.execute("""
                ALTER TABLE orders
                ADD COLUMN coupon_discount REAL NOT NULL DEFAULT 0
            """)

        # حفظ نصيب كل تاجر من خصم الكوبون داخل طلب التاجر.
        merchant_orders_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(merchant_orders)"
            ).fetchall()
        }

        if "coupon_discount" not in merchant_orders_columns:
            conn.execute("""
                ALTER TABLE merchant_orders
                ADD COLUMN coupon_discount REAL NOT NULL DEFAULT 0
            """)

        # كوبونات التجار
        conn.execute("""
            CREATE TABLE IF NOT EXISTS merchant_coupons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                discount_type TEXT NOT NULL DEFAULT 'percentage',
                discount_value REAL NOT NULL DEFAULT 0,
                min_order_amount REAL NOT NULL DEFAULT 0,
                starts_at TEXT,
                ends_at TEXT,
                max_uses INTEGER,
                usage_count INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (merchant_id)
                    REFERENCES merchants(id)
                    ON DELETE CASCADE
            )
        """)

        # سجل استخدام الكوبونات
        conn.execute("""
            CREATE TABLE IF NOT EXISTS coupon_usages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coupon_id INTEGER NOT NULL,
                order_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                merchant_id INTEGER NOT NULL,
                discount_amount REAL NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (coupon_id)
                    REFERENCES merchant_coupons(id)
                    ON DELETE RESTRICT,
                FOREIGN KEY (order_id)
                    REFERENCES orders(id)
                    ON DELETE RESTRICT,
                FOREIGN KEY (customer_id)
                    REFERENCES customers(id)
                    ON DELETE RESTRICT,
                FOREIGN KEY (merchant_id)
                    REFERENCES merchants(id)
                    ON DELETE RESTRICT
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_merchant_coupons_merchant
            ON merchant_coupons(merchant_id)
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_merchant_coupons_merchant_code
            ON merchant_coupons(merchant_id, code)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_coupon_usages_coupon
            ON coupon_usages(coupon_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_coupon_usages_order
            ON coupon_usages(order_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_coupon_usages_customer
            ON coupon_usages(customer_id)
        """)

        # =========================================================
        # MODER ONE OWNER ADS — مواضع إعلانات المالك المستقلة
        # منفصلة تماماً عن مواضع حملات MODR ADS
        # =========================================================
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS owner_ad_placements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            placement_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            image_ratio TEXT NOT NULL DEFAULT '16:5',
            image_fit TEXT NOT NULL DEFAULT 'cover',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        INSERT OR IGNORE INTO owner_ad_placements
            (placement_key, name, description, sort_order, image_ratio, image_fit)
        VALUES
            ('home_featured', 'إعلانات الرئيسية', 'أسفل الهيدر في الصفحة الرئيسية', 1, '16:5', 'cover'),
            ('store_featured', 'إعلانات المتجر', 'بعد معلومات المتجر وقبل المنتجات', 2, '16:5', 'cover'),
            ('product_featured', 'إعلانات تفاصيل المنتج', 'أسفل تفاصيل المنتج', 3, '4:3', 'cover'),
            ('category_featured', 'إعلانات التصنيفات', 'بعد عنوان التصنيف وقبل المنتجات', 4, '16:5', 'cover');
        """)

        # =========================================================
        # MODER ONE INVOICES — فواتير مستقلة لكل متجر داخل الطلب
        # =========================================================
        merchant_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(merchants)")
        }
        if "return_policy" not in merchant_columns:
            conn.execute("""
                ALTER TABLE merchants
                ADD COLUMN return_policy TEXT NOT NULL DEFAULT ''
            """)

        if "return_policy_en" not in merchant_columns:
            conn.execute("""
                ALTER TABLE merchants
                ADD COLUMN return_policy_en TEXT NOT NULL DEFAULT ''
            """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT NOT NULL UNIQUE,
                merchant_order_id INTEGER NOT NULL UNIQUE,
                order_id INTEGER NOT NULL,
                merchant_id INTEGER NOT NULL,
                customer_id INTEGER,
                snapshot_json TEXT NOT NULL,
                file_name TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'issued', 'failed')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                issued_at TIMESTAMP,
                FOREIGN KEY (merchant_order_id)
                    REFERENCES merchant_orders(id) ON DELETE RESTRICT,
                FOREIGN KEY (order_id)
                    REFERENCES orders(id) ON DELETE RESTRICT,
                FOREIGN KEY (merchant_id)
                    REFERENCES merchants(id) ON DELETE RESTRICT,
                FOREIGN KEY (customer_id)
                    REFERENCES customers(id) ON DELETE RESTRICT
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invoices_customer
            ON invoices(customer_id, status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invoices_merchant
            ON invoices(merchant_id, status)
        """)

        # =========================================================
        # MODER ONE OFFERS — نظام العروض السعرية المستقل
        # لا يغيّر جداول الفواتير أو الكوبونات أو الترويج
        # =========================================================
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS merchant_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            discount_type TEXT NOT NULL
                CHECK (discount_type IN ('percentage', 'fixed_price')),
            discount_value REAL,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CHECK (
                (discount_type = 'percentage'
                    AND discount_value > 0 AND discount_value < 100)
                OR
                (discount_type = 'fixed_price'
                    AND discount_value IS NULL)
            ),
            FOREIGN KEY (merchant_id)
                REFERENCES merchants(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS merchant_offer_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            offer_price REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CHECK (offer_price IS NULL OR offer_price > 0),
            UNIQUE (offer_id, product_id),
            FOREIGN KEY (offer_id)
                REFERENCES merchant_offers(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id)
                REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_merchant_offers_merchant
            ON merchant_offers(merchant_id, status);

        CREATE INDEX IF NOT EXISTS idx_merchant_offers_period
            ON merchant_offers(status, starts_at, ends_at);

        CREATE INDEX IF NOT EXISTS idx_merchant_offer_products_product
            ON merchant_offer_products(product_id);

        CREATE INDEX IF NOT EXISTS idx_merchant_offer_products_offer
            ON merchant_offer_products(offer_id);
        """)


        conn.executescript("""
        CREATE TABLE IF NOT EXISTS customer_tab_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT NOT NULL UNIQUE,
            customer_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY (customer_id)
                REFERENCES customers(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_customer_tab_sessions_customer
            ON customer_tab_sessions(customer_id);

        CREATE INDEX IF NOT EXISTS idx_customer_tab_sessions_expiry
            ON customer_tab_sessions(expires_at, revoked_at);
        """)

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS dhirgham_customer_memory (
            customer_id INTEGER PRIMARY KEY,
            memory_json TEXT NOT NULL DEFAULT '[]',
            consent_enabled INTEGER NOT NULL DEFAULT 0
                CHECK (consent_enabled IN (0, 1)),
            consent_updated_at TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id)
                REFERENCES customers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS dhirgham_merchant_memory (
            merchant_id INTEGER PRIMARY KEY,
            memory_json TEXT NOT NULL DEFAULT '[]',
            consent_enabled INTEGER NOT NULL DEFAULT 0
                CHECK (consent_enabled IN (0, 1)),
            consent_updated_at TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (merchant_id)
                REFERENCES merchants(id) ON DELETE CASCADE
        );
        """)

        conn.commit()

    finally:
        conn.close()


if __name__ == "__main__":
    setup_database()
    print(f"Database initialized: {DATABASE_PATH}")

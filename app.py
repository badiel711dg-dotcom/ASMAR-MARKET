from flask import Flask, render_template, request, redirect, session, flash

import uuid

from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os
import secrets
import hmac
import phonenumbers
from phonenumbers import geocoder
from pathlib import Path
import sqlite3
import math


app = Flask(__name__)


def calculate_distance_km(lat1, lon1, lat2, lon2):
    radius = 6371.0

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    return 2 * radius * math.asin(math.sqrt(a))
app.secret_key = os.environ.get("ASMAR_SECRET_KEY") or (_ for _ in ()).throw(RuntimeError("ASMAR_SECRET_KEY must be set in production"))
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

def normalize_phone(phone, country_code):
    phone = (phone or "").strip()
    country_code = (country_code or "").strip()

    allowed_country_codes = {item["code"] for item in get_country_codes()}

    if country_code not in allowed_country_codes:
        return None

    phone = (
        phone.replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    if phone.startswith("+"):
        phone = phone[1:]

    if phone.startswith("00"):
        phone = phone[2:]

    if phone.startswith("0"):
        phone = phone[1:]

    if not phone.isdigit():
        return None

    try:
        parsed = phonenumbers.parse(
            "+" + country_code.lstrip("+") + phone,
            None
        )
    except phonenumbers.NumberParseException:
        return None

    if not phonenumbers.is_valid_number(parsed):
        return None

    return phonenumbers.format_number(
        parsed,
        phonenumbers.PhoneNumberFormat.E164
    )


def get_country_codes():
    from babel import Locale

    ar = Locale("ar")
    en = Locale("en")

    countries = []

    for region in sorted(phonenumbers.SUPPORTED_REGIONS):
        code = phonenumbers.country_code_for_region(region)

        name_ar = ar.territories.get(region, region)
        name_en = en.territories.get(region, region)

        countries.append({
            "region": region,
            "code": f"+{code}",
            "name_ar": name_ar,
            "name_en": name_en
        })

    countries.sort(key=lambda x: x["name_ar"])

    return countries


def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]

@app.context_processor
def inject_csrf_token():
    return {
        "csrf_token": get_csrf_token(),
        "get_csrf_token": get_csrf_token
    }

@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        session_token = session.get("csrf_token", "")
        if not session_token or not token or not hmac.compare_digest(token, session_token):
            print("CSRF DEBUG:", bool(token), bool(session_token), len(token), len(session_token))
            return "طلب غير صالح - CSRF", 400


def db():
    conn = sqlite3.connect("shop.db")
    conn.row_factory = sqlite3.Row
    return conn

def register_platform_view():
    if "visitor_id" not in session:
        session["visitor_id"] = str(uuid.uuid4())

    visitor_id = session["visitor_id"]

    with db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO platform_views (session_id)
            VALUES (?)
        """, (visitor_id,))


def merchant_is_active():
    merchant_id = session.get("merchant_id")

    if not merchant_id:
        return False

    with db() as conn:
        merchant = conn.execute(
            "SELECT status, subscription_end FROM merchants WHERE id = ?",
            (merchant_id,)
        ).fetchone()

    if merchant is None:
        session.pop("merchant_id", None)
        return False

    if merchant["status"] != "approved":
        session.pop("merchant_id", None)
        return False

    if merchant["subscription_end"]:
        from datetime import date

        if merchant["subscription_end"] < date.today().isoformat():
            session.pop("merchant_id", None)
            return False

    return True



with db() as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT,
            stock INTEGER NOT NULL DEFAULT 0,
            image TEXT,
            merchant_id INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS merchants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            subscription_end TEXT
        )
    """)


@app.route("/product/<int:product_id>")
def product_details(product_id):

    if "visitor_id" not in session:
        session["visitor_id"] = str(uuid.uuid4())

    visitor_id = session["visitor_id"]

    with db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO product_views (product_id, session_id)
            VALUES (?, ?)
        """, (product_id, visitor_id))

        product = conn.execute("""
            SELECT products.*, merchants.name AS merchant_name
            FROM products
            LEFT JOIN merchants ON merchants.id = products.merchant_id
            WHERE products.id = ? AND products.status = 'active'
        """, (product_id,)).fetchone()

    if product is None:
        return "المنتج غير موجود ❌", 404

    return render_template(
        "product_details.html",
        product=product
    )


# =========================
# المتجر الرئيسي
# =========================

@app.route("/")
def home():
    register_platform_view()

    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()

    with db() as conn:
        query = """
            SELECT
                products.*,
                (
                    SELECT COUNT(*)
                    FROM product_likes
                    WHERE product_likes.product_id = products.id
                ) AS likes_count,
                (
                    SELECT COUNT(*)
                    FROM product_views
                    WHERE product_views.product_id = products.id
                ) AS views_count
            FROM products
            WHERE products.status = 'active'
        """
        params = []

        if search:
            query += " AND name LIKE ?"
            params.append(f"%{search}%")

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY id DESC"

        products = conn.execute(query, params).fetchall()

        ads = conn.execute("""
            SELECT *
            FROM ads
            WHERE active = 1
            ORDER BY sort_order ASC, id ASC
        """).fetchall()

        is_following = False
        customer_id = session.get("customer_id")

        unread_customer_notifications = 0

        if customer_id:
            is_following = conn.execute("""
                SELECT 1
                FROM platform_followers
                WHERE customer_id = ?
            """, (customer_id,)).fetchone() is not None

            unread_customer_notifications = conn.execute("""
                SELECT COUNT(*)
                FROM notifications
                WHERE customer_id = ?
                  AND is_read = 0
            """, (customer_id,)).fetchone()[0]

    return render_template(
        "index.html",
        products=products,
        ads=ads,
        search=search,
        category=category,
        is_following=is_following,
        unread_customer_notifications=unread_customer_notifications
    )


@app.route("/customer/register", methods=["GET", "POST"])
def customer_register():
    countries = get_country_codes()
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        country_code = request.form.get("country_code", "+967").strip()
        password = request.form["password"]

        allowed_country_codes = {item["code"] for item in countries}

        if country_code not in allowed_country_codes:
            return render_template(
                "customer_register.html",
                error="رمز الدولة غير صالح ❌",
                countries=countries,
            )

        phone = normalize_phone(phone, country_code)

        if not phone:
            return render_template(
                "customer_register.html",
                error="رقم الهاتف غير صالح أو غير مدعوم ❌",
                countries=get_country_codes()
            )

        if not name or not phone or not password:
            return render_template(
                "customer_register.html",
                error="جميع الحقول مطلوبة ❌"
            )

        password_hash = generate_password_hash(password)

        try:
            with db() as conn:
                conn.execute("""
                    INSERT INTO customers (name, phone, password)
                    VALUES (?, ?, ?)
                """, (name, phone, password_hash))

            return redirect("/customer/login")

        except sqlite3.IntegrityError:
            return render_template(
                "customer_register.html",
                error="رقم الهاتف مسجل مسبقًا ❌"
            )

    return render_template(
        "customer_register.html",
        countries=get_country_codes()
    )

@app.route("/customer/login", methods=["GET", "POST"])
def customer_login():
    countries = get_country_codes()

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        country_code = request.form.get("country_code", "+967").strip()
        password = request.form.get("password", "")
        allowed_country_codes = {item["code"] for item in countries}

        if country_code not in allowed_country_codes:
            return render_template(
                "customer_login.html",
                countries=countries,
                error="رمز الدولة غير صالح ❌",
            )

        phone = normalize_phone(phone, country_code)

        if not phone:
            return render_template(
                "customer_login.html",
                countries=countries,
                error="رقم الهاتف غير صالح أو غير مدعوم ❌"
            )

        with db() as conn:
            customer = conn.execute("""
                SELECT *
                FROM customers
                WHERE phone = ?
            """, (phone,)).fetchone()

        if customer and check_password_hash(customer["password"], password):
            session.pop("merchant_id", None)
            session["customer_id"] = customer["id"]
            session["customer_name"] = customer["name"]
            return redirect("/")

        return render_template(
            "customer_login.html",
            countries=countries,
            error="رقم الهاتف أو كلمة المرور غير صحيحة ❌"
        )

    return render_template(
        "customer_login.html",
        countries=countries
    )


@app.route("/product/<int:product_id>/like", methods=["POST"])
def product_like(product_id):
    customer_id = session.get("customer_id")

    if not customer_id:
        return redirect("/customer/login")

    with db() as conn:
        exists = conn.execute("""
            SELECT id
            FROM product_likes
            WHERE customer_id = ? AND product_id = ?
        """, (customer_id, product_id)).fetchone()

        if exists:
            conn.execute("""
                DELETE FROM product_likes
                WHERE customer_id = ? AND product_id = ?
            """, (customer_id, product_id))
        else:
            conn.execute("""
                INSERT INTO product_likes (customer_id, product_id)
                VALUES (?, ?)
            """, (customer_id, product_id))

    return redirect(request.referrer or "/")


@app.route("/follow", methods=["POST"])
def follow_platform():
    customer_id = session.get("customer_id")

    if not customer_id:
        return redirect("/customer/login")

    with db() as conn:
        exists = conn.execute("""
            SELECT id
            FROM platform_followers
            WHERE customer_id = ?
        """, (customer_id,)).fetchone()

        if exists:
            conn.execute("""
                DELETE FROM platform_followers
                WHERE customer_id = ?
            """, (customer_id,))
        else:
            conn.execute("""
                INSERT INTO platform_followers (customer_id)
                VALUES (?)
            """, (customer_id,))

    return redirect(request.referrer or "/")

@app.route("/customer/logout")
def customer_logout():
    session.pop("customer_id", None)
    session.pop("customer_name", None)
    return redirect("/")

@app.route("/customer/orders")
def customer_orders():
    customer_id = session.get("customer_id")

    if not customer_id:
        return redirect("/customer/login")

    with db() as conn:
        orders = conn.execute("""
            SELECT *
            FROM orders
            WHERE customer_id = ?
            ORDER BY id DESC
        """, (customer_id,)).fetchall()

        customer_orders_data = []

        for order in orders:
            merchant_orders = conn.execute("""
                SELECT
                    merchant_orders.id,
                    merchant_orders.merchant_id,
                    merchant_orders.subtotal,
                    merchant_orders.shipping_cost,
                    merchant_orders.total,
                    merchant_orders.status,
                    merchant_orders.currency,
                    merchants.name AS merchant_name
                FROM merchant_orders
                JOIN merchants
                    ON merchants.id = merchant_orders.merchant_id
                WHERE merchant_orders.order_id = ?
                ORDER BY merchant_orders.id
            """, (order["id"],)).fetchall()

            merchants_data = []

            for merchant_order in merchant_orders:
                items = conn.execute("""
                    SELECT
                        product_name,
                        price,
                        quantity,
                        currency
                    FROM order_items
                    WHERE order_id = ?
                      AND merchant_id = ?
                    ORDER BY id
                """, (
                    order["id"],
                    merchant_order["merchant_id"]
                )).fetchall()

                merchants_data.append({
                    "merchant": merchant_order,
                    "items": items
                })

            customer_orders_data.append({
                "order": order,
                "merchants": merchants_data
            })

    return render_template(
        "customer_orders.html",
        orders=customer_orders_data
    )


@app.route("/merchant/register", methods=["GET", "POST"])
def merchant_register():

    countries = get_country_codes()

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        phone_input = request.form.get("phone", "").strip()
        country_code = request.form.get("country_code", "+967").strip()
        raw_password = request.form.get("password", "")

        if not name or not phone_input or not raw_password:
            return render_template(
                "merchant_register.html",
                countries=countries,
                error="جميع الحقول مطلوبة ❌"
            )

        phone = normalize_phone(phone_input, country_code)

        if not phone:
            return render_template(
                "merchant_register.html",
                countries=countries,
                error="رقم الهاتف غير صالح أو غير مدعوم ❌"
            )

        password = generate_password_hash(raw_password)

        try:
            with db() as conn:
                conn.execute("""
                    INSERT INTO merchants
                    (name, phone, password)
                    VALUES (?, ?, ?)
                """, (name, phone, password))

            return """
            <!DOCTYPE html>
            <html lang="ar" dir="rtl">
            <meta charset="UTF-8">
            <body style="font-family:Arial;text-align:center;padding:50px">
                <h1>ASMAR MARKET 👑</h1>
                <h2>تم إرسال طلبك بنجاح ✅</h2>
                <p>طلبك بانتظار موافقة إدارة المنصة.</p>
                <a href="/">العودة للمتجر</a>
            </body>
            </html>
            """

        except sqlite3.IntegrityError:
            return render_template(
                "merchant_register.html",
                countries=countries,
                error="رقم الهاتف مسجل مسبقًا ❌"
            )

    return render_template(
        "merchant_register.html",
        countries=countries
    )


# =========================
# دخول المالك
# =========================

@app.route("/owner/login", methods=["GET", "POST"])
def owner_login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        owner_username = os.environ.get("ASMAR_OWNER_USERNAME", "owner")
        owner_password_hash = os.environ.get("ASMAR_OWNER_PASSWORD_HASH", "")

        if (
            owner_password_hash
            and username == owner_username
            and check_password_hash(owner_password_hash, password)
        ):
            session["owner"] = True
            return redirect("/admin")

        return render_template(
            "owner_login.html",
            error="اسم المستخدم أو كلمة المرور غير صحيحة"
        )

    return render_template("owner_login.html")


# =========================
# لوحة المالك
# =========================

@app.route("/admin/orders")
def admin_orders():
    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        orders = conn.execute("""
            SELECT
                orders.id AS order_id,
                orders.customer_name,
                orders.phone,
                orders.address,
                orders.total,
                orders.status,
                orders.currency,
                orders.created_at,
                order_items.product_name,
                order_items.price,
                order_items.quantity,
                order_items.currency,
                order_items.merchant_id,
                merchants.name AS merchant_name
            FROM orders
            JOIN order_items
                ON orders.id = order_items.order_id
            LEFT JOIN merchants
                ON order_items.merchant_id = merchants.id
            ORDER BY orders.id DESC
        """).fetchall()

    return render_template("admin_orders.html", orders=orders)

@app.route(
    "/admin/order/<int:order_id>/status",
    methods=["POST"]
)
def admin_order_status(order_id):

    if not session.get("owner"):
        return redirect("/owner/login")

    new_status = request.form.get("status", "").strip()

    allowed_statuses = {
        "جديد",
        "تم التأكيد",
        "قيد التجهيز",
        "تم الشحن",
        "تم التسليم",
        "ملغي"
    }

    if new_status not in allowed_statuses:
        return redirect("/admin/orders")

    with db() as conn:
        order = conn.execute(
            "SELECT id, status FROM orders WHERE id = ?",
            (order_id,)
        ).fetchone()

        if order is None:
            return "الطلب غير موجود ❌", 404

        if order["status"] == "ملغي" and new_status != "ملغي":
            return "الطلب ملغي ولا يمكن إعادة تفعيله ❌", 400

        if new_status == "ملغي" and order["status"] != "ملغي":
            merchant_orders = conn.execute("""
                SELECT id, merchant_id, stock_restored
                FROM merchant_orders
                WHERE order_id = ?
            """, (order_id,)).fetchall()

            for merchant_order in merchant_orders:
                if not merchant_order["stock_restored"]:
                    items = conn.execute("""
                        SELECT product_id, quantity
                        FROM order_items
                        WHERE order_id = ?
                          AND merchant_id = ?
                    """, (order_id, merchant_order["merchant_id"])).fetchall()

                    for item in items:
                        conn.execute("""
                            UPDATE products
                            SET stock = stock + ?
                            WHERE id = ?
                        """, (item["quantity"], item["product_id"]))

                    conn.execute("""
                        UPDATE merchant_orders
                        SET status = 'ملغي',
                            stock_restored = 1
                        WHERE id = ?
                    """, (merchant_order["id"],))
                else:
                    conn.execute("""
                        UPDATE merchant_orders
                        SET status = 'ملغي'
                        WHERE id = ?
                    """, (merchant_order["id"],))

        conn.execute("""
            UPDATE orders
            SET status = ?
            WHERE id = ?
        """, (new_status, order_id))

    return redirect("/admin/orders")


@app.route("/admin/stats")
def admin_stats():
    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        total_orders = conn.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

        currency_stats = conn.execute(
            """
            SELECT
                COALESCE(currency, 'YER') AS currency,
                COALESCE(SUM(total), 0) AS total_sales,
                COALESCE(
                    (
                        SELECT SUM(mo.subtotal * mo.commission_rate / 100.0)
                        FROM merchant_orders mo
                        JOIN orders o2 ON o2.id = mo.order_id
                        WHERE o2.status != 'ملغي'
                          AND COALESCE(o2.currency, 'YER') = COALESCE(o.currency, 'YER')
                    ),
                    0
                ) AS total_commission,
                COALESCE(
                    (
                        SELECT SUM(
                            mo.subtotal -
                            (mo.subtotal * mo.commission_rate / 100.0)
                        )
                        FROM merchant_orders mo
                        JOIN orders o2 ON o2.id = mo.order_id
                        WHERE o2.status != 'ملغي'
                          AND COALESCE(mo.currency, 'YER') = COALESCE(o.currency, 'YER')
                    ),
                    0
                ) AS merchant_due
            FROM orders o
            WHERE o.status != 'ملغي'
            GROUP BY COALESCE(o.currency, 'YER')
            ORDER BY currency
            """
        ).fetchall()

        merchant_reports = conn.execute(
            """
            SELECT
                m.id,
                m.name,
                COALESCE(mo.currency, 'YER') AS currency,
                COUNT(mo.id) AS orders_count,
                COALESCE(SUM(mo.subtotal), 0) AS sales,
                COALESCE(
                    SUM(mo.subtotal * mo.commission_rate / 100.0),
                    0
                ) AS commission,
                COALESCE(
                    SUM(
                        mo.subtotal -
                        (mo.subtotal * mo.commission_rate / 100.0)
                    ),
                    0
                ) AS merchant_due
            FROM merchants m
            LEFT JOIN merchant_orders mo
                ON mo.merchant_id = m.id
            LEFT JOIN orders o
                ON o.id = mo.order_id
                AND o.status != 'ملغي'
            WHERE mo.id IS NULL OR o.id IS NOT NULL
            GROUP BY m.id, m.name, COALESCE(mo.currency, 'YER')
            ORDER BY sales DESC
            """
        ).fetchall()

        total_sales = sum(row["total_sales"] for row in currency_stats)
        total_commission = sum(row["total_commission"] for row in currency_stats)
        merchant_due = sum(row["merchant_due"] for row in currency_stats)

    return render_template(
        "admin_stats.html",
        total_orders=total_orders,
        total_sales=currency_sales,
        total_merchants=total_merchants,
        total_products=total_products,
        total_commission=total_commission,
        merchant_due=merchant_due,
        currency_stats=currency_stats,
        merchant_reports=merchant_reports
    )


@app.route("/admin/ad/add", methods=["GET", "POST"])
def add_ad():

    if not session.get("owner"):
        return redirect("/owner/login")

    if request.method == "POST":

        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        link = request.form.get("link", "").strip()
        sort_order = request.form.get("sort_order", "0").strip()
        image_file = request.files.get("image")

        if not title:
            return "اسم الإعلان مطلوب ❌", 400

        try:
            sort_order = int(sort_order)
        except ValueError:
            sort_order = 0

        image_name = None

        if image_file and image_file.filename:
            import os
            from werkzeug.utils import secure_filename

            filename = secure_filename(image_file.filename)
            ext = os.path.splitext(filename)[1].lower()
            allowed_ext = {".jpg", ".jpeg", ".png", ".webp"}

            if ext not in allowed_ext:
                return "صيغة الصورة غير مدعومة ❌", 400

            try:
                from PIL import Image
                image_file.stream.seek(0)
                with Image.open(image_file.stream) as img:
                    img.verify()
                image_file.stream.seek(0)

                with Image.open(image_file.stream) as img:
                    format_map = {
                        ".jpg": "JPEG",
                        ".jpeg": "JPEG",
                        ".png": "PNG",
                        ".webp": "WEBP",
                    }
                    if img.format != format_map.get(ext):
                        return "محتوى الصورة لا يطابق امتداد الملف ❌", 400
            except Exception:
                return "الملف المرفوع ليس صورة صالحة ❌", 400
            finally:
                image_file.stream.seek(0)

            with db() as conn:
                cursor = conn.execute("""
                    INSERT INTO ads
                    (title, image, category, link, active, sort_order)
                    VALUES (?, ?, ?, ?, 1, ?)
                """, (
                    title,
                    None,
                    category,
                    link,
                    sort_order
                ))

                ad_id = cursor.lastrowid

            image_name = f"ad_{ad_id}{ext}"

            ads_folder = Path("static/ads")
            ads_folder.mkdir(parents=True, exist_ok=True)
            image_file.save(ads_folder / image_name)

            with db() as conn:
                conn.execute(
                    "UPDATE ads SET image = ? WHERE id = ?",
                    (image_name, ad_id)
                )

        else:
            with db() as conn:
                conn.execute("""
                    INSERT INTO ads
                    (title, image, category, link, active, sort_order)
                    VALUES (?, ?, ?, ?, 1, ?)
                """, (
                    title,
                    None,
                    category,
                    link,
                    sort_order
                ))

        return redirect("/admin")

    return render_template("add_ad.html")


@app.route("/admin/ad/<int:ad_id>/delete", methods=["POST"])
def delete_ad(ad_id):

    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        ad = conn.execute(
            "SELECT image FROM ads WHERE id = ?",
            (ad_id,)
        ).fetchone()

        if ad is None:
            return "الإعلان غير موجود ❌", 404

        conn.execute(
            "DELETE FROM ads WHERE id = ?",
            (ad_id,)
        )

        if ad["image"]:
            image_path = Path("static/ads") / ad["image"]
            if image_path.exists():
                image_path.unlink()

    return redirect("/admin")


@app.route("/admin/ad/<int:ad_id>/toggle", methods=["POST"])
def toggle_ad(ad_id):

    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        ad = conn.execute(
            "SELECT active FROM ads WHERE id = ?",
            (ad_id,)
        ).fetchone()

        if ad is None:
            return "الإعلان غير موجود ❌", 404

        new_status = 0 if ad["active"] else 1

        conn.execute(
            "UPDATE ads SET active = ? WHERE id = ?",
            (new_status, ad_id)
        )

    return redirect("/admin")


@app.route("/admin/ad/<int:ad_id>/edit", methods=["GET", "POST"])
def edit_ad(ad_id):

    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        ad = conn.execute(
            "SELECT * FROM ads WHERE id = ?",
            (ad_id,)
        ).fetchone()

        if ad is None:
            return "الإعلان غير موجود ❌", 404

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            category = request.form.get("category", "").strip()
            link = request.form.get("link", "").strip()
            sort_order = request.form.get("sort_order", "0").strip()

            image_file = request.files.get("image")
            image_name = ad["image"]
            if image_file and image_file.filename:
                from werkzeug.utils import secure_filename

                filename = secure_filename(image_file.filename)

                if filename:
                    ext = os.path.splitext(filename)[1].lower()
                    allowed_ext = {".jpg", ".jpeg", ".png", ".webp"}

                    if ext not in allowed_ext:
                        return "صيغة الصورة غير مدعومة ❌", 400

                    image_name = f"ad_{ad_id}{ext}"

                    ads_folder = Path("static/ads")
                    ads_folder.mkdir(parents=True, exist_ok=True)

                    image_file.save(ads_folder / image_name)

            if not title:
                return "اسم الإعلان مطلوب ❌", 400

            try:
                sort_order = int(sort_order)
            except ValueError:
                sort_order = 0

            conn.execute("""
                UPDATE ads
                SET title = ?, category = ?, link = ?, sort_order = ?
                WHERE id = ?
            """, (
                title,
                category,
                link,
                sort_order,
                ad_id
            ))

            conn.execute("""
                UPDATE ads
                SET image = ?
                WHERE id = ?
            """, (image_name, ad_id))

            return redirect("/admin")

    return render_template("edit_ad.html", ad=ad)


@app.route("/admin")
def admin():
    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        merchants = conn.execute("""
            SELECT * FROM merchants
            ORDER BY id DESC
        """).fetchall()

        products = conn.execute("""
            SELECT
                products.*,
                merchants.name AS merchant_name,
                merchants.phone AS merchant_phone
            FROM products
            LEFT JOIN merchants
                ON products.merchant_id = merchants.id
            ORDER BY products.id DESC
        """).fetchall()

        total_orders = conn.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

        currency_sales = conn.execute("""
            SELECT
                COALESCE(currency, 'YER') AS currency,
                COALESCE(SUM(total), 0) AS total_sales
            FROM orders
            WHERE status != 'ملغي'
            GROUP BY COALESCE(currency, 'YER')
            ORDER BY currency
        """).fetchall()

        total_merchants = conn.execute(
            "SELECT COUNT(*) FROM merchants"
        ).fetchone()[0]

        total_products = conn.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]

        total_views = conn.execute(
            "SELECT COUNT(*) FROM platform_views"
        ).fetchone()[0]

        total_followers = conn.execute(
            "SELECT COUNT(*) FROM platform_followers"
        ).fetchone()[0]

        total_likes = conn.execute(
            "SELECT COUNT(*) FROM product_likes"
        ).fetchone()[0]

        total_customers = conn.execute(
            "SELECT COUNT(*) FROM customers"
        ).fetchone()[0]

        ads = conn.execute("""
            SELECT *
            FROM ads
            ORDER BY sort_order ASC, id ASC
        """).fetchall()

    return render_template(
        "admin.html",
        merchants=merchants,
        products=products,
        ads=ads,
        total_orders=total_orders,
        total_sales=total_sales,
        total_merchants=total_merchants,
        total_products=total_products,
        total_views=total_views,
        total_followers=total_followers,
        total_likes=total_likes,
        total_customers=total_customers
    )
@app.route("/admin/ads")
def admin_ads():
    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        ads = conn.execute(
            "SELECT * FROM ads ORDER BY id DESC"
        ).fetchall()

    return render_template(
        "admin_ads.html",
        ads=ads
    )


@app.route("/admin/products")
def admin_products():
    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        products = conn.execute("""
            SELECT
                products.*,
                merchants.name AS merchant_name
            FROM products
            LEFT JOIN merchants
                ON products.merchant_id = merchants.id
            ORDER BY products.id DESC
        """).fetchall()

    return render_template(
        "admin_products.html",
        products=products
    )

@app.route("/admin/merchants")
def admin_merchants():
    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        merchants = conn.execute(
            "SELECT * FROM merchants ORDER BY id DESC"
        ).fetchall()

    return render_template("admin_merchants.html", merchants=merchants)


@app.route(
    "/admin/merchant/<int:merchant_id>/commission",
    methods=["POST"]
)
def admin_merchant_commission(merchant_id):

    if not session.get("owner"):
        return redirect("/owner/login")

    commission = request.form.get("commission_rate", "0").strip()

    try:
        commission = float(commission)
    except ValueError:
        return "نسبة العمولة غير صحيحة ❌", 400

    if commission < 0 or commission > 100:
        return "نسبة العمولة يجب أن تكون بين 0 و100 ❌", 400

    with db() as conn:
        merchant = conn.execute(
            "SELECT id FROM merchants WHERE id = ?",
            (merchant_id,)
        ).fetchone()

        if merchant is None:
            return "التاجر غير موجود ❌", 404

        conn.execute(
            """
            UPDATE merchants
            SET commission_rate = ?
            WHERE id = ?
            """,
            (commission, merchant_id)
        )

    return redirect("/admin/merchants")


# =========================
# موافقة التاجر
# =========================

@app.route(
    "/admin/merchant/<int:merchant_id>/approve",
    methods=["POST"]
)
def approve_merchant(merchant_id):

    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        conn.execute("""
            UPDATE merchants
            SET status = 'approved',
                subscription_end = date('now', '+1 year')
            WHERE id = ?
        """, (merchant_id,))

    return redirect("/admin")


# =========================
# تمديد اشتراك التاجر
# =========================

@app.route(
    "/admin/merchant/<int:merchant_id>/suspend",
    methods=["POST"]
)
def suspend_merchant(merchant_id):

    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        merchant = conn.execute(
            "SELECT id FROM merchants WHERE id = ?",
            (merchant_id,)
        ).fetchone()

        if merchant is None:
            return "التاجر غير موجود ❌", 404

        conn.execute("""
            UPDATE merchants
            SET status = 'suspended'
            WHERE id = ?
        """, (merchant_id,))

    return redirect("/admin")


@app.route(
    "/admin/merchant/<int:merchant_id>/activate",
    methods=["POST"]
)
def activate_merchant(merchant_id):

    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        merchant = conn.execute(
            "SELECT id FROM merchants WHERE id = ?",
            (merchant_id,)
        ).fetchone()

        if merchant is None:
            return "التاجر غير موجود ❌", 404

        conn.execute("""
            UPDATE merchants
            SET status = 'approved'
            WHERE id = ?
        """, (merchant_id,))

    return redirect("/admin")


@app.route(
    "/admin/merchant/<int:merchant_id>/renew",
    methods=["POST"]
)
def renew_merchant(merchant_id):

    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        merchant = conn.execute(
            "SELECT id FROM merchants WHERE id = ?",
            (merchant_id,)
        ).fetchone()

        if merchant is None:
            return "التاجر غير موجود ❌", 404

        conn.execute("""
            UPDATE merchants
            SET status = 'approved',
                subscription_end = date(
                    CASE
                        WHEN subscription_end IS NOT NULL
                             AND subscription_end > date('now')
                        THEN subscription_end
                        ELSE date('now')
                    END,
                    '+1 year'
                )
            WHERE id = ?
        """, (merchant_id,))

    return redirect("/admin")


# =========================
# رفض التاجر
# =========================

@app.route(
    "/admin/merchant/<int:merchant_id>/reject",
    methods=["POST"]
)
def reject_merchant(merchant_id):

    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        merchant = conn.execute(
            "SELECT id FROM merchants WHERE id = ?",
            (merchant_id,)
        ).fetchone()

        if merchant is None:
            return "التاجر غير موجود ❌", 404

        conn.execute("""
            UPDATE merchants
            SET status = 'rejected'
            WHERE id = ?
        """, (merchant_id,))

    return redirect("/admin")


# =========================
# خروج المالك
# =========================

@app.route("/owner/logout")
def owner_logout():

    session.pop("owner", None)
    return redirect("/owner/login")


# =========================
# دخول التاجر
# =========================

@app.route("/merchant/login", methods=["GET", "POST"])
def merchant_login():

    countries = get_country_codes()

    if request.method == "POST":

        phone_input = request.form.get("phone", "").strip()
        country_code = request.form.get("country_code", "+967").strip()
        password = request.form.get("password", "")

        phone = normalize_phone(phone_input, country_code)

        if not phone:
            return render_template(
                "merchant_login.html",
                countries=countries,
                error="رقم الهاتف غير صالح أو غير مدعوم ❌"
            )

        with db() as conn:
            merchant = conn.execute(
                "SELECT * FROM merchants WHERE phone = ?",
                (phone,)
            ).fetchone()

        if merchant is None:
            return render_template(
                "merchant_login.html",
                countries=countries,
                error="بيانات الدخول غير صحيحة"
            )

        if not check_password_hash(
            merchant["password"],
            password
        ):
            return render_template(
                "merchant_login.html",
                countries=countries,
                error="بيانات الدخول غير صحيحة"
            )

        if merchant["status"] != "approved":
            return render_template(
                "merchant_login.html",
                countries=countries,
                error="حسابك لم تتم الموافقة عليه بعد"
            )

        if merchant["subscription_end"]:
            from datetime import date

            if merchant["subscription_end"] < date.today().isoformat():
                return render_template(
                    "merchant_login.html",
                    countries=countries,
                    error="اشتراك حسابك منتهي ❌"
                )

        session.pop("customer_id", None)
        session.pop("customer_name", None)
        session["merchant_id"] = merchant["id"]

        return redirect("/merchant/dashboard")

    return render_template(
        "merchant_login.html",
        countries=countries
    )


# =========================
# لوحة التاجر
# =========================

@app.route("/merchant/dashboard")
def merchant_dashboard():

    merchant_id = session.get("merchant_id")

    if not merchant_is_active():
        return redirect("/merchant/login")

    with db() as conn:

        merchant = conn.execute(
            "SELECT * FROM merchants WHERE id = ?",
            (merchant_id,)
        ).fetchone()

        if merchant is None:
            session.pop("merchant_id", None)
            return redirect("/merchant/login")

        products = conn.execute("""
            SELECT * FROM products
            WHERE merchant_id = ?
            ORDER BY id DESC
        """, (merchant_id,)).fetchall()

        unread_notifications = conn.execute("""
            SELECT COUNT(*)
            FROM notifications
            WHERE merchant_id = ?
            AND is_read = 0
        """, (merchant_id,)).fetchone()[0]

        total_products = conn.execute("""
            SELECT COUNT(*)
            FROM products
            WHERE merchant_id = ?
        """, (merchant_id,)).fetchone()[0]

        total_orders = conn.execute("""
            SELECT COUNT(DISTINCT order_id)
            FROM order_items
            WHERE merchant_id = ?
        """, (merchant_id,)).fetchone()[0]

        new_orders = conn.execute("""
            SELECT COUNT(DISTINCT order_items.order_id)
            FROM order_items
            JOIN orders
              ON orders.id = order_items.order_id
            JOIN merchant_orders
              ON merchant_orders.order_id = order_items.order_id
             AND merchant_orders.merchant_id = order_items.merchant_id
            WHERE order_items.merchant_id = ?
              AND merchant_orders.status = 'جديد'
        """, (merchant_id,)).fetchone()[0]

    return render_template(
        "merchant_dashboard.html",
        merchant=merchant,
        products=products,
        unread_notifications=unread_notifications,
        total_products=total_products,
        total_orders=total_orders,
        new_orders=new_orders
    )


# =========================
# إضافة منتج
# =========================

@app.route("/merchant/settings", methods=["GET", "POST"])
def merchant_settings():

    if not merchant_is_active():
        return redirect("/merchant/login")

    merchant_id = session["merchant_id"]

    with db() as conn:

        if request.method == "POST":
            try:
                latitude = float(request.form.get("latitude", "").strip())
                longitude = float(request.form.get("longitude", "").strip())

                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    return "إحداثيات الموقع غير صحيحة ❌", 400

                conn.execute("""
                    UPDATE merchants
                    SET latitude = ?, longitude = ?
                    WHERE id = ?
                """, (latitude, longitude, merchant_id))

            except (ValueError, TypeError):
                return "إحداثيات الموقع غير صحيحة ❌", 400

            return redirect("/merchant/settings")

        merchant = conn.execute("""
            SELECT *
            FROM merchants
            WHERE id = ?
        """, (merchant_id,)).fetchone()

    if merchant is None:
        session.pop("merchant_id", None)
        return redirect("/merchant/login")

    return render_template(
        "merchant_settings.html",
        merchant=merchant
    )


# =========================
# إضافة منتج
# =========================

@app.route("/merchant/product/add", methods=["GET", "POST"])
def add_product():

    merchant_id = session.get("merchant_id")

    if not merchant_is_active():
        return redirect("/merchant/login")

    if request.method == "POST":

        token = request.form.get("submit_token")

        if not token:
            token = str(uuid.uuid4())

        if session.get("last_product_token") == token:
            return redirect("/merchant/dashboard")

        session["last_product_token"] = token

        name = request.form["name"].strip()
        price = request.form["price"]
        description = request.form["description"].strip()
        stock = request.form["stock"]
        category = request.form.get("category", "أخرى").strip()
        currency = request.form.get("currency", "YER").strip()

        allowed_currencies = {
            "YER", "SAR", "USD", "AED",
            "EGP", "KWD", "EUR", "GBP", "OTHER"
        }

        if currency not in allowed_currencies:
            currency = "YER"

        image = request.files.get("image")
        image_name = None

        if image and image.filename:

            filename = secure_filename(image.filename)

            upload_dir = os.path.join(
                app.root_path,
                "static",
                "uploads"
            )

            os.makedirs(upload_dir, exist_ok=True)

            try:
                from PIL import Image

                image.stream.seek(0)
                with Image.open(image.stream) as img:
                    img.verify()

                image.stream.seek(0)
                with Image.open(image.stream) as img:
                    format_map = {
                        ".jpg": "JPEG",
                        ".jpeg": "JPEG",
                        ".png": "PNG",
                        ".webp": "WEBP",
                    }
                    ext = os.path.splitext(filename)[1].lower()

                    if ext not in format_map or img.format != format_map[ext]:
                        return "محتوى الصورة لا يطابق امتداد الملف ❌", 400
            except Exception:
                return "الملف المرفوع ليس صورة صالحة ❌", 400
            finally:
                image.stream.seek(0)

            image.save(
                os.path.join(upload_dir, filename)
            )

            image_name = filename

        with db() as conn:
            conn.execute("""
                INSERT INTO products
                (
                    name,
                    price,
                    description,
                    stock,
                    image,
                    merchant_id,
                    category,
                    currency
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name,
                price,
                description,
                stock,
                image_name,
                merchant_id,
                category,
                currency
            ))

        return redirect("/merchant/dashboard")

    return render_template("add_product.html")


# =========================
# تعديل منتج
# =========================

@app.route(
    "/merchant/product/<int:product_id>/edit",
    methods=["GET", "POST"]
)
def edit_product(product_id):
    if not merchant_is_active():
        return redirect("/merchant/login")


    merchant_id = session.get("merchant_id")

    if not merchant_id:
        return redirect("/merchant/login")

    with db() as conn:

        product = conn.execute("""
            SELECT * FROM products
            WHERE id = ? AND merchant_id = ?
        """, (product_id, merchant_id)).fetchone()

        if product is None:
            return "المنتج غير موجود أو ليس تابعًا لك ❌", 404

        if request.method == "POST":

            name = request.form["name"].strip()
            price = request.form["price"]
            description = request.form["description"].strip()
            stock = request.form["stock"]
            image_zoom = request.form.get("image_zoom", product["image_zoom"] or 1)
            image_x = request.form.get("image_x", product["image_x"] or 0)
            image_y = request.form.get("image_y", product["image_y"] or 0)
            category = request.form.get("category", product["category"] or "أخرى").strip()
            currency = request.form.get("currency", product["currency"] or "YER").strip()

            allowed_currencies = {
                "YER", "SAR", "USD", "AED",
                "EGP", "KWD", "EUR", "GBP", "OTHER"
            }

            if currency not in allowed_currencies:
                currency = "YER"

            image_name = product["image"]

            image = request.files.get("image")

            if image and image.filename:

                filename = secure_filename(
                    image.filename
                )

                upload_dir = os.path.join(
                    app.root_path,
                    "static",
                    "uploads"
                )

                os.makedirs(upload_dir, exist_ok=True)

                try:
                    from PIL import Image

                    image.stream.seek(0)
                    with Image.open(image.stream) as img:
                        img.verify()

                    image.stream.seek(0)
                    with Image.open(image.stream) as img:
                        format_map = {
                            ".jpg": "JPEG",
                            ".jpeg": "JPEG",
                            ".png": "PNG",
                            ".webp": "WEBP",
                        }
                        ext = os.path.splitext(filename)[1].lower()

                        if ext not in format_map or img.format != format_map[ext]:
                            return "محتوى الصورة لا يطابق امتداد الملف ❌", 400
                except Exception:
                    return "الملف المرفوع ليس صورة صالحة ❌", 400
                finally:
                    image.stream.seek(0)

                image.save(
                    os.path.join(upload_dir, filename)
                )

                image_name = filename

            conn.execute("""
                UPDATE products
                SET name = ?,
                    price = ?,
                    description = ?,
                    stock = ?,
                    image = ?,
                    category = ?,
                    currency = ?,
                    image_zoom = ?,
                    image_x = ?,
                    image_y = ?
                WHERE id = ?
                AND merchant_id = ?
            """, (
                name,
                price,
                description,
                stock,
                image_name,
                category,
                currency,
                image_zoom,
                image_x,
                image_y,
                product_id,
                merchant_id
            ))

            return redirect("/merchant/dashboard")

    return render_template(
        "edit_product.html",
        product=product
    )


# =========================
# حذف منتج
# =========================

@app.route(
    "/merchant/product/<int:product_id>/delete",
    methods=["POST"]
)
def delete_product(product_id):
    if not merchant_is_active():
        return redirect("/merchant/login")


    merchant_id = session.get("merchant_id")

    if not merchant_id:
        return redirect("/merchant/login")

    with db() as conn:

        product = conn.execute("""
            SELECT image FROM products
            WHERE id = ?
            AND merchant_id = ?
        """, (product_id, merchant_id)).fetchone()

        if product:

            conn.execute("""
                DELETE FROM products
                WHERE id = ?
                AND merchant_id = ?
            """, (product_id, merchant_id))

    return redirect("/merchant/dashboard")



# =========================
# سلة المشتريات
# =========================

@app.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id):

    import uuid

    if "cart_session_id" not in session:
        session["cart_session_id"] = str(uuid.uuid4())

    cart_session_id = session["cart_session_id"]

    with db() as conn:
        product = conn.execute(
            "SELECT id, stock, status, currency FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()

        if product is None:
            return "المنتج غير موجود ❌", 404

        if product["status"] != "active":
            return "المنتج متوقف حاليًا ❌", 400

        if product["stock"] <= 0:
            return "المنتج غير متوفر حاليًا ❌", 400

        product_currency = (product["currency"] or "YER").strip().upper()

        cart_currencies = conn.execute("""
            SELECT DISTINCT UPPER(TRIM(COALESCE(products.currency, 'YER'))) AS currency
            FROM cart_items
            JOIN products ON products.id = cart_items.product_id
            WHERE cart_items.session_id = ?
        """, (cart_session_id,)).fetchall()

        if any(row["currency"] != product_currency for row in cart_currencies):
            return "لا يمكن إضافة منتج بعملة مختلفة إلى السلة. اختر منتجات بعملة واحدة فقط ❌", 400

        existing = conn.execute("""
            SELECT quantity FROM cart_items
            WHERE session_id = ? AND product_id = ?
        """, (cart_session_id, product_id)).fetchone()

        if existing:
            new_quantity = existing["quantity"] + 1

            if new_quantity > product["stock"]:
                new_quantity = product["stock"]

            conn.execute("""
                UPDATE cart_items
                SET quantity = ?
                WHERE session_id = ? AND product_id = ?
            """, (new_quantity, cart_session_id, product_id))

        else:
            conn.execute("""
                INSERT INTO cart_items
                (session_id, product_id, quantity)
                VALUES (?, ?, 1)
            """, (cart_session_id, product_id))

    return redirect("/cart")



@app.route("/cart/update/<int:product_id>", methods=["POST"])
def cart_update(product_id):
    cart_session_id = session.get("cart_session_id")

    if not cart_session_id:
        return redirect("/cart")

    try:
        quantity = int(request.form.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1

    if quantity < 1:
        quantity = 1

    with db() as conn:
        product = conn.execute(
            "SELECT stock, status FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()

        if product is None or product["status"] != "active":
            return redirect("/cart")

        if product["stock"] <= 0:
            conn.execute("""
                DELETE FROM cart_items
                WHERE session_id = ? AND product_id = ?
            """, (cart_session_id, product_id))
            return redirect("/cart")

        quantity = min(quantity, product["stock"])

        conn.execute("""
            UPDATE cart_items
            SET quantity = ?
            WHERE session_id = ?
            AND product_id = ?
        """, (quantity, cart_session_id, product_id))

    return redirect("/cart")



@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart_session_id = session.get("cart_session_id")

    if not cart_session_id:
        return redirect("/cart")

    with db() as conn:
        items = conn.execute("""
            SELECT
                cart_items.quantity,
                products.id AS product_id,
                products.name,
                products.price,
                products.currency,
                products.stock,
                products.merchant_id
            FROM cart_items
            JOIN products
                ON products.id = cart_items.product_id
            WHERE cart_items.session_id = ? AND products.status = 'active'
        """, (cart_session_id,)).fetchall()

        currency = (items[0]["currency"] or "YER").strip().upper()

        exchange_rate = conn.execute("SELECT rate_to_yer FROM exchange_rates WHERE currency = ?", (currency,)).fetchone()
        rate_to_yer = float(exchange_rate["rate_to_yer"]) if exchange_rate else 0.0

        shipping_rates = conn.execute("SELECT city, cost FROM shipping_rates_multi WHERE currency = ? ORDER BY id", (currency,)).fetchall()

        if not shipping_rates:
            yer_rates = conn.execute("SELECT city, cost FROM shipping_rates_multi WHERE currency = 'YER' ORDER BY id").fetchall()
            if currency == "YER":
                shipping_rates = yer_rates
            elif rate_to_yer > 0:
                shipping_rates = [{"city": row["city"], "cost": round(float(row["cost"]) / rate_to_yer, 2)} for row in yer_rates]

        shipping_settings = conn.execute("SELECT base_cost, cost_per_km, max_distance_km FROM shipping_settings_multi WHERE currency = ?", (currency,)).fetchone()

    if not items:
        return redirect("/cart")

    currencies = sorted({
        (item["currency"] or "YER").strip().upper()
        for item in items
    })

    if len(currencies) > 1:
        return render_template(
            "cart.html",
            items=items,
            total=0,
            currencies=currencies,
            currency=None,
            currency_error="السلة تحتوي على منتجات بعملات مختلفة. يرجى اختيار منتجات بعملة واحدة لإتمام الطلب."
        )

    total = sum(item["price"] * item["quantity"] for item in items)

    shipping_city = ""
    shipping_cost = 0
    grand_total = total

    if request.method == "POST":
        customer_name = request.form.get("customer_name", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        shipping_city = request.form.get("shipping_city", "").strip()
        payment_method = request.form.get("payment_method", "الدفع عند الاستلام").strip()

        try:
            customer_latitude = float(request.form.get("customer_latitude", "").strip())
            customer_longitude = float(request.form.get("customer_longitude", "").strip())

            if not (-90 <= customer_latitude <= 90 and -180 <= customer_longitude <= 180):
                raise ValueError
        except (ValueError, TypeError):
            customer_latitude = None
            customer_longitude = None

        if not customer_name or not phone or not address:
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                shipping_rates=shipping_rates,
                shipping_city=shipping_city,
                shipping_cost=0,
                grand_total=total,
                currency=currencies[0],
                error="يرجى تعبئة جميع بيانات العميل ❌"
            )

        if customer_latitude is None or customer_longitude is None:
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                shipping_rates=shipping_rates,
                shipping_city=shipping_city,
                shipping_cost=0,
                grand_total=total,
                currency=currencies[0],
                error="يرجى تحديد موقع التوصيل لحساب تكلفة الشحن 📍"
            )

        shipping = next(
            (rate for rate in shipping_rates if rate["city"] == shipping_city),
            None
        )

        if shipping is None:
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                shipping_rates=shipping_rates,
                shipping_city="",
                shipping_cost=0,
                grand_total=total,
                currency=currencies[0],
                error="مدينة الشحن غير صحيحة ❌"
            )

        # سيتم حساب تكلفة الشحن النهائية بعد قفل السلة
        # اعتمادًا على موقع كل تاجر.
        shipping_cost = 0
        grand_total = total

        with db() as conn:
            # قفل الكتابة لمنع سباق المخزون أثناء إتمام الطلب
            conn.execute("BEGIN IMMEDIATE")

            # إعادة قراءة السلة بعد القفل لمنع تكرار إنشاء الطلب
            items = conn.execute("""
                SELECT
                    cart_items.quantity,
                    products.id AS product_id,
                    products.name,
                    products.price,
                    products.currency,
                    products.stock,
                    products.merchant_id
                FROM cart_items
                JOIN products
                    ON products.id = cart_items.product_id
                WHERE cart_items.session_id = ? AND products.status = 'active'
            """, (cart_session_id,)).fetchall()

            # إذا كانت السلة فارغة فهذا يعني أن طلبًا سابقًا عالجها بالفعل
            if not items:
                conn.rollback()
                return redirect("/cart")

            # إعادة حساب الإجمالي من السلة الحالية بعد القفل
            total = sum(item["price"] * item["quantity"] for item in items)
            # حساب الشحن حسب المسافة بين العميل والتاجر
            merchant_ids = {
                item["merchant_id"]
                for item in items
                if item["merchant_id"] is not None
            }

            merchant_shipping_costs = {}
            merchant_distances = []

            base_cost = float(shipping_settings["base_cost"]) if shipping_settings else 500.0
            cost_per_km = float(shipping_settings["cost_per_km"]) if shipping_settings else 100.0
            max_distance_km = float(shipping_settings["max_distance_km"]) if shipping_settings else 50.0

            for merchant_id in merchant_ids:
                merchant = conn.execute("""
                    SELECT latitude, longitude
                    FROM merchants
                    WHERE id = ?
                """, (merchant_id,)).fetchone()

                if (
                    merchant
                    and merchant["latitude"] is not None
                    and merchant["longitude"] is not None
                    and customer_latitude is not None
                    and customer_longitude is not None
                ):
                    distance_km = calculate_distance_km(
                        customer_latitude,
                        customer_longitude,
                        float(merchant["latitude"]),
                        float(merchant["longitude"])
                    )

                    if distance_km > max_distance_km:
                        conn.rollback()
                        return render_template(
                            "checkout.html",
                            items=items,
                            total=total,
                            shipping_rates=shipping_rates,
                            shipping_city=shipping_city,
                            shipping_cost=0,
                            grand_total=total,
                            currency=currencies[0],
                            error=f"موقع التوصيل يبعد {distance_km:.1f} كم عن التاجر، والحد الأقصى للتوصيل هو {max_distance_km:.0f} كم ❌"
                        )

                    merchant_shipping_costs[merchant_id] = round(
                        base_cost + (distance_km * cost_per_km), 2
                    )
                    merchant_distances.append(distance_km)
                else:
                    merchant_shipping_costs[merchant_id] = float(shipping["cost"])

            shipping_cost = (
                round(sum(merchant_shipping_costs.values()), 2)
                if merchant_shipping_costs
                else float(shipping["cost"])
            )

            shipping_distance_km = (
                round(max(merchant_distances), 2)
                if merchant_distances
                else 0.0
            )

            grand_total = total + shipping_cost

            # إعادة فحص المخزون داخل عملية الشراء
            for item in items:
                product = conn.execute("""
                    SELECT stock, status, currency
                    FROM products
                    WHERE id = ?
                """, (item["product_id"],)).fetchone()

                if product is None:
                    return render_template(
                        "checkout.html",
                        items=items,
                        total=total,
                        shipping_rates=shipping_rates,
                        shipping_city=shipping_city,
                        shipping_cost=shipping_cost,
                        grand_total=grand_total,
                        currency=currencies[0],
                        error=f"المنتج {item['name']} لم يعد متوفرًا ❌"
                    )

                current_product_currency = (product["currency"] or "YER").strip().upper()

                if current_product_currency != currencies[0]:
                    conn.rollback()
                    return render_template(
                        "checkout.html",
                        items=items,
                        total=total,
                        shipping_rates=shipping_rates,
                        shipping_city=shipping_city,
                        shipping_cost=0,
                        grand_total=total,
                        currency=currencies[0],
                        error="تغيرت عملة أحد المنتجات أثناء إتمام الطلب. يرجى تحديث السلة والمحاولة مرة أخرى ❌"
                    )

                if product["status"] != "active":
                    return render_template(
                        "checkout.html",
                        items=items,
                        total=total,
                        shipping_rates=shipping_rates,
                        shipping_city=shipping_city,
                        shipping_cost=shipping_cost,
                        grand_total=grand_total,
                        currency=currencies[0],
                        error=f"المنتج {item['name']} متوقف حاليًا ❌"
                    )

                if product["stock"] < item["quantity"]:
                    return render_template(
                        "checkout.html",
                        items=items,
                        total=total,
                        shipping_rates=shipping_rates,
                        shipping_city=shipping_city,
                        shipping_cost=shipping_cost,
                        grand_total=grand_total,
                        currency=currencies[0],
                        error=f"المخزون غير كافٍ للمنتج {item['name']} ❌"
                    )

            cursor = conn.execute("""
                INSERT INTO orders
                (customer_id, customer_name, phone, address, total,
                 shipping_city, shipping_cost, grand_total, payment_method,
                 shipping_distance_km, customer_latitude, customer_longitude, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session.get("customer_id"),
                customer_name,
                phone,
                address,
                total,
                shipping_city,
                shipping_cost,
                grand_total,
                payment_method,
                shipping_distance_km,
                customer_latitude,
                customer_longitude,
                currencies[0]
            ))

            order_id = cursor.lastrowid

            for item in items:
                conn.execute("""
                    INSERT INTO order_items
                    (order_id, product_id, product_name, price, quantity, merchant_id, currency)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id,
                    item["product_id"],
                    item["name"],
                    item["price"],
                    item["quantity"],
                    item["merchant_id"],
                    currencies[0]
                ))

                # خصم الكمية من المخزون
                conn.execute("""
                    UPDATE products
                    SET stock = stock - ?
                    WHERE id = ?
                """, (
                    item["quantity"],
                    item["product_id"]
                ))

            # إنشاء طلب مستقل لكل تاجر داخل الطلب
            merchant_totals = {}

            for item in items:
                merchant_id = item["merchant_id"]

                if merchant_id is None:
                    continue

                merchant_totals.setdefault(merchant_id, 0)
                merchant_totals[merchant_id] += (
                    item["price"] * item["quantity"]
                )

            for merchant_id, subtotal in merchant_totals.items():

                merchant = conn.execute("""
                    SELECT commission_rate
                    FROM merchants
                    WHERE id = ?
                """, (merchant_id,)).fetchone()

                commission_rate = (
                    float(merchant["commission_rate"])
                    if merchant else 0
                )

                merchant_shipping_cost = merchant_shipping_costs.get(
                    merchant_id,
                    float(shipping["cost"])
                )

                merchant_total = round(
                    subtotal + merchant_shipping_cost, 2
                )

                conn.execute("""
                    INSERT INTO merchant_orders
                    (order_id, merchant_id, subtotal, shipping_cost, total, status, commission_rate, currency)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id,
                    merchant_id,
                    subtotal,
                    merchant_shipping_cost,
                    merchant_total,
                    "جديد",
                    commission_rate,
                    currencies[0]
                ))

            # إنشاء إشعار لكل تاجر لديه منتج في الطلب
            merchant_ids = set(
                item["merchant_id"]
                for item in items
                if item["merchant_id"] is not None
            )

            for merchant_id in merchant_ids:
                conn.execute("""
                    INSERT INTO notifications
                    (merchant_id, order_id, message)
                    VALUES (?, ?, ?)
                """, (
                    merchant_id,
                    order_id,
                    f"لديك طلب جديد رقم #{order_id} 🔔"
                ))

            conn.execute("""
                DELETE FROM cart_items
                WHERE session_id = ?
            """, (cart_session_id,))

        return redirect("/order/success/" + str(order_id))

    return render_template(
        "checkout.html",
        items=items,
        total=total,
        shipping_rates=shipping_rates,
        shipping_city=shipping_city,
        shipping_cost=shipping_cost,
        grand_total=grand_total,
        currency=currencies[0],
        error=None
    )

@app.route("/order/success/<int:order_id>")
def order_success(order_id):
    customer_id = session.get("customer_id")

    if not customer_id:
        return redirect("/customer/login")

    with db() as conn:
        customer = conn.execute(
            "SELECT id FROM customers WHERE id = ?",
            (customer_id,)
        ).fetchone()

        if customer is None:
            session.pop("customer_id", None)
            session.pop("customer_name", None)
            return redirect("/customer/login")

        order = conn.execute("""
            SELECT *
            FROM orders
            WHERE id = ?
              AND customer_id = ?
        """, (order_id, customer_id)).fetchone()

    if order is None:
        return "الطلب غير موجود ❌", 404

    return render_template(
        "order_success.html",
        order=order
    )


@app.route("/cart")
def cart():

    cart_session_id = session.get("cart_session_id")

    if not cart_session_id:
        return render_template(
            "cart.html",
            items=[],
            total=0,
            currencies=[],
            currency=None,
            currency_error=None
        )

    with db() as conn:
        items = conn.execute("""
            SELECT
                cart_items.id,
                cart_items.quantity,
                products.id AS product_id,
                products.name,
                products.price,
                products.currency,
                products.image,
                products.stock,
                products.merchant_id
            FROM cart_items
            JOIN products
                ON products.id = cart_items.product_id
            WHERE cart_items.session_id = ? AND products.status = 'active'
            ORDER BY cart_items.id DESC
        """, (cart_session_id,)).fetchall()

    currencies = sorted({
        (item["currency"] or "YER").strip().upper()
        for item in items
    })

    currency_error = None
    currency = currencies[0] if len(currencies) == 1 else None

    if len(currencies) > 1:
        currency_error = "السلة تحتوي على منتجات بعملات مختلفة. يرجى اختيار منتجات بعملة واحدة لإتمام الطلب."
        total = 0
    else:
        total = sum(
            item["price"] * item["quantity"]
            for item in items
        )

    return render_template(
        "cart.html",
        items=items,
        total=total,
        currencies=currencies,
        currency=currency,
        currency_error=currency_error
    )


@app.route("/cart/remove/<int:product_id>", methods=["POST"])
def cart_remove(product_id):

    cart_session_id = session.get("cart_session_id")

    if cart_session_id:
        with db() as conn:
            conn.execute("""
                DELETE FROM cart_items
                WHERE session_id = ?
                AND product_id = ?
            """, (cart_session_id, product_id))

    return redirect("/cart")

# =========================
# تشغيل الموقع
# =========================


@app.route("/merchant/order/<int:order_id>")
def merchant_order_details(order_id):
    if not merchant_is_active():
        return redirect("/merchant/login")

    merchant_id = session["merchant_id"]

    with db() as conn:
        order = conn.execute("""
            SELECT
                orders.id AS order_id,
                orders.customer_name,
                orders.phone,
                orders.address,
                orders.shipping_city,
                merchant_orders.shipping_cost,
                merchant_orders.total AS grand_total,
                merchant_orders.status,
                merchant_orders.currency,
                orders.created_at
            FROM orders
            JOIN merchant_orders
                ON orders.id = merchant_orders.order_id
               AND merchant_orders.merchant_id = ?
            JOIN order_items
                ON orders.id = order_items.order_id
               AND order_items.merchant_id = ?
            WHERE orders.id = ?
              AND merchant_orders.merchant_id = ?
            LIMIT 1
        """, (merchant_id, merchant_id, order_id, merchant_id)).fetchone()

        if order is None:
            return "الطلب غير موجود أو لا يخص هذا التاجر ❌", 404

        items = conn.execute("""
            SELECT product_name, price, quantity, currency
            FROM order_items
            WHERE order_id = ?
              AND merchant_id = ?
        """, (order_id, merchant_id)).fetchall()

    return render_template(
        "merchant_order_details.html",
        order=order,
        items=items
    )


@app.route(
    "/merchant/order/<int:order_id>/status",
    methods=["POST"]
)
def merchant_order_status(order_id):

    if not merchant_is_active():
        return redirect("/merchant/login")

    merchant_id = session["merchant_id"]

    new_status = request.form.get("status", "").strip()

    allowed_statuses = {
        "جديد",
        "تم التأكيد",
        "قيد التجهيز",
        "تم الشحن",
        "تم التسليم",
        "ملغي"
    }

    if new_status not in allowed_statuses:
        return redirect("/merchant/orders")

    with db() as conn:
        merchant_order = conn.execute("""
            SELECT id, status, stock_restored
            FROM merchant_orders
            WHERE order_id = ?
              AND merchant_id = ?
        """, (order_id, merchant_id)).fetchone()

        if merchant_order is None:
            return "الطلب غير موجود أو لا يخص هذا التاجر ❌", 404

        if merchant_order["status"] == "ملغي" and new_status != "ملغي":
            return "الطلب ملغي ولا يمكن إعادة تفعيله ❌", 400

        if new_status == "ملغي" and merchant_order["status"] != "ملغي" and not merchant_order["stock_restored"]:
            items = conn.execute("""
                SELECT product_id, quantity
                FROM order_items
                WHERE order_id = ?
                  AND merchant_id = ?
            """, (order_id, merchant_id)).fetchall()

            for item in items:
                conn.execute("""
                    UPDATE products
                    SET stock = stock + ?
                    WHERE id = ?
                """, (item["quantity"], item["product_id"]))

            conn.execute("""
                UPDATE merchant_orders
                SET status = ?, stock_restored = 1
                WHERE order_id = ?
                  AND merchant_id = ?
            """, (new_status, order_id, merchant_id))
        else:
            conn.execute("""
                UPDATE merchant_orders
                SET status = ?
                WHERE order_id = ?
                  AND merchant_id = ?
            """, (new_status, order_id, merchant_id))

        statuses = [
            row["status"]
            for row in conn.execute("""
                SELECT status
                FROM merchant_orders
                WHERE order_id = ?
            """, (order_id,)).fetchall()
        ]

        active_statuses = [status for status in statuses if status != "ملغي"]

        if not active_statuses:
            overall_status = "ملغي"
        elif all(status == "تم التسليم" for status in active_statuses):
            overall_status = "تم التسليم"
        elif all(status in {"تم الشحن", "تم التسليم"} for status in active_statuses):
            overall_status = "تم الشحن"
        elif all(status in {"قيد التجهيز", "تم الشحن", "تم التسليم"} for status in active_statuses):
            overall_status = "قيد التجهيز"
        elif all(status in {"تم التأكيد", "قيد التجهيز", "تم الشحن", "تم التسليم"} for status in active_statuses):
            overall_status = "تم التأكيد"
        else:
            overall_status = "جديد"

        conn.execute("""
            UPDATE orders
            SET status = ?
            WHERE id = ?
        """, (overall_status, order_id))

        customer_id = conn.execute("""
            SELECT customer_id
            FROM orders
            WHERE id = ?
        """, (order_id,)).fetchone()["customer_id"]

        if customer_id and merchant_order["status"] != new_status:
            customer_message = f"تم تحديث حالة طلبك رقم #{order_id} إلى: {overall_status}"

            existing_notification = conn.execute("""
                SELECT id
                FROM notifications
                WHERE customer_id = ?
                  AND order_id = ?
                  AND message = ?
                LIMIT 1
            """, (
                customer_id,
                order_id,
                customer_message
            )).fetchone()

            if existing_notification is None:
                conn.execute("""
                    INSERT INTO notifications
                    (customer_id, order_id, message)
                    VALUES (?, ?, ?)
                """, (
                    customer_id,
                    order_id,
                    customer_message
                ))

    return redirect("/merchant/orders")


@app.route("/merchant/orders")
def merchant_orders():
    if not merchant_is_active():
        return redirect("/merchant/login")

    merchant_id = session["merchant_id"]

    with db() as conn:
        orders = conn.execute("""
            SELECT
                orders.id AS order_id,
                orders.customer_name,
                orders.phone,
                orders.address,
                orders.shipping_city,
                merchant_orders.shipping_cost,
                merchant_orders.total AS grand_total,
                merchant_orders.status,
                merchant_orders.currency,
                orders.created_at,
                (
                    SELECT product_name
                    FROM order_items
                    WHERE order_id = orders.id
                      AND merchant_id = ?
                    ORDER BY id
                    LIMIT 1
                ) AS product_name,
                (
                    SELECT price
                    FROM order_items
                    WHERE order_id = orders.id
                      AND merchant_id = ?
                    ORDER BY id
                    LIMIT 1
                ) AS price,
                (
                    SELECT quantity
                    FROM order_items
                    WHERE order_id = orders.id
                      AND merchant_id = ?
                    ORDER BY id
                    LIMIT 1
                ) AS quantity
            FROM orders
            JOIN merchant_orders
                ON orders.id = merchant_orders.order_id
               AND merchant_orders.merchant_id = ?
            WHERE merchant_orders.merchant_id = ?
            ORDER BY orders.id DESC
        """, (
            merchant_id,
            merchant_id,
            merchant_id,
            merchant_id,
            merchant_id
        )).fetchall()

    return render_template("merchant_orders.html", orders=orders)

# ==================== مركز الشكاوى والدعم ====================

@app.route("/complaints")
def complaints_center():
    if session.get("merchant_id"):
        return redirect("/merchant/complaints")

    if session.get("customer_id"):
        return redirect("/customer/complaints")

    return render_template("complaints_center.html")


# ==================== شكاوى التاجر ====================

@app.route("/merchant/complaints")
def merchant_complaints():
    if not merchant_is_active():
        return redirect("/merchant/login")

    merchant_id = session["merchant_id"]

    with db() as conn:
        complaints = conn.execute("""
            SELECT c.*, o.id AS order_number,
                   cu.name AS customer_name
            FROM complaints c
            LEFT JOIN orders o ON o.id = c.order_id
            LEFT JOIN customers cu ON cu.id = c.customer_id
            WHERE c.merchant_id = ?
              AND c.complainant_type = 'merchant'
            ORDER BY c.created_at DESC
        """, (merchant_id,)).fetchall()

    return render_template(
        "merchant_complaints.html",
        complaints=complaints
    )


@app.route("/merchant/complaints/new", methods=["GET", "POST"])
def merchant_complaint_new():
    if not merchant_is_active():
        return redirect("/merchant/login")

    merchant_id = session["merchant_id"]

    with db() as conn:
        orders = conn.execute("""
            SELECT DISTINCT o.id, o.status, o.created_at
            FROM orders o
            INNER JOIN order_items oi ON oi.order_id = o.id
            WHERE oi.merchant_id = ?
            ORDER BY o.id DESC
        """, (merchant_id,)).fetchall()

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        category = request.form.get("category", "أخرى").strip()
        message = request.form.get("message", "").strip()
        order_id = request.form.get("order_id") or None

        allowed_categories = {
            "مشكلة في الطلب",
            "مشكلة مع العميل",
            "مشكلة في المنتج",
            "الدفع",
            "الشحن",
            "أخرى"
        }

        if category not in allowed_categories:
            category = "أخرى"

        if not subject or not message:
            flash("يرجى كتابة عنوان الشكوى وتفاصيلها.", "error")
            return render_template(
                "merchant_complaint_new.html",
                orders=orders
            )

        with db() as conn:
            if order_id:
                order = conn.execute("""
                    SELECT o.id
                    FROM orders o
                    INNER JOIN order_items oi ON oi.order_id = o.id
                    WHERE o.id = ? AND oi.merchant_id = ?
                    LIMIT 1
                """, (order_id, merchant_id)).fetchone()

                if not order:
                    order_id = None

            conn.execute("""
                INSERT INTO complaints
                (customer_id, order_id, merchant_id, subject, category,
                 message, complainant_type)
                VALUES (NULL, ?, ?, ?, ?, ?, 'merchant')
            """, (
                order_id,
                merchant_id,
                subject,
                category,
                message
            ))
            conn.commit()

        flash("تم إرسال شكواك بنجاح، وستتم مراجعتها من الإدارة.", "success")
        return redirect("/merchant/complaints")

    return render_template(
        "merchant_complaint_new.html",
        orders=orders
    )


@app.route("/merchant/notifications")
def merchant_notifications():
    if not merchant_is_active():
        return redirect("/merchant/login")

    merchant_id = session["merchant_id"]

    with db() as conn:
        notifications = conn.execute("""
            SELECT id, order_id, message, is_read, created_at
            FROM notifications
            WHERE merchant_id = ?
            ORDER BY id DESC
        """, (merchant_id,)).fetchall()
    return render_template("merchant_notifications.html", notifications=notifications)


@app.route("/customer/notifications")
def customer_notifications():
    customer_id = session.get("customer_id")
    if not customer_id:
        return redirect("/customer/login")

    with db() as conn:
        notifications = conn.execute("""
            SELECT id, order_id, message, is_read, created_at
            FROM notifications
            WHERE customer_id = ?
            ORDER BY id DESC
        """, (customer_id,)).fetchall()

        conn.execute("""
            UPDATE notifications
            SET is_read = 1
            WHERE customer_id = ?
        """, (customer_id,))

    return render_template(
        "customer_notifications.html",
        notifications=notifications
    )


@app.route("/admin/product/<int:product_id>/toggle", methods=["POST"])
def admin_product_toggle(product_id):
    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        product = conn.execute(
            "SELECT status FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()

        if product:
            new_status = "inactive" if product["status"] == "active" else "active"
            conn.execute(
                "UPDATE products SET status = ? WHERE id = ?",
                (new_status, product_id)
            )

    return redirect("/admin")


@app.route("/admin/product/<int:product_id>/delete", methods=["POST"])
def admin_product_delete(product_id):
    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        conn.execute(
            "DELETE FROM products WHERE id = ?",
            (product_id,)
        )

    return redirect("/admin")



@app.route("/customer/account")
def customer_account():
    customer_id = session.get("customer_id")

    if not customer_id:
        return redirect("/customer/login")

    with db() as conn:
        customer = conn.execute("""
            SELECT id, name, phone, created_at
            FROM customers
            WHERE id = ?
        """, (customer_id,)).fetchone()

        if customer is None:
            session.pop("customer_id", None)
            session.pop("customer_name", None)
            return redirect("/customer/login")

        orders_count = conn.execute("""
            SELECT COUNT(*)
            FROM orders
            WHERE customer_id = ?
        """, (customer_id,)).fetchone()[0]

        is_following = conn.execute("""
            SELECT 1
            FROM platform_followers
            WHERE customer_id = ?
        """, (customer_id,)).fetchone() is not None

    return render_template(
        "customer_account.html",
        customer=customer,
        orders_count=orders_count,
        is_following=is_following
    )

# ==================== نظام الشكاوى ====================

@app.route("/customer/complaints")
def customer_complaints():
    customer_id = session.get("customer_id")
    if not customer_id:
        return redirect("/customer/login")

    with db() as conn:
        complaints = conn.execute("""
            SELECT c.*, o.id AS order_number, m.name AS merchant_name
            FROM complaints c
            LEFT JOIN orders o ON o.id = c.order_id
            LEFT JOIN merchants m ON m.id = c.merchant_id
            WHERE c.customer_id = ?
            ORDER BY c.created_at DESC
        """, (customer_id,)).fetchall()

    return render_template("customer_complaints.html", complaints=complaints)


@app.route("/customer/complaints/new", methods=["GET", "POST"])
def customer_complaint_new():
    customer_id = session.get("customer_id")
    if not customer_id:
        return redirect("/customer/login")

    with db() as conn:
        orders = conn.execute("""
            SELECT id, grand_total, total, status, created_at
            FROM orders
            WHERE customer_id = ?
            ORDER BY id DESC
        """, (customer_id,)).fetchall()

        merchants = conn.execute("""
            SELECT id, name
            FROM merchants
            WHERE status = "approved"
            ORDER BY name
        """).fetchall()

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        category = request.form.get("category", "أخرى").strip()
        message = request.form.get("message", "").strip()
        order_id = request.form.get("order_id") or None
        merchant_id = request.form.get("merchant_id") or None

        allowed_categories = {
            "مشكلة في الطلب",
            "مشكلة مع التاجر",
            "مشكلة في المنتج",
            "الدفع",
            "الشحن",
            "أخرى"
        }

        if category not in allowed_categories:
            category = "أخرى"

        if not subject or not message:
            flash("يرجى كتابة عنوان الشكوى وتفاصيلها.", "error")
            return render_template(
                "customer_complaint_new.html",
                orders=orders,
                merchants=merchants
            )

        with db() as conn:
            if order_id:
                order = conn.execute("""
                    SELECT id FROM orders
                    WHERE id = ? AND customer_id = ?
                """, (order_id, customer_id)).fetchone()
                if not order:
                    order_id = None

            if merchant_id:
                merchant = conn.execute("""
                    SELECT id FROM merchants
                    WHERE id = ? AND status = "approved"
                """, (merchant_id,)).fetchone()
                if not merchant:
                    merchant_id = None

            conn.execute("""
                INSERT INTO complaints
                (customer_id, order_id, merchant_id, subject, category, message)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                customer_id,
                order_id,
                merchant_id,
                subject,
                category,
                message
            ))
            conn.commit()

        flash("تم إرسال شكواك بنجاح، وسيتم مراجعتها من الإدارة.", "success")
        return redirect("/customer/complaints")

    return render_template(
        "customer_complaint_new.html",
        orders=orders,
        merchants=merchants
    )


@app.route("/admin/complaints")
def admin_complaints():
    if not session.get("owner"):
        return redirect("/owner/login")

    status_filter = request.args.get("status", "").strip()

    with db() as conn:
        query = """
            SELECT c.*,
                   cu.name AS customer_name,
                   cu.phone AS customer_phone,
                   m.name AS merchant_name,
                   m.phone AS merchant_phone,
                   o.id AS order_number
            FROM complaints c
            LEFT JOIN customers cu ON cu.id = c.customer_id
            LEFT JOIN merchants m ON m.id = c.merchant_id
            LEFT JOIN orders o ON o.id = c.order_id
        """

        params = ()

        if status_filter:
            query += " WHERE c.status = ?"
            params = (status_filter,)

        query += " ORDER BY c.created_at DESC"

        complaints = conn.execute(query, params).fetchall()

    return render_template(
        "admin_complaints.html",
        complaints=complaints,
        status_filter=status_filter
    )


@app.route("/admin/complaint/<int:complaint_id>/update", methods=["POST"])
def admin_complaint_update(complaint_id):
    if not session.get("owner"):
        return redirect("/owner/login")

    status = request.form.get("status", "قيد المراجعة").strip()
    admin_reply = request.form.get("admin_reply", "").strip()

    allowed_statuses = {
        "جديدة",
        "قيد المراجعة",
        "تم الحل",
        "مرفوضة"
    }

    if status not in allowed_statuses:
        status = "قيد المراجعة"

    with db() as conn:
        complaint = conn.execute("""
            SELECT id, customer_id, merchant_id, complainant_type, subject
            FROM complaints
            WHERE id = ?
        """, (complaint_id,)).fetchone()

        if not complaint:
            flash("الشكوى غير موجودة.", "error")
            return redirect("/admin/complaints")

        conn.execute("""
            UPDATE complaints
            SET status = ?,
                admin_reply = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, admin_reply, complaint_id))

        notification_message = (
            f"تم تحديث شكواك: {complaint['subject']} — الحالة: {status}"
        )

        if complaint["complainant_type"] == "merchant" and complaint["merchant_id"]:
            conn.execute("""
                INSERT INTO notifications
                (merchant_id, order_id, message, is_read, created_at)
                VALUES (?, NULL, ?, 0, CURRENT_TIMESTAMP)
            """, (
                complaint["merchant_id"],
                notification_message
            ))
        elif complaint["customer_id"]:
            conn.execute("""
                INSERT INTO notifications
                (customer_id, order_id, message, is_read, created_at)
                VALUES (?, NULL, ?, 0, CURRENT_TIMESTAMP)
            """, (
                complaint["customer_id"],
                notification_message
            ))

        conn.commit()

    flash("تم تحديث الشكوى وإشعار صاحبها.", "success")
    return redirect("/admin/complaints")


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000))
    )

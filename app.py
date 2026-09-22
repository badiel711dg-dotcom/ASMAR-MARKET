from flask import Flask, render_template, request, redirect, session, flash, send_from_directory, jsonify

import uuid

from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
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

# حماية من الصور ذات الأبعاد الضخمة (Decompression Bomb)
try:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 20_000_000
except Exception:
    pass


def process_product_image(image_stream, upload_dir):
    """معالجة صور المنتجات تلقائيًا وقص الفراغات الخارجية بأمان."""
    from PIL import Image, ImageOps
    import os
    import uuid

    image_stream.seek(0)

    with Image.open(image_stream) as source:
        img = ImageOps.exif_transpose(source).convert("RGBA")

        original_w, original_h = img.size

        # نستخدم نسخة صغيرة للتحليل فقط حتى تكون المعالجة سريعة.
        max_analysis = 360
        scale = min(1.0, max_analysis / max(original_w, original_h))

        if scale < 1:
            aw = max(1, int(original_w * scale))
            ah = max(1, int(original_h * scale))
            analysis = img.convert("RGB").resize(
                (aw, ah),
                Image.Resampling.LANCZOS
            )
        else:
            analysis = img.convert("RGB")

        aw, ah = analysis.size
        pixels = analysis.load()

        # أخذ لون الخلفية من عدة مناطق على الحواف.
        samples = []

        for x in range(0, aw, max(1, aw // 20)):
            samples.append(pixels[x, 0])
            samples.append(pixels[x, ah - 1])

        for y in range(0, ah, max(1, ah // 20)):
            samples.append(pixels[0, y])
            samples.append(pixels[aw - 1, y])

        # متوسط لون الحواف.
        bg = tuple(
            sum(c[i] for c in samples) // len(samples)
            for i in range(3)
        )

        # سماحية اختلاف الخلفية.
        threshold = 32

        def similar(pixel):
            return (
                abs(pixel[0] - bg[0]) <= threshold
                and abs(pixel[1] - bg[1]) <= threshold
                and abs(pixel[2] - bg[2]) <= threshold
            )

        # نسبة البكسلات القريبة من الخلفية في الصف/العمود.
        def row_background_ratio(y):
            step = max(1, aw // 120)
            total = 0
            same = 0

            for x in range(0, aw, step):
                total += 1
                if similar(pixels[x, y]):
                    same += 1

            return same / total if total else 0

        def col_background_ratio(x):
            step = max(1, ah // 120)
            total = 0
            same = 0

            for y in range(0, ah, step):
                total += 1
                if similar(pixels[x, y]):
                    same += 1

            return same / total if total else 0

        # قص الفراغ من الأعلى.
        top = 0
        while top < int(ah * 0.45) and row_background_ratio(top) >= 0.88:
            top += 1

        # قص الفراغ من الأسفل.
        bottom = ah - 1
        while bottom > int(ah * 0.55) and row_background_ratio(bottom) >= 0.88:
            bottom -= 1

        # قص الفراغ من اليسار.
        left = 0
        while left < int(aw * 0.45) and col_background_ratio(left) >= 0.88:
            left += 1

        # قص الفراغ من اليمين.
        right = aw - 1
        while right > int(aw * 0.55) and col_background_ratio(right) >= 0.88:
            right -= 1

        # تحويل الحدود إلى أبعاد الصورة الأصلية.
        if scale < 1:
            left = int(left / scale)
            top = int(top / scale)
            right = min(original_w - 1, int(right / scale))
            bottom = min(original_h - 1, int(bottom / scale))

        crop_w = right - left + 1
        crop_h = bottom - top + 1

        # هامش أمان 4%.
        pad_x = max(10, int(original_w * 0.04))
        pad_y = max(10, int(original_h * 0.04))

        left = max(0, left - pad_x)
        top = max(0, top - pad_y)
        right = min(original_w - 1, right + pad_x)
        bottom = min(original_h - 1, bottom + pad_y)

        crop_w = right - left + 1
        crop_h = bottom - top + 1

        # لا نستخدم القص إلا إذا كان فعلاً يقلل مساحة فارغة بشكل واضح.
        if (
            crop_w >= original_w * 0.30
            and crop_h >= original_h * 0.30
            and crop_w * crop_h < original_w * original_h * 0.92
        ):
            img = img.crop((left, top, right + 1, bottom + 1))

        # توحيد الحجم النهائي.
        img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)

        # خلفية بيضاء موحدة مع الحفاظ على الشفافية.
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.getchannel("A"))

        os.makedirs(upload_dir, exist_ok=True)

        filename = f"{uuid.uuid4().hex}.jpg"
        path = os.path.join(upload_dir, filename)

        background.save(
            path,
            "JPEG",
            quality=90,
            optimize=True,
            progressive=True
        )

        return filename
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

        if not token:
            token = request.headers.get("X-CSRFToken", "")

        session_token = session.get("csrf_token", "")

        if not session_token or not token or not hmac.compare_digest(token, session_token):
            print("CSRF DEBUG:", bool(token), bool(session_token), len(token), len(session_token))
            return "طلب غير صالح - CSRF", 400


STORAGE_DIR = os.environ.get("ASMAR_STORAGE_DIR") or app.root_path
DATABASE_PATH = os.path.join(STORAGE_DIR, "shop.db")
UPLOADS_DIR = os.path.join(STORAGE_DIR, "static", "uploads")
ADS_DIR = os.path.join(STORAGE_DIR, "static", "ads")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(ADS_DIR, exist_ok=True)


@app.route("/static/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOADS_DIR, filename)


@app.route("/static/ads/<path:filename>")
def ad_file(filename):
    return send_from_directory(ADS_DIR, filename)


def db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def ensure_merchant_orders_viewed_column():
    with db() as conn:
        columns = conn.execute("PRAGMA table_info(merchant_orders)").fetchall()
        column_names = {row["name"] for row in columns}

        if "viewed" not in column_names:
            conn.execute("""
                ALTER TABLE merchant_orders
                ADD COLUMN viewed INTEGER NOT NULL DEFAULT 0
            """)
            conn.commit()


def ensure_product_images_table():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS product_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                image TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id)
                    REFERENCES products(id)
                    ON DELETE CASCADE
            )
        """)
        conn.commit()


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



from setup_db import setup_database

setup_database()
ensure_merchant_orders_viewed_column()
ensure_product_images_table()


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

        variants = conn.execute("""
            SELECT
                id,
                color,
                size,
                stock
            FROM product_variants
            WHERE product_id = ?
            ORDER BY id ASC
        """, (product_id,)).fetchall()

        rating_data = conn.execute("""
            SELECT
                COALESCE(AVG(rating), 0) AS average_rating,
                COUNT(*) AS ratings_count
            FROM product_ratings
            WHERE product_id = ?
        """, (product_id,)).fetchone()

        # صور المنتج — حتى 4 صور مع دعم المنتجات القديمة
        product_images = conn.execute("""
            SELECT
                id,
                product_id,
                image,
                sort_order
            FROM product_images
            WHERE product_id = ?
            ORDER BY sort_order ASC, id ASC
        """, (product_id,)).fetchall()

        if not product_images and product["image"]:
            product_images = [{
                "id": None,
                "product_id": product_id,
                "image": product["image"],
                "sort_order": 0
            }]

    average_rating = float(rating_data["average_rating"] or 0)
    ratings_count = int(rating_data["ratings_count"] or 0)

    return render_template(
        "product_details.html",
        product=product,
        variants=variants,
        product_images=product_images,
        average_rating=average_rating,
        ratings_count=ratings_count
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

        # صور المنتجات — حتى 4 صور لكل منتج
        product_ids = [product["id"] for product in products]

        product_images_map = {}

        if product_ids:
            placeholders = ",".join("?" for _ in product_ids)

            image_rows = conn.execute(
                f"""
                    SELECT
                        id,
                        product_id,
                        image,
                        sort_order
                    FROM product_images
                    WHERE product_id IN ({placeholders})
                    ORDER BY product_id ASC, sort_order ASC, id ASC
                """,
                product_ids
            ).fetchall()

            for image_row in image_rows:
                product_images_map.setdefault(
                    image_row["product_id"],
                    []
                ).append(image_row)

        # تجهيز الصور داخل كل منتج مع دعم المنتجات القديمة
        products_with_images = []

        for product in products:
            images = product_images_map.get(
                product["id"],
                []
            )

            if not images and product["image"]:
                images = [{
                    "id": None,
                    "product_id": product["id"],
                    "image": product["image"],
                    "sort_order": 0
                }]

            product_data = dict(product)
            product_data["product_images"] = images[:4]

            products_with_images.append(product_data)

        products = products_with_images

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
        unread_customer_notifications=unread_customer_notifications,
        vapid_public_key=os.environ.get("ASMAR_VAPID_PUBLIC_KEY", "")
    )


@app.route("/customer/register", methods=["GET", "POST"])
def customer_register():
    countries = get_country_codes()
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        country_code = request.form.get("country_code", "+967").strip()
        gender = request.form.get("gender", "").strip()
        password = request.form["password"]

        allowed_country_codes = {item["code"] for item in countries}
        allowed_genders = {"male", "female"}

        if gender not in allowed_genders:
            return render_template(
                "customer_register.html",
                error="يرجى اختيار الجنس ❌",
                countries=countries,
            )

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
                    INSERT INTO customers
                    (name, phone, password, gender, country_code)
                    VALUES (?, ?, ?, ?, ?)
                """, (name, phone, password_hash, gender, country_code))

            return redirect("/customer/login")

        except sqlite3.IntegrityError:
            with db() as conn:
                existing_customer = conn.execute(
                    "SELECT id FROM customers WHERE phone = ?",
                    (phone,)
                ).fetchone()

            return render_template(
                "customer_register.html",
                countries=countries,
                error="رقم الهاتف مسجل مسبقًا ❌",
                phone_recovery_available=bool(existing_customer),
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
            if customer["account_status"] == "disabled":
                return render_template(
                    "customer_login.html",
                    countries=countries,
                    error="هذا الحساب معطّل حاليًا. إذا كنت تعتقد أن الرقم يخصك، يمكنك تقديم طلب استعادة الرقم."
                )

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

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        with db() as conn:
            likes_count = conn.execute("""
                SELECT COUNT(*)
                FROM product_likes
                WHERE product_id = ?
            """, (product_id,)).fetchone()[0]

        return {"success": True, "likes_count": likes_count}

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
        gender = request.form.get("gender", "").strip()
        raw_password = request.form.get("password", "")

        allowed_country_codes = {item["code"] for item in countries}
        allowed_genders = {"male", "female"}

        if country_code not in allowed_country_codes:
            return render_template(
                "merchant_register.html",
                countries=countries,
                error="رمز الدولة غير صالح ❌"
            )

        if gender not in allowed_genders:
            return render_template(
                "merchant_register.html",
                countries=countries,
                error="يرجى اختيار الجنس ❌"
            )

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
                    (name, phone, password, gender, country_code)
                    VALUES (?, ?, ?, ?, ?)
                """, (name, phone, password, gender, country_code))

            return """
            <!DOCTYPE html>
            <html lang="ar" dir="rtl">
            <meta charset="UTF-8">
            <body style="font-family:Arial;text-align:center;padding:50px">
                <h1>MODER ONE 👑</h1>
                <h2>تم إرسال طلبك بنجاح ✅</h2>
                <p>طلبك بانتظار موافقة إدارة المنصة.</p>
                <a href="/">العودة للمتجر</a>
            </body>
            </html>
            """

        except sqlite3.IntegrityError:
            with db() as conn:
                existing_merchant = conn.execute(
                    "SELECT id FROM merchants WHERE phone = ?",
                    (phone,)
                ).fetchone()

            return render_template(
                "merchant_register.html",
                countries=countries,
                error="رقم الهاتف مسجل مسبقًا ❌",
                phone_recovery_available=bool(existing_merchant),
            )

    return render_template(
        "merchant_register.html",
        countries=countries
    )


# =========================
# طلب استعادة رقم الهاتف
# =========================

@app.route("/phone-recovery", methods=["GET", "POST"])
def phone_recovery():
    countries = get_country_codes()

    if request.method == "POST":
        role = request.form.get("role", "").strip()
        name = request.form.get("name", "").strip()
        phone_input = request.form.get("phone", "").strip()
        country_code = request.form.get("country_code", "+967").strip()
        reason = request.form.get("reason", "").strip()

        if role not in {"customer", "merchant"}:
            return render_template(
                "phone_recovery.html",
                countries=countries,
                error="نوع الحساب غير صالح ❌",
                role=role,
                name=name,
                phone=phone_input,
                country_code=country_code,
                reason=reason,
            )

        if not name or not phone_input or not reason:
            return render_template(
                "phone_recovery.html",
                countries=countries,
                error="جميع الحقول مطلوبة ❌",
                role=role,
                name=name,
                phone=phone_input,
                country_code=country_code,
                reason=reason,
            )

        phone = normalize_phone(phone_input, country_code)

        if not phone:
            return render_template(
                "phone_recovery.html",
                countries=countries,
                error="رقم الهاتف غير صالح أو غير مدعوم ❌",
                role=role,
                name=name,
                phone=phone_input,
                country_code=country_code,
                reason=reason,
            )

        table = "customers" if role == "customer" else "merchants"

        with db() as conn:
            account = conn.execute(
                f"SELECT id FROM {table} WHERE phone = ?",
                (phone,)
            ).fetchone()

            if account is None:
                return render_template(
                    "phone_recovery.html",
                    countries=countries,
                    error="هذا الرقم غير مسجل لدينا بهذا النوع من الحسابات ❌",
                    role=role,
                    name=name,
                    phone=phone_input,
                    country_code=country_code,
                    reason=reason,
                )

            existing_request = conn.execute("""
                SELECT id
                FROM phone_recovery_requests
                WHERE role = ?
                  AND phone = ?
                  AND status = 'جديد'
                LIMIT 1
            """, (role, phone)).fetchone()

            if existing_request:
                return render_template(
                    "phone_recovery.html",
                    countries=countries,
                    error="يوجد بالفعل طلب استعادة قيد المراجعة لهذا الرقم ⏳",
                    role=role,
                    name=name,
                    phone=phone_input,
                    country_code=country_code,
                    reason=reason,
                )

            conn.execute("""
                INSERT INTO phone_recovery_requests
                (role, name, phone, reason, status, matched_account_id)
                VALUES (?, ?, ?, ?, 'جديد', ?)
            """, (
                role,
                name,
                phone,
                reason,
                account["id"],
            ))

        return render_template(
            "phone_recovery.html",
            countries=countries,
            success="تم إرسال طلب استعادة الرقم بنجاح ✅ سيتم مراجعته من إدارة المنصة.",
        )

    return render_template(
        "phone_recovery.html",
        countries=countries,
        country_code="+967",
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
        # قفل الكتابة لمنع تضارب تحديث الحالة أو استرجاع المخزون مرتين.
        conn.execute("BEGIN IMMEDIATE")

        order = conn.execute("""
            SELECT id, status, customer_id
            FROM orders
            WHERE id = ?
        """, (order_id,)).fetchone()

        if order is None:
            return "الطلب غير موجود ❌", 404

        old_status = order["status"]

        if old_status == "ملغي" and new_status != "ملغي":
            return "الطلب ملغي ولا يمكن إعادة تفعيله ❌", 400

        merchant_orders = conn.execute("""
            SELECT id, merchant_id, status, stock_restored
            FROM merchant_orders
            WHERE order_id = ?
        """, (order_id,)).fetchall()

        if new_status == "ملغي" and old_status != "ملغي":
            for merchant_order in merchant_orders:

                if not merchant_order["stock_restored"]:
                    items = conn.execute("""
                        SELECT
                            product_id,
                            quantity,
                            variant_id,
                            color,
                            size
                        FROM order_items
                        WHERE order_id = ?
                          AND merchant_id = ?
                    """, (
                        order_id,
                        merchant_order["merchant_id"]
                    )).fetchall()

                    for item in items:

                        if item["variant_id"] > 0:
                            # إعادة الكمية إلى نفس اللون والمقاس.
                            conn.execute("""
                                UPDATE product_variants
                                SET stock = stock + ?
                                WHERE id = ?
                                  AND product_id = ?
                            """, (
                                item["quantity"],
                                item["variant_id"],
                                item["product_id"]
                            ))

                            # products.stock = مجموع مخزون جميع الألوان والمقاسات.
                            variant_total = conn.execute("""
                                SELECT COALESCE(SUM(stock), 0) AS total_stock
                                FROM product_variants
                                WHERE product_id = ?
                            """, (
                                item["product_id"],
                            )).fetchone()["total_stock"]

                            conn.execute("""
                                UPDATE products
                                SET stock = ?
                                WHERE id = ?
                            """, (
                                variant_total,
                                item["product_id"]
                            ))

                        else:
                            # منتج قديم بدون ألوان أو مقاسات.
                            conn.execute("""
                                UPDATE products
                                SET stock = stock + ?
                                WHERE id = ?
                            """, (
                                item["quantity"],
                                item["product_id"]
                            ))

                conn.execute("""
                    UPDATE merchant_orders
                    SET status = 'ملغي',
                        stock_restored = 1
                    WHERE id = ?
                """, (merchant_order["id"],))

        else:
            # المالك هو صاحب القرار العام من لوحة الإدارة،
            # لذلك تتم مزامنة حالة جميع التجار مع حالة الطلب الرئيسية.
            conn.execute("""
                UPDATE merchant_orders
                SET status = ?
                WHERE order_id = ?
            """, (
                new_status,
                order_id
            ))

        conn.execute("""
            UPDATE orders
            SET status = ?
            WHERE id = ?
        """, (
            new_status,
            order_id
        ))

        # إشعار العميل عند تغير الحالة فقط.
        if (
            order["customer_id"]
            and old_status != new_status
        ):
            customer_message = (
                f"تم تحديث حالة طلبك رقم #{order_id} إلى: {new_status}"
            )

            existing_notification = conn.execute("""
                SELECT id
                FROM notifications
                WHERE customer_id = ?
                  AND order_id = ?
                  AND message = ?
                LIMIT 1
            """, (
                order["customer_id"],
                order_id,
                customer_message
            )).fetchone()

            if existing_notification is None:
                conn.execute("""
                    INSERT INTO notifications
                    (customer_id, order_id, message)
                    VALUES (?, ?, ?)
                """, (
                    order["customer_id"],
                    order_id,
                    customer_message
                ))

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
        total_merchants = conn.execute(
            "SELECT COUNT(*) FROM merchants"
        ).fetchone()[0]
        total_products = conn.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]

        # =========================
        # Platform audience analytics
        # =========================

        customer_stats = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN gender = 'male' THEN 1 ELSE 0 END) AS males,
                SUM(CASE WHEN gender = 'female' THEN 1 ELSE 0 END) AS females,
                SUM(CASE
                    WHEN gender IS NULL OR gender = ''
                    THEN 1 ELSE 0
                END) AS unknown
            FROM customers
        """).fetchone()

        merchant_stats = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN gender = 'male' THEN 1 ELSE 0 END) AS males,
                SUM(CASE WHEN gender = 'female' THEN 1 ELSE 0 END) AS females,
                SUM(CASE
                    WHEN gender IS NULL OR gender = ''
                    THEN 1 ELSE 0
                END) AS unknown
            FROM merchants
        """).fetchone()

        total_customers = customer_stats["total"] or 0
        total_merchants = merchant_stats["total"] or 0

        male_customers = customer_stats["males"] or 0
        female_customers = customer_stats["females"] or 0
        unknown_customers = customer_stats["unknown"] or 0

        male_merchants = merchant_stats["males"] or 0
        female_merchants = merchant_stats["females"] or 0
        unknown_merchants = merchant_stats["unknown"] or 0

        total_registered = total_customers + total_merchants

        total_males = male_customers + male_merchants
        total_females = female_customers + female_merchants
        total_unknown_gender = unknown_customers + unknown_merchants

        total_followers = conn.execute("""
            SELECT COUNT(*) FROM platform_followers
        """).fetchone()[0] or 0

        country_stats = conn.execute("""
            SELECT
                country_code,
                COUNT(*) AS total
            FROM (
                SELECT country_code FROM customers
                WHERE country_code IS NOT NULL
                  AND country_code != ''

                UNION ALL

                SELECT country_code FROM merchants
                WHERE country_code IS NOT NULL
                  AND country_code != ''
            )
            GROUP BY country_code
            ORDER BY total DESC, country_code
        """).fetchall()

        registration_trend = conn.execute("""
            SELECT
                date(created_at) AS registration_date,
                COUNT(*) AS total
            FROM (
                SELECT created_at FROM customers
                UNION ALL
                SELECT created_at FROM merchants
            )
            WHERE date(created_at) >= date('now', '-29 days')
            GROUP BY date(created_at)
            ORDER BY registration_date ASC
        """).fetchall()

    return render_template(
        "admin_stats.html",
        total_orders=total_orders,
        total_sales=currency_stats,
        total_merchants=total_merchants,
        total_products=total_products,
        total_commission=total_commission,
        merchant_due=merchant_due,
        currency_stats=currency_stats,
        merchant_reports=merchant_reports,

        # Audience analytics
        total_registered=total_registered,
        total_customers=total_customers,
        total_males=total_males,
        total_females=total_females,
        total_unknown_gender=total_unknown_gender,
        male_customers=male_customers,
        female_customers=female_customers,
        unknown_customers=unknown_customers,
        male_merchants=male_merchants,
        female_merchants=female_merchants,
        unknown_merchants=unknown_merchants,
        total_followers=total_followers,
        country_stats=country_stats,
        registration_trend=registration_trend
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

        def ad_size(name, default, minimum, maximum):
            try:
                value = int(request.form.get(name, default))
                return max(minimum, min(value, maximum))
            except (ValueError, TypeError):
                return default

        card_width = ad_size("card_width", 80, 1, 1000)
        card_height = ad_size("card_height", 50, 1, 1000)
        image_width = ad_size("image_width", 74, 1, 1000)
        image_height = ad_size("image_height", 30, 1, 1000)

        image_file = request.files.get("image")

        if not title:
            return "اسم الإعلان مطلوب ❌", 400

        try:
            sort_order = int(sort_order)
        except (ValueError, TypeError):
            sort_order = 0

        image_name = None

        if image_file and image_file.filename:
            import os
            from werkzeug.utils import secure_filename
            from PIL import Image

            filename = secure_filename(image_file.filename)
            ext = os.path.splitext(filename)[1].lower()
            allowed_ext = {".jpg", ".jpeg", ".png", ".webp"}

            if ext not in allowed_ext:
                return "صيغة الصورة غير مدعومة ❌", 400

            try:
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

            ads_folder = Path(ADS_DIR)
            ads_folder.mkdir(parents=True, exist_ok=True)

            with db() as conn:
                cursor = conn.execute("""
                    INSERT INTO ads
                    (title, image, category, link, active, sort_order,
                     card_width, card_height, image_width, image_height)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """, (
                    title,
                    None,
                    category,
                    link,
                    sort_order,
                    card_width,
                    card_height,
                    image_width,
                    image_height
                ))

                ad_id = cursor.lastrowid

            image_name = f"ad_{ad_id}{ext}"
            image_file.stream.seek(0)
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
                    (title, image, category, link, active, sort_order,
                     card_width, card_height, image_width, image_height)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """, (
                    title,
                    None,
                    category,
                    link,
                    sort_order,
                    card_width,
                    card_height,
                    image_width,
                    image_height
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

        # إعادة ترقيم الإعلانات المتبقية بعد الحذف
        remaining_ads = conn.execute("""
            SELECT id
            FROM ads
            ORDER BY sort_order ASC, id ASC
        """).fetchall()

        for new_order, row in enumerate(remaining_ads, start=1):
            conn.execute(
                "UPDATE ads SET sort_order = ? WHERE id = ?",
                (new_order, row["id"])
            )

        if ad["image"]:
            image_path = Path(ADS_DIR) / ad["image"]
            if image_path.exists():
                image_path.unlink()

    return redirect("/admin")


@app.route("/admin/ad/<int:ad_id>/move", methods=["POST"])
def move_ad(ad_id):
    if not session.get("owner"):
        return redirect("/owner/login")

    direction = request.form.get("direction", "").strip()

    if direction not in {"up", "down"}:
        return "اتجاه التحريك غير صالح ❌", 400

    with db() as conn:
        ads = conn.execute("""
            SELECT id
            FROM ads
            ORDER BY sort_order ASC, id ASC
        """).fetchall()

        if not ads:
            return redirect("/admin/ads")

        # توحيد ترتيب جميع الإعلانات أولاً
        ids = [row["id"] for row in ads]

        for order, row_id in enumerate(ids, start=1):
            conn.execute(
                "UPDATE ads SET sort_order = ? WHERE id = ?",
                (order, row_id)
            )

        if ad_id not in ids:
            return "الإعلان غير موجود ❌", 404

        current_index = ids.index(ad_id)

        if direction == "up":
            target_index = current_index - 1
        else:
            target_index = current_index + 1

        # إذا كان الإعلان في أول/آخر القائمة
        if target_index < 0 or target_index >= len(ids):
            return redirect("/admin/ads")

        current_id = ids[current_index]
        target_id = ids[target_index]

        current_order = current_index + 1
        target_order = target_index + 1

        # تبديل الترتيب
        conn.execute(
            "UPDATE ads SET sort_order = ? WHERE id = ?",
            (target_order, current_id)
        )

        conn.execute(
            "UPDATE ads SET sort_order = ? WHERE id = ?",
            (current_order, target_id)
        )

    return redirect("/admin/ads")


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

            def ad_size(name, default, minimum, maximum):
                try:
                    value = int(request.form.get(name, default))
                    return max(minimum, min(value, maximum))
                except (ValueError, TypeError):
                    return default

            card_width = ad_size("card_width", ad["card_width"] or 80, 1, 1000)
            card_height = ad_size("card_height", ad["card_height"] or 50, 1, 1000)
            image_width = ad_size("image_width", ad["image_width"] or 74, 1, 1000)
            image_height = ad_size("image_height", ad["image_height"] or 30, 1, 1000)

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

                    try:
                        from PIL import Image
                        image_file.stream.seek(0)
                        with Image.open(image_file.stream) as img:
                            img.verify()
                        image_file.stream.seek(0)
                        with Image.open(image_file.stream) as img:
                            if img.format.lower() not in {"jpeg", "png", "webp"}:
                                return "محتوى الصورة غير مدعوم ❌", 400
                    except Exception:
                        return "ملف الصورة غير صالح ❌", 400

                    image_name = f"ad_{ad_id}{ext}"

                    ads_folder = Path(ADS_DIR)
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
                SET title = ?, category = ?, link = ?, sort_order = ?,
                    card_width = ?, card_height = ?,
                    image_width = ?, image_height = ?
                WHERE id = ?
            """, (
                title,
                category,
                link,
                sort_order,
                card_width,
                card_height,
                image_width,
                image_height,
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

        pending_phone_recovery = conn.execute(
            "SELECT COUNT(*) FROM phone_recovery_requests WHERE status = 'جديد'"
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
        total_sales=currency_sales,
        total_merchants=total_merchants,
        total_products=total_products,
        total_views=total_views,
        total_followers=total_followers,
        total_likes=total_likes,
        total_customers=total_customers,
        pending_phone_recovery=pending_phone_recovery
    )
@app.route("/admin/phone-recovery")
def admin_phone_recovery():
    if not session.get("owner"):
        return redirect("/owner/login")

    status_filter = request.args.get("status", "").strip()

    with db() as conn:
        query = """
            SELECT *
            FROM phone_recovery_requests
        """
        params = ()

        if status_filter:
            query += " WHERE status = ?"
            params = (status_filter,)

        query += " ORDER BY created_at DESC, id DESC"

        requests = conn.execute(query, params).fetchall()

    return render_template(
        "admin_phone_recovery.html",
        requests=requests,
        status_filter=status_filter
    )


@app.route("/admin/phone-recovery/<int:request_id>/action", methods=["POST"])
def admin_phone_recovery_action(request_id):
    if not session.get("owner"):
        return redirect("/owner/login")

    token = request.form.get("csrf_token", "")
    session_token = session.get("csrf_token", "")

    if not session_token or not token or not hmac.compare_digest(token, session_token):
        return "طلب غير صالح - CSRF", 400

    action = request.form.get("action", "").strip()
    admin_note = request.form.get("admin_note", "").strip()

    allowed_actions = {
        "review": "قيد المراجعة",
        "approve": "تمت الموافقة",
        "reject": "مرفوض",
    }

    if action not in allowed_actions:
        return "إجراء غير صالح", 400

    with db() as conn:
        recovery_request = conn.execute("""
            SELECT *
            FROM phone_recovery_requests
            WHERE id = ?
        """, (request_id,)).fetchone()

        if recovery_request is None:
            return "طلب الاستعادة غير موجود", 404

        if recovery_request["status"] in {"تمت الموافقة", "مرفوض"}:
            return redirect("/admin/phone-recovery")

        if action == "review":
            conn.execute("""
                UPDATE phone_recovery_requests
                SET status = 'قيد المراجعة',
                    admin_note = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (admin_note or "تم تحويل الطلب إلى قيد المراجعة.", request_id))

            return redirect("/admin/phone-recovery")

        role = recovery_request["role"]
        account_id = recovery_request["matched_account_id"]
        requested_phone = recovery_request["phone"]

        if role not in {"customer", "merchant"}:
            return "نوع الحساب غير صالح", 400

        if not account_id:
            return "الحساب المطابق غير محدد", 400

        table = "customers" if role == "customer" else "merchants"

        account = conn.execute(
            f"""
            SELECT id, phone, account_status
            FROM {table}
            WHERE id = ?
            """,
            (account_id,)
        ).fetchone()

        if account is None:
            return "الحساب المطابق غير موجود", 404

        if account["phone"] != requested_phone:
            return "رقم الهاتف الحالي للحساب لا يطابق رقم طلب الاستعادة", 409

        if action == "reject":
            conn.execute("""
                UPDATE phone_recovery_requests
                SET status = 'مرفوض',
                    admin_note = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                admin_note or "تم رفض طلب استعادة الرقم بعد المراجعة.",
                request_id,
            ))

            return redirect("/admin/phone-recovery")

        # الموافقة:
        # نحافظ على الحساب القديم وسجله، ونحرر الرقم الأصلي
        # بوضع قيمة داخلية فريدة في حقل phone.
        internal_phone = (
            f"__recovered__{role}_{account_id}_"
            f"{secrets.token_hex(12)}"
        )

        conn.execute(
            f"""
            UPDATE {table}
            SET account_status = 'disabled',
                old_phone = phone,
                phone = ?
            WHERE id = ?
            """,
            (internal_phone, account_id)
        )

        conn.execute("""
            UPDATE phone_recovery_requests
            SET status = 'تمت الموافقة',
                admin_note = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            admin_note or "تمت الموافقة على الطلب وإيقاف الحساب القديم وتحرير الرقم للتسجيل من جديد.",
            request_id,
        ))

    return redirect("/admin/phone-recovery")


@app.route("/admin/ads")
def admin_ads():
    if not session.get("owner"):
        return redirect("/owner/login")

    with db() as conn:
        ads = conn.execute("""
            SELECT *
            FROM ads
            ORDER BY sort_order ASC, id ASC
        """).fetchall()

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

    if not math.isfinite(commission) or commission < 0 or commission > 100:
        return "نسبة العمولة يجب أن تكون رقمًا بين 0 و100 ❌", 400

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

        if merchant["account_status"] == "disabled":
            return render_template(
                "merchant_login.html",
                countries=countries,
                error="هذا الحساب معطّل حاليًا. إذا كنت تعتقد أن الرقم يخصك، يمكنك تقديم طلب استعادة الرقم."
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

@app.route("/store/<int:merchant_id>")
def public_store(merchant_id):

    with db() as conn:

        merchant = conn.execute(
            """
            SELECT id, name
            FROM merchants
            WHERE id = ?
              AND status = 'approved'
            """,
            (merchant_id,)
        ).fetchone()

        if merchant is None:
            return "المتجر غير متاح", 404

        products = conn.execute(
            """
            SELECT *
            FROM products
            WHERE merchant_id = ?
              AND status = 'active'
            ORDER BY id DESC
            """,
            (merchant_id,)
        ).fetchall()

    return render_template(
        "public_store.html",
        merchant=merchant,
        products=products
    )


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
              AND merchant_orders.viewed = 0
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

            # =========================
            # حفظ صورة المتجر
            # =========================
            image_file = request.files.get("store_image")

            if image_file and image_file.filename:
                original_filename = secure_filename(image_file.filename)

                if not original_filename:
                    return "اسم صورة المتجر غير صالح ❌", 400

                allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
                ext = os.path.splitext(original_filename)[1].lower()

                if ext not in allowed_extensions:
                    return "صيغة الصورة غير مدعومة. استخدم JPG أو PNG أو WEBP ❌", 400

                filename = f"merchant_{merchant_id}_store{ext}"

                image_file.save(os.path.join(UPLOADS_DIR, filename))

                conn.execute("""
                    UPDATE merchants
                    SET store_image = ?
                    WHERE id = ?
                """, (filename, merchant_id))

                conn.commit()

                return redirect("/merchant/settings")

            # =========================
            # حفظ موقع المتجر
            # =========================
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

                conn.commit()

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
        price_raw = request.form.get("price", "").strip()
        original_price_raw = request.form.get("original_price", "").strip()
        description = request.form["description"].strip()
        category = request.form.get("category", "أخرى").strip()

        # المقاسات متاحة فقط للملابس والأحذية.
        # أي صنف آخر يستخدم المخزون العادي بدون مقاسات.
        size_categories = {"أزياء", "ملابس", "أحذية"}

        has_variants = (
            request.form.get("has_variants") == "1"
            and category in size_categories
        )

        # المخزون العادي يستخدم فقط عندما لا توجد متغيرات
        stock = 0

        if not has_variants:
            stock_raw = request.form.get("stock", "").strip()

            try:
                stock = int(stock_raw)
                if stock < 0:
                    raise ValueError
            except (TypeError, ValueError):
                return "المخزون يجب أن يكون عددًا صحيحًا وأكبر من أو يساوي صفر ❌", 400

        try:
            price = float(price_raw)
            if price < 0:
                raise ValueError
        except (TypeError, ValueError):
            return "السعر يجب أن يكون رقمًا صحيحًا أو عشريًا وأكبر من أو يساوي صفر ❌", 400

        original_price = None

        if original_price_raw:
            try:
                original_price = float(original_price_raw)

                if original_price <= price:
                    raise ValueError

            except (TypeError, ValueError):
                return "السعر قبل الخصم يجب أن يكون أكبر من السعر الحالي ❌", 400

        currency = request.form.get("currency", "YER").strip()

        # إعدادات صورة صفحة التفاصيل
        image_zoom = request.form.get("image_zoom", "1")
        image_x = request.form.get("image_x", "0")
        image_y = request.form.get("image_y", "0")

        # إعدادات صورة كرت الصفحة الرئيسية
        card_image_zoom = request.form.get("card_image_zoom", "1")
        card_image_x = request.form.get("card_image_x", "0")
        card_image_y = request.form.get("card_image_y", "0")

        allowed_currencies = {
            "YER", "SAR", "USD", "AED",
            "EGP", "KWD", "EUR", "GBP", "OTHER"
        }

        if currency not in allowed_currencies:
            currency = "YER"

        # قراءة متغيرات المنتج عند تفعيلها
        variants = []

        if has_variants:

            colors = request.form.getlist("variant_color[]")
            sizes = request.form.getlist("variant_size[]")
            stocks = request.form.getlist("variant_stock[]")

            if not colors or not sizes or not stocks:
                return "أنشئ خيارات اللون والمقاس وحدد المخزون لكل تركيبة ❌", 400

            if not (len(colors) == len(sizes) == len(stocks)):
                return "بيانات خيارات المنتج غير مكتملة ❌", 400

            seen_variants = set()
            variants_total = 0

            for color_raw, size_raw, variant_stock_raw in zip(
                colors,
                sizes,
                stocks
            ):
                color = color_raw.strip()
                size = size_raw.strip()

                if not color:
                    return "يجب إدخال اللون لكل تركيبة ❌", 400

                if not size:
                    return "يجب إدخال المقاس لكل تركيبة ❌", 400

                try:
                    variant_stock = int(variant_stock_raw)

                    if variant_stock < 0:
                        raise ValueError

                except (TypeError, ValueError):
                    return "مخزون كل تركيبة يجب أن يكون عددًا صحيحًا وأكبر من أو يساوي صفر ❌", 400

                variant_key = (color.casefold(), size.casefold())

                if variant_key in seen_variants:
                    return f"اللون والمقاس مكرران: {color} / {size} ❌", 400

                seen_variants.add(variant_key)

                variants.append({
                    "color": color,
                    "size": size,
                    "stock": variant_stock
                })

                variants_total += variant_stock

            if not variants:
                return "أنشئ تركيبة واحدة على الأقل للمنتج ❌", 400

            # إجمالي المخزون = مجموع مخزون جميع تركيبات اللون والمقاس
            stock = variants_total

        # =========================
        # صور المنتج — حد أقصى 4 صور
        # =========================

        product_image_files = [
            file
            for file in request.files.getlist("product_images[]")
            if file and file.filename
        ]

        # توافق مع أي نموذج قديم يرسل image
        if not product_image_files:
            old_image = request.files.get("image")
            if old_image and old_image.filename:
                product_image_files = [old_image]

        if not product_image_files:
            return "يجب إضافة صورة واحدة على الأقل للمنتج ❌", 400

        if len(product_image_files) > 4:
            return "يمكن إضافة 4 صور كحد أقصى لكل منتج ❌", 400

        upload_dir = UPLOADS_DIR
        processed_product_images = []

        allowed_formats = {
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".png": "PNG",
            ".webp": "WEBP",
        }

        # فحص جميع الصور أولًا قبل حفظ أي صورة
        for image_file in product_image_files:

            original_filename = secure_filename(image_file.filename)
            ext = os.path.splitext(original_filename)[1].lower()

            if not original_filename or ext not in allowed_formats:
                return (
                    "صيغة إحدى الصور غير مدعومة. استخدم JPG أو PNG أو WEBP ❌",
                    400
                )

            try:
                from PIL import Image

                image_file.stream.seek(0)

                with Image.open(image_file.stream) as img:
                    img.verify()

                image_file.stream.seek(0)

                with Image.open(image_file.stream) as img:
                    if img.format != allowed_formats[ext]:
                        return "محتوى إحدى الصور لا يطابق امتداد الملف ❌", 400

            except Exception:
                return "أحد الملفات المرفوعة ليس صورة صالحة ❌", 400

            finally:
                image_file.stream.seek(0)

        # معالجة الصور بعد نجاح فحصها كلها
        for image_file in product_image_files:

            image_file.stream.seek(0)

            try:
                processed_name = process_product_image(
                    image_file.stream,
                    upload_dir
                )

            except Exception:
                return "تعذر معالجة إحدى الصور المرفوعة ❌", 400

            if not processed_name:
                return "تعذر حفظ إحدى صور المنتج ❌", 400

            processed_product_images.append(processed_name)

        # الصورة الأولى تبقى الصورة الرئيسية القديمة للمنتج
        image_name = processed_product_images[0]

        with db() as conn:

            cursor = conn.execute("""
                INSERT INTO products
                (
                    name,
                    price,
                    original_price,
                    description,
                    stock,
                    image,
                    merchant_id,
                    category,
                    currency,
                    image_zoom,
                    image_x,
                    image_y,
                    card_image_zoom,
                    card_image_x,
                    card_image_y
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name,
                price,
                original_price,
                description,
                stock,
                image_name,
                merchant_id,
                category,
                currency,
                image_zoom,
                image_x,
                image_y,
                card_image_zoom,
                card_image_x,
                card_image_y
            ))

            product_id = cursor.lastrowid

            # حفظ صور المنتج الإضافية بالترتيب
            conn.executemany("""
                INSERT INTO product_images
                (
                    product_id,
                    image,
                    sort_order
                )
                VALUES (?, ?, ?)
            """, [
                (
                    product_id,
                    image_name,
                    0
                )
            ] + [
                (
                    product_id,
                    image_filename,
                    index
                )
                for index, image_filename
                in enumerate(processed_product_images[1:], start=1)
            ])

            # 🔔 إشعار متابعي MODER ONE عند إضافة منتج جديد
            followers = conn.execute("""
                SELECT customer_id
                FROM platform_followers
            """).fetchall()

            for follower in followers:
                follower_customer_id = follower["customer_id"]

                conn.execute("""
                    INSERT INTO notifications
                    (
                        customer_id,
                        message,
                        is_read,
                        created_at
                    )
                    VALUES (?, ?, 0, CURRENT_TIMESTAMP)
                """, (
                    follower_customer_id,
                    f"🛍️ منتج جديد متاح الآن على MODER ONE: {name}"
                ))

                send_push_notification(
                    customer_id=follower_customer_id,
                    title="MODER ONE",
                    body="تمت إضافة منتج جديد إلى المتجر.",
                    url=f"/product/{product_id}"
                )

            if has_variants:

                conn.executemany("""
                    INSERT INTO product_variants
                    (
                        product_id,
                        color,
                        size,
                        stock
                    )
                    VALUES (?, ?, ?, ?)
                """, [
                    (
                        product_id,
                        variant["color"],
                        variant["size"],
                        variant["stock"]
                    )
                    for variant in variants
                ])

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
            price_raw = request.form.get("price", "").strip()
            original_price_raw = request.form.get("original_price", "").strip()
            description = request.form["description"].strip()

            category = request.form.get(
                "category",
                product["category"] or "أخرى"
            ).strip()

            # المقاسات متاحة فقط للملابس والأحذية.
            # أي صنف آخر يعود تلقائيًا إلى المخزون العادي.
            size_categories = {"أزياء", "ملابس", "أحذية"}

            has_variants = (
                request.form.get("has_variants") == "1"
                and category in size_categories
            )

            try:
                price = float(price_raw)
                if price < 0:
                    raise ValueError
            except (TypeError, ValueError):
                return "السعر يجب أن يكون رقمًا صحيحًا أو عشريًا وأكبر من أو يساوي صفر ❌", 400

            original_price = None

            if original_price_raw:
                try:
                    original_price = float(original_price_raw)
                    if original_price <= price:
                        raise ValueError
                except (TypeError, ValueError):
                    return "السعر قبل الخصم يجب أن يكون أكبر من السعر الحالي ❌", 400

            variants = []
            variants_total = 0

            if has_variants:

                colors = request.form.getlist("variant_color[]")
                sizes = request.form.getlist("variant_size[]")
                stocks = request.form.getlist("variant_stock[]")

                if not colors or not sizes or not stocks:
                    return "يجب إضافة لون ومقاس وكمية واحدة على الأقل ❌", 400

                if not (
                    len(colors) == len(sizes)
                    and len(sizes) == len(stocks)
                ):
                    return "بيانات الألوان والمقاسات والكميات غير متطابقة ❌", 400

                seen = set()

                for color_raw, size_raw, stock_raw in zip(
                    colors,
                    sizes,
                    stocks
                ):
                    color = color_raw.strip()
                    size = size_raw.strip()

                    if not color:
                        return "اسم اللون لا يمكن أن يكون فارغًا ❌", 400

                    if not size:
                        return "اسم المقاس لا يمكن أن يكون فارغًا ❌", 400

                    try:
                        variant_stock = int(stock_raw)
                        if variant_stock < 0:
                            raise ValueError
                    except (TypeError, ValueError):
                        return "كمية كل لون ومقاس يجب أن تكون عددًا صحيحًا وأكبر من أو تساوي صفر ❌", 400

                    key = (
                        color.casefold(),
                        size.casefold()
                    )

                    if key in seen:
                        return (
                            f"لا يمكن تكرار نفس اللون والمقاس: "
                            f"{color} / {size} ❌"
                        ), 400

                    seen.add(key)

                    variants.append({
                        "color": color,
                        "size": size,
                        "stock": variant_stock
                    })

                    variants_total += variant_stock

                stock = variants_total

            else:

                stock_raw = request.form.get("stock", "").strip()

                try:
                    stock = int(stock_raw)
                    if stock < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    return "المخزون يجب أن يكون عددًا صحيحًا وأكبر من أو يساوي صفر ❌", 400

            image_zoom = request.form.get(
                "image_zoom",
                product["image_zoom"] or 1
            )

            image_x = request.form.get(
                "image_x",
                product["image_x"] or 0
            )

            image_y = request.form.get(
                "image_y",
                product["image_y"] or 0
            )

            # إعدادات صورة كرت الصفحة الرئيسية
            card_image_zoom = request.form.get(
                "card_image_zoom",
                product["card_image_zoom"] or 1
            )

            card_image_x = request.form.get(
                "card_image_x",
                product["card_image_x"] or 0
            )

            card_image_y = request.form.get(
                "card_image_y",
                product["card_image_y"] or 0
            )

            currency = request.form.get(
                "currency",
                product["currency"] or "YER"
            ).strip()

            allowed_currencies = {
                "YER", "SAR", "USD", "AED",
                "EGP", "KWD", "EUR", "GBP", "OTHER"
            }

            if currency not in allowed_currencies:
                currency = "YER"

            image_name = product["image"]

            image = request.files.get("image")

            if image and image.filename:

                original_filename = secure_filename(image.filename)
                ext = os.path.splitext(original_filename)[1].lower()

                upload_dir = UPLOADS_DIR

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

                        if (
                            ext not in format_map
                            or img.format != format_map[ext]
                        ):
                            return "محتوى الصورة لا يطابق امتداد الملف ❌", 400

                except Exception:
                    return "الملف المرفوع ليس صورة صالحة ❌", 400

                finally:
                    image.stream.seek(0)

                try:
                    image_name = process_product_image(
                        image.stream,
                        upload_dir
                    )
                except Exception:
                    return "تعذر معالجة الصورة المرفوعة ❌", 400

            conn.execute("""
                UPDATE products
                SET name = ?,
                    price = ?,
                    original_price = ?,
                    description = ?,
                    stock = ?,
                    image = ?,
                    category = ?,
                    currency = ?,
                    image_zoom = ?,
                    image_x = ?,
                    image_y = ?,
                    card_image_zoom = ?,
                    card_image_x = ?,
                    card_image_y = ?
                WHERE id = ?
                AND merchant_id = ?
            """, (
                name,
                price,
                original_price,
                description,
                stock,
                image_name,
                category,
                currency,
                image_zoom,
                image_x,
                image_y,
                card_image_zoom,
                card_image_x,
                card_image_y,
                product_id,
                merchant_id
            ))

            if has_variants:

                # نحافظ على variant_id للتركيبات الموجودة.
                # هذا مهم لأن السلة والطلبات السابقة تعتمد على variant_id.
                existing_variants = conn.execute("""
                    SELECT
                        id,
                        color,
                        size
                    FROM product_variants
                    WHERE product_id = ?
                    ORDER BY id ASC
                """, (product_id,)).fetchall()

                existing_map = {
                    (
                        row["color"].casefold(),
                        row["size"].casefold()
                    ): row["id"]
                    for row in existing_variants
                    if row["color"] is not None and row["size"] is not None
                }

                submitted_keys = set()

                for variant in variants:

                    key = (
                        variant["color"].casefold(),
                        variant["size"].casefold()
                    )

                    submitted_keys.add(key)

                    existing_id = existing_map.get(key)

                    if existing_id is not None:

                        conn.execute("""
                            UPDATE product_variants
                            SET color = ?,
                                size = ?,
                                stock = ?
                            WHERE id = ?
                            AND product_id = ?
                        """, (
                            variant["color"],
                            variant["size"],
                            variant["stock"],
                            existing_id,
                            product_id
                        ))

                    else:

                        conn.execute("""
                            INSERT INTO product_variants
                            (
                                product_id,
                                color,
                                size,
                                stock
                            )
                            VALUES (?, ?, ?, ?)
                        """, (
                            product_id,
                            variant["color"],
                            variant["size"],
                            variant["stock"]
                        ))

                # التركيبات التي أزالها التاجر من الواجهة:
                # لا نحذفها حتى لا نكسر الطلبات السابقة.
                # نجعل مخزونها صفرًا فقط، فتختفي عمليًا من الخيارات المتاحة.
                for existing in existing_variants:

                    key = (
                        existing["color"].casefold(),
                        existing["size"].casefold()
                    )

                    if key not in submitted_keys:

                        conn.execute("""
                            UPDATE product_variants
                            SET stock = 0
                            WHERE id = ?
                            AND product_id = ?
                        """, (
                            existing["id"],
                            product_id
                        ))

            else:

                # إذا عاد التاجر إلى منتج عادي بدون ألوان ومقاسات،
                # نجعل المتغيرات غير متاحة بدل حذفها حفاظًا على الطلبات السابقة.
                conn.execute("""
                    UPDATE product_variants
                    SET stock = 0
                    WHERE product_id = ?
                """, (product_id,))

            return redirect("/merchant/dashboard")

        variants = conn.execute("""
            SELECT
                id,
                product_id,
                color,
                size,
                stock
            FROM product_variants
            WHERE product_id = ?
            ORDER BY id ASC
        """, (product_id,)).fetchall()

    product_images = conn.execute("""
        SELECT
            id,
            product_id,
            image,
            sort_order,
            created_at
        FROM product_images
        WHERE product_id = ?
        ORDER BY sort_order ASC, id ASC
    """, (product_id,)).fetchall()

    # توافق مع المنتجات القديمة التي لديها صورة في products.image فقط
    if not product_images and product["image"]:
        product_images = [{
            "id": None,
            "product_id": product_id,
            "image": product["image"],
            "sort_order": 0,
            "created_at": None
        }]

    return render_template(
        "edit_product.html",
        product=product,
        variants=variants,
        product_images=product_images
    )


# =========================
# إدارة صور المنتج
# =========================

@app.route(
    "/merchant/product/<int:product_id>/images",
    methods=["POST"]
)
def manage_product_images(product_id):

    if not merchant_is_active():
        return redirect("/merchant/login")

    merchant_id = session.get("merchant_id")

    if not merchant_id:
        return redirect("/merchant/login")

    with db() as conn:

        product = conn.execute("""
            SELECT id, image
            FROM products
            WHERE id = ?
            AND merchant_id = ?
        """, (product_id, merchant_id)).fetchone()

        if not product:
            return "المنتج غير موجود ❌", 404

        # مزامنة المنتجات القديمة التي لديها products.image فقط
        current_images = conn.execute("""
            SELECT id, image, sort_order
            FROM product_images
            WHERE product_id = ?
            ORDER BY sort_order ASC, id ASC
        """, (product_id,)).fetchall()

        if not current_images and product["image"]:

            conn.execute("""
                INSERT INTO product_images
                (
                    product_id,
                    image,
                    sort_order
                )
                VALUES (?, ?, 0)
            """, (
                product_id,
                product["image"]
            ))

            conn.commit()

            current_images = conn.execute("""
                SELECT id, image, sort_order
                FROM product_images
                WHERE product_id = ?
                ORDER BY sort_order ASC, id ASC
            """, (product_id,)).fetchall()

        action = request.form.get("action", "add").strip()

        # =========================
        # حذف صورة
        # =========================
        if action == "delete":

            try:
                image_id = int(request.form.get("image_id", ""))
            except (ValueError, TypeError):
                return "معرّف الصورة غير صحيح ❌", 400

            image_row = conn.execute("""
                SELECT id, image
                FROM product_images
                WHERE id = ?
                AND product_id = ?
            """, (image_id, product_id)).fetchone()

            if not image_row:
                return "الصورة غير موجودة ❌", 404

            if len(current_images) <= 1:
                return "لا يمكن حذف آخر صورة للمنتج ❌", 400

            conn.execute("""
                DELETE FROM product_images
                WHERE id = ?
                AND product_id = ?
            """, (image_id, product_id))

            remaining = conn.execute("""
                SELECT id, image, sort_order
                FROM product_images
                WHERE product_id = ?
                ORDER BY sort_order ASC, id ASC
            """, (product_id,)).fetchall()

            for index, image in enumerate(remaining):
                conn.execute("""
                    UPDATE product_images
                    SET sort_order = ?
                    WHERE id = ?
                    AND product_id = ?
                """, (
                    index,
                    image["id"],
                    product_id
                ))

            main_image = remaining[0]["image"]

            conn.execute("""
                UPDATE products
                SET image = ?
                WHERE id = ?
                AND merchant_id = ?
            """, (
                main_image,
                product_id,
                merchant_id
            ))

            conn.commit()

            return redirect(
                f"/merchant/product/{product_id}/edit#product-images"
            )

        # =========================
        # جعل الصورة رئيسية
        # =========================
        if action == "primary":

            try:
                image_id = int(request.form.get("image_id", ""))
            except (ValueError, TypeError):
                return "معرّف الصورة غير صحيح ❌", 400

            selected = conn.execute("""
                SELECT id, image
                FROM product_images
                WHERE id = ?
                AND product_id = ?
            """, (image_id, product_id)).fetchone()

            if not selected:
                return "الصورة غير موجودة ❌", 404

            images = conn.execute("""
                SELECT id, image
                FROM product_images
                WHERE product_id = ?
                ORDER BY sort_order ASC, id ASC
            """, (product_id,)).fetchall()

            ordered = [selected] + [
                image
                for image in images
                if image["id"] != selected["id"]
            ]

            for index, image in enumerate(ordered):
                conn.execute("""
                    UPDATE product_images
                    SET sort_order = ?
                    WHERE id = ?
                    AND product_id = ?
                """, (
                    index,
                    image["id"],
                    product_id
                ))

            conn.execute("""
                UPDATE products
                SET image = ?
                WHERE id = ?
                AND merchant_id = ?
            """, (
                selected["image"],
                product_id,
                merchant_id
            ))

            conn.commit()

            return redirect(
                f"/merchant/product/{product_id}/edit#product-images"
            )

        # =========================
        # إعادة ترتيب الصور
        # =========================
        if action == "reorder":

            try:
                image_id = int(request.form.get("image_id", ""))
            except (ValueError, TypeError):
                return "معرّف الصورة غير صحيح ❌", 400

            direction = request.form.get("direction", "").strip()

            images = conn.execute("""
                SELECT id, image, sort_order
                FROM product_images
                WHERE product_id = ?
                ORDER BY sort_order ASC, id ASC
            """, (product_id,)).fetchall()

            current_index = next(
                (
                    index
                    for index, image in enumerate(images)
                    if image["id"] == image_id
                ),
                None
            )

            if current_index is None:
                return "الصورة غير موجودة ❌", 404

            target_index = current_index

            if direction == "up" and current_index > 0:
                target_index = current_index - 1

            elif (
                direction == "down"
                and current_index < len(images) - 1
            ):
                target_index = current_index + 1

            else:
                return redirect(
                    f"/merchant/product/{product_id}/edit#product-images"
                )

            ordered_images = list(images)

            ordered_images[current_index], ordered_images[target_index] = (
                ordered_images[target_index],
                ordered_images[current_index]
            )

            for index, image in enumerate(ordered_images):

                conn.execute("""
                    UPDATE product_images
                    SET sort_order = ?
                    WHERE id = ?
                    AND product_id = ?
                """, (
                    index,
                    image["id"],
                    product_id
                ))

            # أول صورة دائمًا هي الصورة الرئيسية
            main_image = ordered_images[0]["image"]

            conn.execute("""
                UPDATE products
                SET image = ?
                WHERE id = ?
                AND merchant_id = ?
            """, (
                main_image,
                product_id,
                merchant_id
            ))

            conn.commit()

            return redirect(
                f"/merchant/product/{product_id}/edit#product-images"
            )

        # =========================
        # إضافة صور جديدة
        # =========================
        new_files = [
            file
            for file in request.files.getlist("product_images[]")
            if file and file.filename
        ]

        total_after_add = len(current_images) + len(new_files)

        if total_after_add > 4:
            return "يمكن أن يحتوي المنتج على 4 صور كحد أقصى ❌", 400

        if not new_files:
            return redirect(
                f"/merchant/product/{product_id}/edit#product-images"
            )

        processed_images = []

        allowed_formats = {
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".png": "PNG",
            ".webp": "WEBP",
        }

        # فحص جميع الصور أولًا
        for image_file in new_files:

            original_filename = secure_filename(
                image_file.filename
            )

            ext = os.path.splitext(
                original_filename
            )[1].lower()

            if not original_filename or ext not in allowed_formats:
                return (
                    "صيغة إحدى الصور غير مدعومة. استخدم JPG أو PNG أو WEBP ❌",
                    400
                )

            try:
                from PIL import Image

                image_file.stream.seek(0)

                with Image.open(image_file.stream) as img:
                    img.verify()

                image_file.stream.seek(0)

                with Image.open(image_file.stream) as img:
                    if img.format != allowed_formats[ext]:
                        return (
                            "محتوى إحدى الصور لا يطابق امتداد الملف ❌",
                            400
                        )

            except Exception:
                return "أحد الملفات المرفوعة ليس صورة صالحة ❌", 400

            finally:
                image_file.stream.seek(0)

        # معالجة الصور بعد نجاح الفحص
        for image_file in new_files:

            image_file.stream.seek(0)

            try:
                processed_name = process_product_image(
                    image_file.stream,
                    UPLOADS_DIR
                )
            except Exception:
                return "تعذر معالجة إحدى الصور المرفوعة ❌", 400

            if not processed_name:
                return "تعذر حفظ إحدى صور المنتج ❌", 400

            processed_images.append(processed_name)

        next_order = len(current_images)

        for index, image_name in enumerate(processed_images):

            conn.execute("""
                INSERT INTO product_images
                (
                    product_id,
                    image,
                    sort_order
                )
                VALUES (?, ?, ?)
            """, (
                product_id,
                image_name,
                next_order + index
            ))

        # ضمان بقاء products.image مساويًا للصورة الرئيسية
        first_image = conn.execute("""
            SELECT image
            FROM product_images
            WHERE product_id = ?
            ORDER BY sort_order ASC, id ASC
            LIMIT 1
        """, (product_id,)).fetchone()

        if first_image:
            conn.execute("""
                UPDATE products
                SET image = ?
                WHERE id = ?
                AND merchant_id = ?
            """, (
                first_image["image"],
                product_id,
                merchant_id
            ))

        conn.commit()

    return redirect(
        f"/merchant/product/{product_id}/edit#product-images"
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
            used = conn.execute(
                "SELECT 1 FROM order_items WHERE product_id = ? LIMIT 1",
                (product_id,)
            ).fetchone()

            if used:
                conn.execute("""
                    UPDATE products
                    SET status = 'inactive'
                    WHERE id = ?
                    AND merchant_id = ?
                """, (product_id, merchant_id))
            else:
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

    variant_id_raw = request.form.get("variant_id", "").strip()
    selected_color = request.form.get("color", "").strip()
    selected_size = request.form.get("size", "").strip()

    try:
        variant_id = int(variant_id_raw) if variant_id_raw else 0
    except (TypeError, ValueError):
        return "خيار المنتج غير صالح ❌", 400

    with db() as conn:

        product = conn.execute("""
            SELECT
                id,
                stock,
                status,
                currency
            FROM products
            WHERE id = ?
        """, (product_id,)).fetchone()

        if product is None:
            return "المنتج غير موجود ❌", 404

        if product["status"] != "active":
            return "المنتج متوقف حاليًا ❌", 400

        variant_count = conn.execute("""
            SELECT COUNT(*)
            FROM product_variants
            WHERE product_id = ?
        """, (product_id,)).fetchone()[0]

        selected_variant = None

        if variant_count > 0:

            if variant_id <= 0:
                return "اختر اللون والمقاس أولًا ❌", 400

            selected_variant = conn.execute("""
                SELECT
                    id,
                    product_id,
                    color,
                    size,
                    stock
                FROM product_variants
                WHERE id = ?
                AND product_id = ?
            """, (variant_id, product_id)).fetchone()

            if selected_variant is None:
                return "خيار المنتج غير موجود ❌", 400

            if selected_variant["stock"] <= 0:
                return "هذا اللون والمقاس غير متوفر حاليًا ❌", 400

            if selected_color != selected_variant["color"]:
                return "اللون المحدد غير مطابق للخيار ❌", 400

            if selected_size != selected_variant["size"]:
                return "المقاس المحدد غير مطابق للخيار ❌", 400

        else:

            variant_id = 0
            selected_color = None
            selected_size = None

            if product["stock"] <= 0:
                return "المنتج غير متوفر حاليًا ❌", 400

        product_currency = (
            product["currency"] or "YER"
        ).strip().upper()

        cart_currencies = conn.execute("""
            SELECT DISTINCT
                UPPER(
                    TRIM(
                        COALESCE(products.currency, 'YER')
                    )
                ) AS currency
            FROM cart_items
            JOIN products
                ON products.id = cart_items.product_id
            WHERE cart_items.session_id = ?
        """, (cart_session_id,)).fetchall()

        if any(
            row["currency"] != product_currency
            for row in cart_currencies
        ):
            return (
                "لا يمكن إضافة منتج بعملة مختلفة إلى السلة. "
                "اختر منتجات بعملة واحدة فقط ❌",
                400
            )

        existing = conn.execute("""
            SELECT
                id,
                quantity
            FROM cart_items
            WHERE session_id = ?
            AND product_id = ?
            AND variant_id = ?
        """, (
            cart_session_id,
            product_id,
            variant_id
        )).fetchone()

        available_stock = (
            selected_variant["stock"]
            if selected_variant is not None
            else product["stock"]
        )

        if existing:

            new_quantity = existing["quantity"] + 1

            if new_quantity > available_stock:
                new_quantity = available_stock

            conn.execute("""
                UPDATE cart_items
                SET
                    quantity = ?,
                    color = ?,
                    size = ?
                WHERE id = ?
            """, (
                new_quantity,
                selected_color,
                selected_size,
                existing["id"]
            ))

        else:

            conn.execute("""
                INSERT INTO cart_items
                (
                    session_id,
                    product_id,
                    variant_id,
                    color,
                    size,
                    quantity
                )
                VALUES (?, ?, ?, ?, ?, 1)
            """, (
                cart_session_id,
                product_id,
                variant_id,
                selected_color,
                selected_size
            ))

    return redirect("/cart")


@app.route("/cart/update/<int:cart_item_id>", methods=["POST"])
def cart_update(cart_item_id):

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

        item = conn.execute("""
            SELECT
                cart_items.id,
                cart_items.product_id,
                cart_items.variant_id,
                products.stock AS product_stock,
                products.status
            FROM cart_items
            JOIN products
                ON products.id = cart_items.product_id
            WHERE cart_items.id = ?
            AND cart_items.session_id = ?
        """, (cart_item_id, cart_session_id)).fetchone()

        if item is None:
            return redirect("/cart")

        if item["status"] != "active":
            conn.execute("""
                DELETE FROM cart_items
                WHERE id = ?
                AND session_id = ?
            """, (cart_item_id, cart_session_id))
            return redirect("/cart")

        if item["variant_id"] > 0:

            variant = conn.execute("""
                SELECT stock
                FROM product_variants
                WHERE id = ?
                AND product_id = ?
            """, (
                item["variant_id"],
                item["product_id"]
            )).fetchone()

            if variant is None or variant["stock"] <= 0:
                conn.execute("""
                    DELETE FROM cart_items
                    WHERE id = ?
                    AND session_id = ?
                """, (cart_item_id, cart_session_id))
                return redirect("/cart")

            available_stock = variant["stock"]

        else:

            if item["product_stock"] <= 0:
                conn.execute("""
                    DELETE FROM cart_items
                    WHERE id = ?
                    AND session_id = ?
                """, (cart_item_id, cart_session_id))
                return redirect("/cart")

            available_stock = item["product_stock"]

        quantity = min(quantity, available_stock)

        conn.execute("""
            UPDATE cart_items
            SET quantity = ?
            WHERE id = ?
            AND session_id = ?
        """, (
            quantity,
            cart_item_id,
            cart_session_id
        ))

    return redirect("/cart")


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    customer_id = session.get("customer_id")
    if not customer_id:
        return redirect("/customer/login")

    cart_session_id = session.get("cart_session_id")

    if not cart_session_id:
        return redirect("/cart")

    with db() as conn:
        items = conn.execute("""
            SELECT
                cart_items.id AS cart_item_id,
                cart_items.quantity,
                cart_items.variant_id,
                cart_items.color,
                cart_items.size,
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
                    cart_items.id AS cart_item_id,
                    cart_items.quantity,
                    cart_items.variant_id,
                    cart_items.color,
                    cart_items.size,
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

            # سعر الشحن المعتمد هو سعر المدينة الذي حدده المالك.
            # GPS يستخدم لتسجيل موقع العميل وحساب المسافة كمعلومة فقط،
            # ولا يغيّر سعر الشحن ولا يضاعفه عند وجود أكثر من تاجر.

            shipping_cost = round(float(shipping["cost"]), 2)

            merchant_distances = []

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
                    merchant_distances.append(distance_km)

            shipping_distance_km = (
                round(max(merchant_distances), 2)
                if merchant_distances
                else 0.0
            )

            grand_total = round(total + shipping_cost, 2)

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

                if item["variant_id"] > 0:

                    variant = conn.execute("""
                        SELECT
                            id,
                            product_id,
                            color,
                            size,
                            stock
                        FROM product_variants
                        WHERE id = ?
                          AND product_id = ?
                    """, (
                        item["variant_id"],
                        item["product_id"]
                    )).fetchone()

                    if variant is None:
                        conn.rollback()
                        return render_template(
                            "checkout.html",
                            items=items,
                            total=total,
                            shipping_rates=shipping_rates,
                            shipping_city=shipping_city,
                            shipping_cost=shipping_cost,
                            grand_total=grand_total,
                            currency=currencies[0],
                            error=f"خيار المنتج {item['name']} لم يعد موجودًا. يرجى تحديث السلة ❌"
                        )

                    if (
                        item["color"] != variant["color"]
                        or item["size"] != variant["size"]
                    ):
                        conn.rollback()
                        return render_template(
                            "checkout.html",
                            items=items,
                            total=total,
                            shipping_rates=shipping_rates,
                            shipping_city=shipping_city,
                            shipping_cost=shipping_cost,
                            grand_total=grand_total,
                            currency=currencies[0],
                            error=f"تغير خيار المنتج {item['name']}. يرجى تحديث السلة والمحاولة مرة أخرى ❌"
                        )

                    if variant["stock"] < item["quantity"]:
                        conn.rollback()
                        return render_template(
                            "checkout.html",
                            items=items,
                            total=total,
                            shipping_rates=shipping_rates,
                            shipping_city=shipping_city,
                            shipping_cost=shipping_cost,
                            grand_total=grand_total,
                            currency=currencies[0],
                            error=(
                                f"المخزون غير كافٍ للمنتج {item['name']} "
                                f"({item['color']} / {item['size']}) ❌"
                            )
                        )

                else:

                    if product["stock"] < item["quantity"]:
                        conn.rollback()
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
                    (
                        order_id,
                        product_id,
                        product_name,
                        price,
                        quantity,
                        merchant_id,
                        currency,
                        variant_id,
                        color,
                        size
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id,
                    item["product_id"],
                    item["name"],
                    item["price"],
                    item["quantity"],
                    item["merchant_id"],
                    currencies[0],
                    item["variant_id"],
                    item["color"],
                    item["size"]
                ))

                if item["variant_id"] > 0:

                    # خصم المخزون من اللون والمقاس المحددين فقط.
                    stock_update = conn.execute("""
                        UPDATE product_variants
                        SET stock = stock - ?
                        WHERE id = ?
                          AND product_id = ?
                          AND stock >= ?
                    """, (
                        item["quantity"],
                        item["variant_id"],
                        item["product_id"],
                        item["quantity"]
                    ))

                    if stock_update.rowcount != 1:
                        conn.rollback()
                        return render_template(
                            "checkout.html",
                            items=items,
                            total=total,
                            shipping_rates=shipping_rates,
                            shipping_city=shipping_city,
                            shipping_cost=shipping_cost,
                            grand_total=grand_total,
                            currency=currencies[0],
                            error=(
                                f"المخزون تغير أثناء إتمام الطلب للمنتج "
                                f"{item['name']} ({item['color']} / {item['size']}). "
                                f"يرجى تحديث السلة والمحاولة مرة أخرى ❌"
                            )
                        )

                    # products.stock = مجموع مخزون جميع المتغيرات.
                    variant_total = conn.execute("""
                        SELECT COALESCE(SUM(stock), 0) AS total_stock
                        FROM product_variants
                        WHERE product_id = ?
                    """, (
                        item["product_id"],
                    )).fetchone()["total_stock"]

                    conn.execute("""
                        UPDATE products
                        SET stock = ?
                        WHERE id = ?
                    """, (
                        variant_total,
                        item["product_id"]
                    ))

                else:

                    # المنتج القديم بدون ألوان أو مقاسات.
                    stock_update = conn.execute("""
                        UPDATE products
                        SET stock = stock - ?
                        WHERE id = ?
                          AND status = 'active'
                          AND stock >= ?
                    """, (
                        item["quantity"],
                        item["product_id"],
                        item["quantity"]
                    ))

                    if stock_update.rowcount != 1:
                        conn.rollback()
                        return render_template(
                            "checkout.html",
                            items=items,
                            total=total,
                            shipping_rates=shipping_rates,
                            shipping_city=shipping_city,
                            shipping_cost=shipping_cost,
                            grand_total=grand_total,
                            currency=currencies[0],
                            error=(
                                f"المخزون تغير أثناء إتمام الطلب للمنتج "
                                f"{item['name']}. يرجى تحديث السلة والمحاولة مرة أخرى ❌"
                            )
                        )

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

                # الشحن يُحسب مرة واحدة على مستوى الطلب الرئيسي.
                # لا نكرر تكلفة الشحن داخل كل تاجر.
                merchant_shipping_cost = round(float(shipping_cost), 2)
                merchant_total = round(subtotal + merchant_shipping_cost, 2)

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
                cart_items.variant_id,
                cart_items.color,
                cart_items.size,
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


@app.route("/cart/remove/<int:cart_item_id>", methods=["POST"])
def cart_remove(cart_item_id):

    cart_session_id = session.get("cart_session_id")

    if cart_session_id:
        with db() as conn:
            conn.execute("""
                DELETE FROM cart_items
                WHERE id = ?
                AND session_id = ?
            """, (
                cart_item_id,
                cart_session_id
            ))

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
        # قفل الكتابة لمنع إرجاع المخزون مرتين عند إلغاء متزامن
        conn.execute("BEGIN IMMEDIATE")

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
                SELECT
                    product_id,
                    quantity,
                    variant_id,
                    color,
                    size
                FROM order_items
                WHERE order_id = ?
                  AND merchant_id = ?
            """, (order_id, merchant_id)).fetchall()

            for item in items:

                if item["variant_id"] > 0:
                    # إعادة الكمية إلى نفس اللون والمقاس.
                    conn.execute("""
                        UPDATE product_variants
                        SET stock = stock + ?
                        WHERE id = ?
                          AND product_id = ?
                    """, (
                        item["quantity"],
                        item["variant_id"],
                        item["product_id"]
                    ))

                    # products.stock = مجموع مخزون جميع الألوان والمقاسات.
                    variant_total = conn.execute("""
                        SELECT COALESCE(SUM(stock), 0) AS total_stock
                        FROM product_variants
                        WHERE product_id = ?
                    """, (
                        item["product_id"],
                    )).fetchone()["total_stock"]

                    conn.execute("""
                        UPDATE products
                        SET stock = ?
                        WHERE id = ?
                    """, (
                        variant_total,
                        item["product_id"]
                    ))

                else:
                    # منتج قديم بدون ألوان أو مقاسات.
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
        # تسجيل الطلبات الجديدة كمُشاهدة عند دخول صفحة الطلبات
        conn.execute("""
            UPDATE merchant_orders
            SET viewed = 1
            WHERE merchant_id = ?
              AND status = 'جديد'
        """, (merchant_id,))
        conn.commit()
        orders = conn.execute("""
            SELECT
                orders.id AS order_id,
                orders.customer_name,
                orders.phone,
                orders.address,
                orders.shipping_city,
                orders.shipping_cost,
                orders.grand_total,
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

        # عند دخول التاجر إلى صفحة الإشعارات تعتبر جميع إشعاراته مستلمة/مقروءة
        conn.execute("""
            UPDATE notifications
            SET is_read = 1
            WHERE merchant_id = ?
              AND is_read = 0
        """, (merchant_id,))
        conn.commit()

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
        used = conn.execute(
            "SELECT 1 FROM order_items WHERE product_id = ? LIMIT 1",
            (product_id,)
        ).fetchone()

        if used:
            conn.execute(
                "UPDATE products SET status = 'inactive' WHERE id = ?",
                (product_id,)
            )
        else:
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

# =========================
# MODER AI
# =========================


def send_push_notification(customer_id=None, title="MODER ONE",
                           body="لديك إشعار جديد", url="/"):
    """إرسال Web Push باستخدام مفاتيح VAPID المخزنة في متغيرات البيئة."""
    private_key = os.environ.get("ASMAR_VAPID_PRIVATE_KEY", "").strip()
    vapid_sub = os.environ.get("ASMAR_VAPID_SUB", "").strip()

    if not private_key or not vapid_sub:
        print("PUSH DEBUG: VAPID settings are missing")
        return 0

    try:
        from pywebpush import webpush, WebPushException
    except Exception as exc:
        print("PUSH DEBUG: pywebpush unavailable:", exc)
        return 0

    with db() as conn:
        if customer_id is None:
            subscriptions = conn.execute("""
                SELECT id, endpoint, p256dh, auth
                FROM push_subscriptions
            """).fetchall()
        else:
            subscriptions = conn.execute("""
                SELECT id, endpoint, p256dh, auth
                FROM push_subscriptions
                WHERE customer_id = ?
            """, (customer_id,)).fetchall()

    sent = 0

    for subscription in subscriptions:
        subscription_info = {
            "endpoint": subscription["endpoint"],
            "keys": {
                "p256dh": subscription["p256dh"],
                "auth": subscription["auth"]
            }
        }

        try:
            webpush(
                subscription_info=subscription_info,
                data=json.dumps({
                    "title": title,
                    "body": body,
                    "url": url
                }, ensure_ascii=False),
                vapid_private_key=private_key,
                vapid_claims={
                    "sub": vapid_sub
                },
                ttl=86400
            )
            sent += 1

        except WebPushException as exc:
            status_code = getattr(
                getattr(exc, "response", None),
                "status_code",
                None
            )

            if status_code in (404, 410):
                with db() as conn:
                    conn.execute(
                        "DELETE FROM push_subscriptions WHERE id = ?",
                        (subscription["id"],)
                    )

            print(
                "PUSH DEBUG: delivery failed",
                subscription["id"],
                status_code,
                exc
            )

        except Exception as exc:
            print(
                "PUSH DEBUG: unexpected delivery error",
                subscription["id"],
                exc
            )

    return sent


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    customer_id = session.get("customer_id")

    if not customer_id:
        return jsonify({
            "ok": False,
            "error": "يجب تسجيل الدخول أولًا."
        }), 401

    data = request.get_json(silent=True) or {}
    endpoint = str(data.get("endpoint", "")).strip()
    keys = data.get("keys") or {}
    p256dh = str(keys.get("p256dh", "")).strip()
    auth = str(keys.get("auth", "")).strip()

    if not endpoint or not p256dh or not auth:
        return jsonify({
            "ok": False,
            "error": "بيانات الاشتراك غير مكتملة."
        }), 400

    with db() as conn:
        conn.execute("""
            INSERT INTO push_subscriptions
                (customer_id, endpoint, p256dh, auth)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                customer_id = excluded.customer_id,
                p256dh = excluded.p256dh,
                auth = excluded.auth
        """, (customer_id, endpoint, p256dh, auth))

    return jsonify({"ok": True})


@app.route("/api/asmar-ai", methods=["POST"])
def asmar_ai():
    import json
    import subprocess
    import re

    user_message = request.form.get("message", "").strip()

    if not user_message:
        return jsonify({"ok": False, "error": "اكتب سؤالك أولًا."}), 400

    if len(user_message) > 500:
        return jsonify({"ok": False, "error": "الرسالة طويلة جدًا."}), 400

    with db() as conn:
        products = conn.execute("""
            SELECT
                id,
                name,
                price,
                original_price,
                description,
                stock,
                image,
                category,
                currency
            FROM products
            WHERE status = 'active'
            ORDER BY id DESC
            LIMIT 100
        """).fetchall()

    product_context = []

    for product in products:
        product_context.append({
            "id": product["id"],
            "name": product["name"],
            "price": product["price"],
            "original_price": product["original_price"],
            "description": product["description"] or "",
            "stock": product["stock"],
            "category": product["category"] or "أخرى",
            "currency": product["currency"] or "YER"
        })

    system_prompt = """
أنت MODER AI، مساعد التسوق الذكي لمنصة ASMAR MARKET.

افهم سؤال العميل باللغة الطبيعية ثم اختر المنتجات المناسبة فقط من القائمة.

مهم جدًا:
- لا تخترع أي منتج.
- لا تخترع سعرًا أو مخزونًا.
- لا تخترع اسم ماركة أو موديل أو مواصفة أو ميزة غير موجودة حرفيًا في بيانات المنتج.
- إذا كان اسم المنتج "ساعه فاخره" فلا تقل "كاسيو" ولا تضف أي مواصفات مثل مقاومة الماء إلا إذا كانت موجودة في بيانات المنتج.
- استخدم فقط الاسم والتصنيف والوصف لفهم المنتج.
- اعتبر الكلمات المتقاربة في المعنى.
- هاتف، جوال، آيفون، ايفون = هاتف.
- سماعة، سماعات، بلوتوث، ايربودز = سماعة إذا كان المنتج مناسبًا.
- عطر، برفان، عطور = عطر.
- ساعة، ساعه، ساعات = ساعة.
- إذا طلب العميل منتجًا غير موجود، product_ids تكون [].
- إذا كان المنتج موجودًا لكن المخزون 0، يمكنك ذكر أنه موجود لكنه غير متوفر حاليًا.
- إذا طلب العميل "بسعر مناسب" أو "رخيص" فاختر المنتجات ذات السعر الأقل نسبيًا ضمن المنتجات المطابقة.
- لا تعتبر العملة الواحدة مساوية لعملة أخرى؛ اعرض العملة كما هي في بيانات المنتج.
- أجب بالعربية وبأسلوب ودود وفخم ومختصر.
- افهم نوع سؤال العميل قبل الإجابة.
- إذا سأل العميل "ما رأيك؟" أو "هل المنتج حلو؟" أو "كيف تقيّمه؟" فقدم رأيًا مبنيًا فقط على المعلومات المتوفرة عن المنتج، مثل الاسم والتصنيف والوصف والسعر والتوفر.
- إذا سأل العميل "هل تنصحني بشرائه؟" فاذكر نقاط القوة والقيود المتوفرة في البيانات، ثم اترك قرار الشراء للعميل.
- إذا سأل عن السعر أو التوفر فأجب من بيانات قاعدة البيانات.
- إذا سأل عن المميزات، اذكر فقط المميزات الموجودة في الوصف أو بيانات المنتج.
- لا تدّعي أنك جربت المنتج أو استخدمته بنفسك.
- لا تستنتج جودة أو متانة أو عملية أو مناسبة للاستخدام اليومي أو قيمة ممتازة من الاسم أو السعر أو الوصف وحده. اذكر فقط ما تدعمه بيانات المنتج حرفيًا، ولا تحوّل أي وصف إلى ضمان أو حكم تجريبي.
- إذا سأل العميل صراحةً: "تنصحني أشتريه؟" أو "أشتريه؟" أو "هل أشتريه؟" أو طلب رأيك في الشراء، يمكنك تقديم توصية واضحة بالشراء بناءً على المعلومات المتوفرة، مع ترك القرار النهائي للعميل.
- عند وجود مخزون قليل، يمكنك تنبيه العميل إلى أن الكمية المتوفرة قليلة، وخصوصًا إذا كانت 3 قطع أو أقل، مثل: "إذا أعجبك المنتج فلا تؤجل كثيرًا قبل نفاد الكمية." لا تستخدم عبارة "المخزون محدود" إلا إذا كانت الكمية فعلًا قليلة.
- لا تقل "سعر معقول" أو "سعر ممتاز" أو "يستحق الشراء" إلا إذا كان العميل قد طلب رأيًا، وحتى عندها اربط التوصية بالمعلومات المتوفرة بدل تقديمها كحقيقة موضوعية.

- لا تخترع مواصفات أو ماركات أو تقييمات رقمية غير موجودة في البيانات.
- إذا كانت المعلومات غير كافية لتقييم المنتج، قل ذلك بوضوح.
- إذا قال العميل "هذه الساعة" أو "هذا المنتج" وكان هناك منتج مناسب في نفس السؤال، اربطه بذلك المنتج.
- يمكن استخدام إيموجي قليلة.
- أعد JSON فقط.

الصيغة:
{
  "answer": "رد العميل",
  "product_ids": [1, 2, 3]
}
"""

    last_product_id = session.get("asmar_ai_last_product_id")

    last_product_context = ""
    if last_product_id:
        for product in product_context:
            if int(product["id"]) == int(last_product_id):
                last_product_context = json.dumps(
                    product,
                    ensure_ascii=False
                )
                break

    user_prompt = f"""
رسالة العميل:
{user_message}

آخر منتج تم عرضه للعميل في المحادثة السابقة:
{last_product_context if last_product_context else "لا يوجد"}

مهم:
إذا كانت رسالة العميل تشير إلى "هذا المنتج" أو "هذه الساعة" أو "هو" أو "هي"
وكان آخر منتج معروض مناسبًا للسياق، فاستخدم آخر منتج معروض باعتباره المقصود.

المنتجات الحالية:
{json.dumps(product_context, ensure_ascii=False)}
"""

    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key:
        return jsonify({
            "ok": False,
            "error": "MODER AI غير مفعّل حاليًا."
        }), 500

    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 500,
        "temperature": 0.1
    }

    try:
        import requests

        response_request = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "ASMAR-MARKET/1.0"
            },
            json=payload,
            timeout=30
        )

        if not response_request.ok:
            print("MODER AI GROQ ERROR:", response_request.text)
            return jsonify({
                "ok": False,
                "error": "تعذر الاتصال بمساعد التسوق حاليًا."
            }), 502

        response = response_request.json()

        if "error" in response:
            print("MODER AI GROQ ERROR:", response["error"])
            return jsonify({
                "ok": False,
                "error": "خطأ من خدمة MODER AI."
            }), 502

        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        content = re.sub(r"^```json\s*", "", content)
        content = re.sub(r"\s*```$", "", content).strip()

        try:
            ai_result = json.loads(content)
        except json.JSONDecodeError:
            print("MODER AI INVALID JSON:", content)
            return jsonify({
                "ok": False,
                "error": "تعذر قراءة نتيجة MODER AI."
            }), 502

        answer = str(ai_result.get("answer", "")).strip()
        requested_ids = ai_result.get("product_ids", [])

        # الحفاظ على إجابة MODER AI الأصلية.
        # إذا لم توجد إجابة أصلًا، نستخدم رسالة افتراضية فقط.
        if not answer:
            if requested_ids:
                answer = "هذه المنتجات قد تناسب طلبك:"
            else:
                answer = "عذرًا، لم أجد منتجًا مناسبًا حاليًا."

        if not isinstance(requested_ids, list):
            requested_ids = []

        valid_ids = {int(product["id"]) for product in product_context}

        selected_ids = []

        for product_id in requested_ids:
            try:
                product_id = int(product_id)
            except (TypeError, ValueError):
                continue

            if product_id in valid_ids and product_id not in selected_ids:
                selected_ids.append(product_id)

        selected_ids = selected_ids[:6]

        # حفظ أول منتج تم اختياره حتى تفهم MODER AI عبارات مثل:
        # "هذه الساعة" و"هذا المنتج" و"تنصحني أشتريها؟"
        if selected_ids:
            session["asmar_ai_last_product_id"] = selected_ids[0]

        selected_products = []

        with db() as conn:
            if selected_ids:
                placeholders = ",".join("?" for _ in selected_ids)

                rows = conn.execute(
                    f"""
                    SELECT
                        id,
                        name,
                        price,
                        original_price,
                        stock,
                        image,
                        category,
                        currency
                    FROM products
                    WHERE status = 'active'
                      AND id IN ({placeholders})
                    """,
                    selected_ids
                ).fetchall()

                row_map = {int(row["id"]): row for row in rows}

                for product_id in selected_ids:
                    row = row_map.get(product_id)

                    if not row:
                        continue

                    selected_products.append({
                        "id": row["id"],
                        "name": row["name"],
                        "price": row["price"],
                        "original_price": row["original_price"],
                        "stock": row["stock"],
                        "image": row["image"],
                        "category": row["category"] or "أخرى",
                        "currency": row["currency"] or "YER",
                        "url": f"/product/{row['id']}"
                    })

        return jsonify({
            "ok": True,
            "answer": answer,
            "products": selected_products
        })

    except Exception as e:
        print("MODER AI ERROR:", str(e))
        return jsonify({
            "ok": False,
            "error": "تعذر الاتصال بمساعد التسوق حاليًا."
        }), 502

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000))
    )

@app.route("/sw.js")
def service_worker():
    return send_from_directory(app.static_folder, "sw.js")

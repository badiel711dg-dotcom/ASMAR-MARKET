from pathlib import Path

a = Path("templates/add_product.html")
e = Path("templates/edit_product.html")
sa, se = a.read_text(), e.read_text()

old_a = '''    <optgroup label="المجوهرات">
        <option value="مجوهرات وإكسسوارات">المجوهرات</option>'''
new_a = '''    <optgroup label="المجوهرات">
        <option value="مجوهرات">المجوهرات</option>
        <option value="مجوهرات وإكسسوارات">مجوهرات وإكسسوارات (قديم)</option>'''

old_e = '        <option value="إكسسوارات" {% if product["category"] == "إكسسوارات" %}selected{% endif %}>إكسسوارات (قديم)</option>'

if sa.count(old_a) != 1:
    raise SystemExit("توقف: لم أجد مجموعة المجوهرات في صفحة الإضافة كما توقعت")
if se.count(old_e) != 1:
    raise SystemExit("توقف: لم أجد خيار الإكسسوارات المكرر كما توقعت")

sa = sa.replace(old_a, new_a, 1)
se = se.replace(old_e + "\n", "", 1)

a.write_text(sa)
e.write_text(se)
print("تم فصل المجوهرات وإزالة خيار الإكسسوارات المكرر")

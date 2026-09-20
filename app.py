import sqlite3
import hashlib
import json
import os
from datetime import datetime
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='assets')
CORS(app)

DATABASE = 'users.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def init_db():
    print("Initializing clean SQLite database with WAL mode...")
    conn = get_db_connection()
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        
        # 1. Users Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT DEFAULT 'farmer',
                phone TEXT DEFAULT '',
                location TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 2. Products Table (Digital Mandi)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT DEFAULT 'Cereals',
                price_num REAL NOT NULL,
                unit TEXT DEFAULT 'Kg',
                location TEXT NOT NULL,
                contact TEXT NOT NULL,
                description TEXT DEFAULT '',
                image TEXT NOT NULL,
                seller_name TEXT NOT NULL,
                seller_email TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 3. Orders Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT NOT NULL UNIQUE,
                user_email TEXT NOT NULL,
                user_name TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total_amount REAL NOT NULL,
                delivery_address TEXT NOT NULL,
                pincode TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                status TEXT DEFAULT 'Confirmed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 4. Diagnoses Table (Crop Doctor History)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS diagnoses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT DEFAULT 'guest',
                crop_name TEXT NOT NULL,
                disease_name TEXT NOT NULL,
                confidence REAL NOT NULL,
                severity TEXT DEFAULT 'Moderate',
                remedy TEXT NOT NULL,
                organic_remedy TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
    finally:
        conn.close()
    print("Clean database ready. WAL enabled for concurrent access.")

# --- STATIC & ASSET ROUTES ---

@app.route('/')
def serve_index():
    return send_file('index.html')

@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory('assets', filename)

# --- AUTHENTICATION ROUTES ---

@app.route('/register', methods=['POST'])
def register_user():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()
    full_name = data.get('full_name', '').strip()
    role = data.get('role', 'farmer').strip().lower()
    phone = data.get('phone', '').strip()
    location = data.get('location', '').strip()

    if not email or not password or not full_name:
        return jsonify({"success": False, "message": "Please provide full name, email, and password."}), 400

    hashed_pw = hash_password(password)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (email, password, full_name, role, phone, location) VALUES (?, ?, ?, ?, ?, ?)",
            (email, hashed_pw, full_name, role, phone, location)
        )
        conn.commit()
        return jsonify({
            "success": True,
            "message": "Registration successful! Welcome to AgroIndia.",
            "user": {
                "email": email,
                "fullName": full_name,
                "role": role,
                "phone": phone,
                "location": location
            }
        }), 201
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "message": "This email address is already registered."}), 400
    except Exception as e:
        return jsonify({"success": False, "message": f"Server Error: {str(e)}"}), 500
    finally:
        conn.close()

@app.route('/login', methods=['POST'])
def login_user():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password are required."}), 400

    hashed_pw = hash_password(password)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ? AND password = ?", (email, hashed_pw))
        user = cursor.fetchone()
        if user:
            return jsonify({
                "success": True,
                "message": "Login successful!",
                "user": {
                    "id": user['id'],
                    "email": user['email'],
                    "fullName": user['full_name'],
                    "role": user['role'] or 'farmer',
                    "phone": user['phone'] or '',
                    "location": user['location'] or ''
                }
            }), 200
        else:
            return jsonify({"success": False, "message": "Invalid email or password. Please try again."}), 401
    finally:
        conn.close()

@app.route('/update_role', methods=['POST'])
def update_role():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    role = data.get('role', '').strip().lower()

    if not email or not role:
        return jsonify({"success": False, "message": "Email and role are required."}), 400

    conn = get_db_connection()
    try:
        conn.execute("UPDATE users SET role = ? WHERE email = ?", (role, email))
        conn.commit()
        return jsonify({
            "success": True, 
            "message": f"Role updated to {role.capitalize()} successfully.",
            "role": role
        }), 200
    finally:
        conn.close()

# --- PRODUCT (MARKETPLACE) ROUTES ---

@app.route('/products', methods=['GET'])
def get_products():
    category = request.args.get('category', 'all')
    search = request.args.get('search', '').strip().lower()
    
    conn = get_db_connection()
    try:
        query = 'SELECT * FROM products WHERE 1=1'
        params = []
        
        if category != 'all' and category != '':
            query += ' AND category = ?'
            params.append(category)
            
        if search:
            query += ' AND (LOWER(name) LIKE ? OR LOWER(location) LIKE ? OR LOWER(seller_name) LIKE ?)'
            like_pattern = f'%{search}%'
            params.extend([like_pattern, like_pattern, like_pattern])
            
        query += ' ORDER BY id DESC'
        
        products = conn.execute(query, params).fetchall()
        
        products_list = []
        for row in products:
            p = dict(row)
            p['price'] = p['price_num']
            p['img'] = p['image']
            p['seller'] = p['seller_name']
            products_list.append(p)
            
        return jsonify({"success": True, "products": products_list})
    finally:
        conn.close()

@app.route('/add_product', methods=['POST'])
def add_product():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    price = data.get('price') or data.get('price_num') or data.get('priceNum')
    unit = data.get('unit', 'Kg')
    category = data.get('category', 'Cereals')
    location = data.get('location', '').strip()
    contact = data.get('contact', '').strip()
    description = data.get('desc', data.get('description', '')).strip()
    image = data.get('img', data.get('image', 'https://images.unsplash.com/photo-1574323347407-f5e1ad6d020b?auto=format&fit=crop&q=80&w=600'))
    seller_name = data.get('seller', data.get('seller_name', 'Kisan')).strip()
    seller_email = data.get('seller_email', '').strip()

    if not name or price is None or not location or not contact:
        return jsonify({"success": False, "message": "Crop name, price, location, and contact phone are required."}), 400

    try:
        price_float = float(price)
    except ValueError:
        return jsonify({"success": False, "message": "Price must be a valid number."}), 400

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO products (name, category, price_num, unit, location, contact, description, image, seller_name, seller_email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, category, price_float, unit, location, contact, description, image, seller_name, seller_email))
        product_id = cursor.lastrowid
        conn.commit()

        return jsonify({
            "success": True,
            "message": "Your produce has been listed in the Digital Mandi successfully!",
            "product_id": product_id
        }), 201
    finally:
        conn.close()

@app.route('/delete_product/<int:id>', methods=['DELETE', 'POST'])
def delete_product(id):
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM products WHERE id = ?', (id,))
        conn.commit()
        return jsonify({"success": True, "message": "Product removed successfully."}), 200
    finally:
        conn.close()

# --- ORDERS ROUTES ---

@app.route('/create_order', methods=['POST'])
def create_order():
    data = request.get_json() or {}
    user_email = data.get('user_email', 'guest@kisan.com')
    user_name = data.get('user_name', 'Customer')
    items = data.get('items', [])
    total_amount = data.get('total_amount', 0.0)
    delivery_address = data.get('delivery_address', '').strip()
    pincode = data.get('pincode', '').strip()
    payment_method = data.get('payment_method', 'UPI')

    if not items or float(total_amount) <= 0 or not delivery_address or not pincode:
        return jsonify({"success": False, "message": "Cart items, delivery address, and pincode are required."}), 400

    order_code = f"AGR-{datetime.now().strftime('%Y%m%d%H%M%S')}-{os.urandom(2).hex().upper()}"

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO orders (order_code, user_email, user_name, items_json, total_amount, delivery_address, pincode, payment_method, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (order_code, user_email, user_name, json.dumps(items), float(total_amount), delivery_address, pincode, payment_method, 'Confirmed'))
        order_id = cursor.lastrowid
        conn.commit()

        return jsonify({
            "success": True,
            "message": "Order placed successfully!",
            "order": {
                "id": order_id,
                "order_code": order_code,
                "total_amount": total_amount,
                "status": "Confirmed",
                "date": datetime.now().strftime('%d %b %Y, %I:%M %p')
            }
        }), 201
    finally:
        conn.close()

@app.route('/orders', methods=['GET'])
def get_orders():
    email = request.args.get('email', '')
    conn = get_db_connection()
    try:
        if email:
            orders = conn.execute('SELECT * FROM orders WHERE user_email = ? ORDER BY id DESC', (email,)).fetchall()
        else:
            orders = conn.execute('SELECT * FROM orders ORDER BY id DESC').fetchall()

        orders_list = []
        for row in orders:
            order = dict(row)
            try:
                order['items'] = json.loads(order['items_json'])
            except Exception:
                order['items'] = []
            orders_list.append(order)

        return jsonify({"success": True, "orders": orders_list})
    finally:
        conn.close()

# --- AI CROP DOCTOR ROUTES ---

@app.route('/diagnose', methods=['POST'])
def diagnose_crop():
    data = request.get_json() or {}
    crop = data.get('crop', 'Wheat')
    email = data.get('email', 'guest')

    knowledge = {
        'Wheat': [
            {
                "disease": "Yellow Rust (Puccinia striiformis)",
                "confidence": 96.4,
                "severity": "High",
                "remedy": "Spray Propiconazole 25% EC (Tilt) @ 1 ml/L of water. Ensure proper field drainage.",
                "organic_remedy": "Foliar spray with 5% Neem seed kernel extract (NSKE) + bio-fungicide formulation."
            },
            {
                "disease": "Karnal Bunt (Tilletia indica)",
                "confidence": 92.1,
                "severity": "Moderate",
                "remedy": "Treat seeds with Carbendazim 50 WP @ 2g/kg before sowing. Spray Mancozeb 75 WP.",
                "organic_remedy": "Crop rotation with non-host crops and Trichoderma viride application."
            },
            {
                "disease": "Healthy Crop",
                "confidence": 98.7,
                "severity": "None",
                "remedy": "No chemical treatment needed. Maintain optimal NPK balance and timely irrigation.",
                "organic_remedy": "Apply vermicompost and Jeevamrut regularly."
            }
        ],
        'Rice': [
            {
                "disease": "Bacterial Leaf Blight (Xanthomonas oryzae)",
                "confidence": 95.2,
                "severity": "High",
                "remedy": "Spray Streptocycline (1.5g) + Copper Oxychloride (25g) per 10L of water.",
                "organic_remedy": "Drain excess water from field; spray fresh sour buttermilk (chaas) solution."
            },
            {
                "disease": "Rice Blast (Magnaporthe oryzae)",
                "confidence": 93.8,
                "severity": "Severe",
                "remedy": "Apply Tricyclazole 75% WP @ 0.6 g/L or Isoprothiolane 40% EC @ 1.5 ml/L.",
                "organic_remedy": "Apply Pseudomonas fluorescens @ 10g/L spray."
            }
        ],
        'Tomato': [
            {
                "disease": "Early Blight (Alternaria solani)",
                "confidence": 97.1,
                "severity": "Moderate",
                "remedy": "Spray Mancozeb 75% WP @ 2.5g/L or Azoxystrobin 23% SC @ 1 ml/L.",
                "organic_remedy": "Prune lower infected leaves; apply baking soda spray (5g/L) + neem oil."
            },
            {
                "disease": "Tomato Leaf Curl Virus (ToLCV)",
                "confidence": 94.6,
                "severity": "Severe",
                "remedy": "Control whitefly vector by spraying Imidacloprid 17.8% SL @ 0.3 ml/L.",
                "organic_remedy": "Install yellow sticky traps (15 per acre); spray 3% Neem oil emulsion."
            }
        ],
        'Potato': [
            {
                "disease": "Late Blight (Phytophthora infestans)",
                "confidence": 98.0,
                "severity": "Critical",
                "remedy": "Immediate spray of Metalaxyl 8% + Mancozeb 64% WP (Ridomil MZ) @ 2.5g/L.",
                "organic_remedy": "Copper hydroxide spray (2g/L); destroy infected haulms immediately."
            }
        ],
        'Cotton': [
            {
                "disease": "Cotton Leaf Curl Virus (CLCuV)",
                "confidence": 91.5,
                "severity": "High",
                "remedy": "Spray Diafenthiuron 50% WP @ 1.2g/L for whitefly control.",
                "organic_remedy": "Grow border barrier crops (Bajra/Maize); spray Dashparni Ark."
            }
        ]
    }

    import random
    diag_list = knowledge.get(crop, knowledge['Wheat'])
    selected = random.choice(diag_list)

    # Save diagnosis record in database
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO diagnoses (user_email, crop_name, disease_name, confidence, severity, remedy, organic_remedy)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (email, crop, selected['disease'], selected['confidence'], selected['severity'], selected['remedy'], selected['organic_remedy']))
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        "success": True,
        "diagnosis": selected
    })

# --- DYNAMIC DATABASE STATS ---

@app.route('/stats', methods=['GET'])
def get_stats():
    conn = get_db_connection()
    try:
        total_users = conn.execute('SELECT COUNT(*) as c FROM users').fetchone()['c']
        total_products = conn.execute('SELECT COUNT(*) as c FROM products').fetchone()['c']
        total_orders = conn.execute('SELECT COUNT(*) as c FROM orders').fetchone()['c']
        return jsonify({
            "success": True,
            "farmers_count": total_users,
            "live_products": total_products,
            "total_orders": total_orders
        })
    finally:
        conn.close()

if __name__ == '__main__':
    init_db()
    print("=" * 60)
    print(">> AgroIndia Server running at: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)
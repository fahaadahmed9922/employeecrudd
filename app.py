from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, jsonify
from flask_mysqldb import MySQL
from werkzeug.utils import secure_filename
from datetime import datetime, date
import os
import qrcode

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# MySQL Config
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'employee_db'

# Upload folders
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

QRCODE_FOLDER = 'qrcodes'
app.config['QRCODE_FOLDER'] = QRCODE_FOLDER
os.makedirs(QRCODE_FOLDER, exist_ok=True)

mysql = MySQL(app)

# Serve uploaded photos
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Serve QR codes
@app.route('/qrcodes/<filename>')
def qrcode_file(filename):
    return send_from_directory(app.config['QRCODE_FOLDER'], filename)

@app.route('/')
def index():
    if 'loggedin' in session:
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, name, username, email, password, city, photo FROM employees")
        rows = cur.fetchall()
        cur.close()

        employees = []
        for row in rows:
            employees.append({
                'id': row[0],
                'name': row[1],
                'username': row[2],
                'email': row[3],
                'password': row[4],
                'city': row[5],
                'photo': row[6]
            })

        return render_template('index.html', employees=employees)
    else:
        return redirect(url_for('login'))

# ------------------ Attendance ------------------

@app.route('/attendance_scan')
def attendance_scan():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    return render_template('attendance.html')

@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    data = request.json
    employee_id = data.get('employee_id')
    today = date.today()

    cur = mysql.connection.cursor()
    cur.execute("SELECT id, sign_in, sign_out FROM attendance WHERE employee_id=%s AND date=%s", (employee_id, today))
    record = cur.fetchone()

    if record:
        if record[2] is None:
            sign_out_time = datetime.now().strftime('%H:%M:%S')
            cur.execute("UPDATE attendance SET sign_out=%s WHERE id=%s", (sign_out_time, record[0]))
            mysql.connection.commit()
            cur.close()
            return jsonify({'status': 'success', 'message': f'Sign Out recorded at {sign_out_time}'})
        else:
            cur.close()
            return jsonify({'status': 'info', 'message': 'Already signed out today.'})
    else:
        sign_in_time = datetime.now().strftime('%H:%M:%S')
        cur.execute("INSERT INTO attendance (employee_id, date, sign_in) VALUES (%s, %s, %s)", (employee_id, today, sign_in_time))
        mysql.connection.commit()
        cur.close()
        return jsonify({'status': 'success', 'message': f'Sign In recorded at {sign_in_time}'})

# ------------------ Dashboard ------------------

@app.route('/attendance_dashboard')
def attendance_dashboard():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    today = date.today()

    cur.execute("SELECT COUNT(DISTINCT employee_id) FROM attendance WHERE DATE(date) = %s", (today,))
    total_present = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM employees")
    total_employees = cur.fetchone()[0] or 0

    total_absent = total_employees - total_present if total_employees - total_present >= 0 else 0

    cur.execute("""
        SELECT e.name, DATE(a.date), a.sign_in, a.sign_out
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        WHERE DATE(a.date) = %s
        ORDER BY a.date DESC
    """, (today,))
    records = cur.fetchall()
    cur.close()

    return render_template('attendance_dashboard.html',
                           total_present=total_present,
                           total_absent=total_absent,
                           total_employees=total_employees,
                           records=records)

# ------------------ Login, Add, Edit, Delete ------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        user = cur.fetchone()
        cur.close()

        if user:
            session['loggedin'] = True
            session['username'] = username
            return redirect(url_for('index'))
        else:
            flash("Invalid username or password", "danger")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('loggedin', None)
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/add', methods=['GET', 'POST'])
def add_employee():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        city = request.form['city']
        photo = request.files['photo']

        photo_filename = ''
        if photo and photo.filename != '':
            photo_filename = secure_filename(photo.filename)
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], photo_filename))

        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO employees (name, username, email, password, city, photo)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (name, username, email, password, city, photo_filename))
        mysql.connection.commit()

        employee_id = cur.lastrowid

        # ✅ Generate QR code with name_id.png inside qrcodes folder
        qr = qrcode.make(str(employee_id))
        safe_name = secure_filename(name.lower().replace(" ", "_"))
        qr_filename = f"{safe_name}_{employee_id}.png"
        qr_path = os.path.join(app.config['QRCODE_FOLDER'], qr_filename)
        qr.save(qr_path)

        cur.close()

        flash("Employee added successfully and QR code generated.", "success")
        return redirect(url_for('index'))

    return render_template('add_employee.html')

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_employee(id):
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()

    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        city = request.form['city']
        photo = request.files['photo']

        if photo and photo.filename != '':
            photo_filename = secure_filename(photo.filename)
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], photo_filename))
            cur.execute("""
                UPDATE employees
                SET name=%s, username=%s, email=%s, password=%s, city=%s, photo=%s
                WHERE id=%s
            """, (name, username, email, password, city, photo_filename, id))
        else:
            cur.execute("""
                UPDATE employees
                SET name=%s, username=%s, email=%s, password=%s, city=%s
                WHERE id=%s
            """, (name, username, email, password, city, id))

        mysql.connection.commit()
        cur.close()

        flash("Employee updated successfully", "success")
        return redirect(url_for('index'))

    cur.execute("SELECT id, name, username, email, password, city, photo FROM employees WHERE id=%s", (id,))
    row = cur.fetchone()
    cur.close()

    if row:
        employee = {
            'id': row[0],
            'name': row[1],
            'username': row[2],
            'email': row[3],
            'password': row[4],
            'city': row[5],
            'photo': row[6]
        }
        return render_template('edit_employee.html', employee=employee)
    else:
        flash("Employee not found", "danger")
        return redirect(url_for('index'))

@app.route('/delete/<int:id>')
def delete_employee(id):
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM employees WHERE id=%s", (id,))
    mysql.connection.commit()
    cur.close()

    flash("Employee deleted successfully", "success")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)

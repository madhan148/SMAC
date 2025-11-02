import os
import google.generativeai as genai
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient

app = Flask(__name__)
app.secret_key = 'your_very_secret_key_here'  # Replace with a secure random string

# Set your Gemini API key
GEMINI_API_KEY = "AIzaSyA98BprRV6Yl3KnMUSK8TXGLRTEuxqd4GM"
genai.configure(api_key=GEMINI_API_KEY)

app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'png', 'jpg', 'jpeg'}

# -------------------- MONGODB CONNECTION --------------------
MONGO_URI = os.environ.get('MONGO_URI', '')
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['admission_portal']
users_col = db['users']
applications_col = db['applications']

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_user(username):
    return users_col.find_one({'username': username})

def update_user(username, data):
    users_col.update_one({'username': username}, {'$set': data})

def get_supported_model():
    """
    Find the first available Gemini model that supports generateContent.
    """
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            return m.name
    raise Exception("No suitable Gemini model found. Please check your API key and project.")

# -------------------- CHATBOT ROUTE --------------------
@app.route('/chatbot', methods=['POST'])
def chatbot():
    user_message = request.json.get('message')
    if not user_message:
        return jsonify({"error": "Please provide a message"}), 400

    try:
        model_name = get_supported_model()
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(user_message)
        ai_reply = response.text    # Gemini's response
        return jsonify({"reply": ai_reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------- ROUTES --------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = 'student'

        if get_user(username):
            flash('Username already exists')
            return redirect(url_for('register'))

        password_hash = generate_password_hash(password)
        users_col.insert_one({'username': username, 'password_hash': password_hash, 'role': role})
        flash('Registration successful. Please login.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = get_user(username)

        if user and check_password_hash(user['password_hash'], password):
            session['username'] = username
            session['role'] = user['role']
            flash('Logged in successfully.')

            if user['role'] == 'student':
                return redirect(url_for('student_dashboard'))
            elif user['role'] == 'college':
                return redirect(url_for('college_dashboard'))
            elif user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid username or password')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.')
    return redirect(url_for('index'))

@app.route('/student_dashboard')
def student_dashboard():
    if 'username' not in session or session.get('role') != 'student':
        flash('Please login as student.')
        return redirect(url_for('login'))

    username = session['username']
    application = applications_col.find_one({'username': username})
    return render_template('student_dashboard.html', application=application)

@app.route('/admission_form', methods=['GET', 'POST'])
def admission_form():
    if 'username' not in session or session.get('role') != 'student':
        flash('Please login as student.')
        return redirect(url_for('login'))

    if request.method == 'POST':
        fullname = request.form['fullname']
        dob = request.form['dob']
        email = request.form['email']
        phone = request.form['phone']
        father_name = request.form['father_name']
        mother_name = request.form['mother_name']
        address = request.form['address']
        marks_10th = request.form['marks_10th']
        marks_12th = request.form['marks_12th']

        marksheet_10th = request.files['marksheet_10th']
        marksheet_12th = request.files['marksheet_12th']

        if marksheet_10th and allowed_file(marksheet_10th.filename):
            filename_10th = secure_filename(marksheet_10th.filename)
            marksheet_10th.save(os.path.join(app.config['UPLOAD_FOLDER'], filename_10th))
        else:
            flash('Invalid or missing 10th marksheet file.')
            return redirect(url_for('admission_form'))

        if marksheet_12th and allowed_file(marksheet_12th.filename):
            filename_12th = secure_filename(marksheet_12th.filename)
            marksheet_12th.save(os.path.join(app.config['UPLOAD_FOLDER'], filename_12th))
        else:
            flash('Invalid or missing 12th marksheet file.')
            return redirect(url_for('admission_form'))

        applications_col.update_one(
            {'username': session['username']},
            {'$set': {
                'fullname': fullname,
                'dob': dob,
                'email': email,
                'phone': phone,
                'father_name': father_name,
                'mother_name': mother_name,
                'address': address,
                'marks_10th': marks_10th,
                'marks_12th': marks_12th,
                'marksheet_10th': filename_10th,
                'marksheet_12th': filename_12th,
                'status': 'Pending'
            }},
            upsert=True
        )

        flash('Application submitted successfully!')
        return redirect(url_for('student_dashboard'))

    return render_template('admission_form.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/college_dashboard')
def college_dashboard():
    if 'username' not in session or session.get('role') != 'college':
        flash('Please login as college.')
        return redirect(url_for('login'))

    user = get_user(session['username'])
    if not user.get('verified', False):
        flash('Your college account is not verified yet.')
        return redirect(url_for('login'))

    applications = list(applications_col.find())
    return render_template('college_dashboard.html', applications=applications)

@app.route('/validate/<student_username>/<action>')
def validate(student_username, action):
    if 'username' not in session or session.get('role') != 'college':
        flash('Please login as college.')
        return redirect(url_for('login'))

    user = get_user(session['username'])
    if not user.get('verified', False):
        flash('Your college account is not verified yet.')
        return redirect(url_for('login'))

    app_data = applications_col.find_one({'username': student_username})
    if app_data:
        new_status = 'Approved' if action == 'approve' else 'Rejected'
        applications_col.update_one({'username': student_username}, {'$set': {'status': new_status}})
        flash(f"Application of {student_username} {new_status}.")
    else:
        flash('Application not found.')

    return redirect(url_for('college_dashboard'))

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Please login as admin.')
        return redirect(url_for('login'))

    colleges = list(users_col.find({'role': 'college'}))
    return render_template('admin_dashboard.html', colleges=colleges)

@app.route('/add_college', methods=['GET', 'POST'])
def add_college():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Please login as admin.')
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if get_user(username):
            flash('Username already exists')
            return redirect(url_for('add_college'))

        users_col.insert_one({
            'username': username,
            'password_hash': generate_password_hash(password),
            'role': 'college',
            'verified': False
        })

        flash('College user created. Verification pending.')
        return redirect(url_for('admin_dashboard'))

    return render_template('add_college.html')

@app.route('/verify_college/<username>')
def verify_college(username):
    if 'username' not in session or session.get('role') != 'admin':
        flash('Please login as admin.')
        return redirect(url_for('login'))

    user = get_user(username)
    if user and user['role'] == 'college':
        update_user(username, {'verified': True})
        flash(f'College user {username} verified.')
    else:
        flash('College user not found.')
    return redirect(url_for('admin_dashboard'))

# -------------------- START SERVER --------------------
if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    app.run(debug=True)

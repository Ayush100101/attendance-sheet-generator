from flask import Flask, render_template, request, redirect, url_for, send_file, flash, send_from_directory, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
import os
import shutil
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Required for flash messages and Flask-Login

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'  # SQLite database file
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # Create the upload folder if it doesn't exist

# Temporary folder for updated files
TEMP_FOLDER = 'temp'
app.config['TEMP_FOLDER'] = TEMP_FOLDER
os.makedirs(TEMP_FOLDER, exist_ok=True)

# Drop records folder
DROP_RECORDS_FOLDER = 'drop_records'
app.config['DROP_RECORDS_FOLDER'] = DROP_RECORDS_FOLDER
os.makedirs(DROP_RECORDS_FOLDER, exist_ok=True)

# User model for the database
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

    # Override get_id to return the username instead of the ID
    def get_id(self):
        return self.username  # Use username as the identifier

# Drop record model for the database
class DropRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usn = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(500), nullable=False)

# Subject model for the database
class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    year = db.Column(db.String(10), nullable=False)  # 'te' or 'se'

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Redirect to login page if unauthorized

@login_manager.user_loader
def load_user(username):
    return User.query.filter_by(username=username).first()  # Use username instead of ID

# Create the database and tables
with app.app_context():
    db.create_all()

# Function to filter students by subject
def filter_students_by_subject(file_path, selected_subject, batch_size):
    df = pd.read_excel(file_path)
    subject_columns = ['Open Elective II', 'Open Elective III']  # Add all subject columns here
    
    # Check which column contains the selected subject
    filtered_df = df[df[subject_columns].apply(lambda row: selected_subject in row.values, axis=1)]
    
    # Keep required columns in the output (including all subject details)
    columns_to_keep = ['Division', 'Batch', 'USN', 'Roll No', 'Name'] + subject_columns
    filtered_df = filtered_df[columns_to_keep]
    
    # Sort by batch priority (A1, A2, A3, B1, B2, etc.) and then by USN chronologically
    batch_order = sorted(filtered_df['Batch'].unique(), key=lambda x: (x[0], int(x[1:]) if x[1:].isdigit() else 0))
    filtered_df['Batch'] = pd.Categorical(filtered_df['Batch'], categories=batch_order, ordered=True)
    filtered_df = filtered_df.sort_values(by=['Batch', 'USN'])
    
    # Split data into multiple sheets based on batch size
    sheet_data = {}
    num_sheets = (len(filtered_df) // batch_size) + (1 if len(filtered_df) % batch_size != 0 else 0)
    
    for i in range(num_sheets):
        start_idx = i * batch_size
        end_idx = start_idx + batch_size
        batch_df = filtered_df.iloc[start_idx:end_idx].copy()
        batch_df.insert(0, 'Serial No', range(1, len(batch_df) + 1))  # Add Serial Number column
        sheet_data[f'Batch_{i+1}'] = batch_df
    
    return sheet_data

# Routes for authentication
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash('Passwords do not match. Please try again.', 'error')
        else:
            # Check if the username already exists
            existing_user = User.query.filter_by(username=username).first()
            if existing_user:
                flash('Username already exists. Please choose a different username.', 'error')
            else:
                # Create a new user
                new_user = User(username=username, password=password)  # In production, hash the password!
                db.session.add(new_user)
                db.session.commit()
                flash('Account created successfully! Please log in.', 'success')
                return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and user.password == password:  # In production, use password hashing!
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('login'))

# Protect all routes that require authentication
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/update_subject', methods=['GET', 'POST'])
@login_required
def update_subject():
    if request.method == 'POST':
        current_subject_file = request.files['current_subject_file']
        new_subject_file = request.files['new_subject_file']
        usn = request.form.get('usn')

        if not current_subject_file or not new_subject_file or not usn:
            flash('Please upload both files and provide the USN.', 'error')
            return redirect(url_for('update_subject'))

        # Save the uploaded files
        current_subject_path = os.path.join(app.config['UPLOAD_FOLDER'], 'current_subject.xlsx')
        new_subject_path = os.path.join(app.config['UPLOAD_FOLDER'], 'new_subject.xlsx')
        current_subject_file.save(current_subject_path)
        new_subject_file.save(new_subject_path)

        # Load the Excel files
        current_df = pd.read_excel(current_subject_path)
        new_df = pd.read_excel(new_subject_path)

        # Find the student in the current subject file
        student = current_df[current_df['USN'] == usn]

        if not student.empty:
            # Remove the student from the current subject file
            current_df = current_df[current_df['USN'] != usn]

            # Add the student to the new subject file
            new_df = pd.concat([new_df, student], ignore_index=True)

            # Sort the new_df by USN in chronological order
            new_df = new_df.sort_values(by='USN')

            # Save the updated files to the temporary folder
            updated_current_path = os.path.join(app.config['TEMP_FOLDER'], 'updated_current_subject.xlsx')
            updated_new_path = os.path.join(app.config['TEMP_FOLDER'], 'updated_new_subject.xlsx')
            current_df.to_excel(updated_current_path, index=False)
            new_df.to_excel(updated_new_path, index=False)

            flash('Subject updated successfully! Download the updated files below.', 'success')
            return render_template('update_subject.html', files_ready=True)
        else:
            flash('Student not found in the current subject file.', 'error')
            return redirect(url_for('update_subject'))

    return render_template('update_subject.html', files_ready=False)

# Route to download updated files
@app.route('/download/<filename>')
@login_required
def download_file(filename):
    return send_from_directory(app.config['TEMP_FOLDER'], filename, as_attachment=True)

# Drop student feature
@app.route('/drop_student', methods=['GET', 'POST'])
@login_required
def drop_student():
    if request.method == 'POST':
        file = request.files['file']
        usn = request.form.get('usn')
        reason = request.form.get('reason')

        if not file or not usn or not reason:
            flash('Please upload a file, provide the USN, and specify the reason.', 'error')
            return redirect(url_for('drop_student'))

        # Save the uploaded file
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'drop_student.xlsx')
        file.save(file_path)

        # Load the Excel file
        df = pd.read_excel(file_path)

        # Find the student in the file
        student = df[df['USN'] == usn]

        if not student.empty:
            # Remove the student from the file
            df = df[df['USN'] != usn]

            # Save the updated file to the temporary folder
            updated_file_path = os.path.join(app.config['TEMP_FOLDER'], 'updated_drop_student.xlsx')
            df.to_excel(updated_file_path, index=False)

            # Save the drop record to the database
            drop_record = DropRecord(usn=usn, reason=reason)
            db.session.add(drop_record)
            db.session.commit()

            flash('Student dropped successfully! Download the updated file below.', 'success')
            return render_template('drop_student.html', files_ready=True)
        else:
            flash('Student not found in the uploaded file.', 'error')
            return redirect(url_for('drop_student'))

    return render_template('drop_student.html', files_ready=False)

# Route to view drop records
@app.route('/view_drop_records')
@login_required
def view_drop_records():
    drop_records = DropRecord.query.all()
    return render_template('view_drop_records.html', drop_records=drop_records)

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('index'))
    
    if file:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'students.xlsx')
        file.save(file_path)
        
        selected_subject = request.form.get('subject')
        batch_size = int(request.form.get('batch_size', 1))
        
        if selected_subject:
            try:
                sheet_data = filter_students_by_subject(file_path, selected_subject, batch_size)
                file_download_path = save_filtered_students(sheet_data, selected_subject)
                flash('Attendance sheet generated successfully!', 'success')
                return send_file(file_download_path, as_attachment=True)
            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'error')
                return redirect(url_for('index'))
        
    return redirect(url_for('index'))

def save_filtered_students(sheet_data, selected_subject):
    safe_subject_name = "_".join(selected_subject.split()).replace("/", "-")
    output_filename = f'filtered_students_{safe_subject_name}.xlsx'
    output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
    
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        for sheet_name, df in sheet_data.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    return output_path

# Route to add a new subject
@app.route('/add_subject', methods=['POST'])
@login_required
def add_subject():
    data = request.get_json()
    subject_name = data.get('subject')
    year = data.get('year')  # Get the year from the request

    if not subject_name or not year:
        return jsonify({'error': 'Subject name and year are required'}), 400

    # Check if the subject already exists
    existing_subject = Subject.query.filter_by(name=subject_name, year=year).first()
    if existing_subject:
        return jsonify({'error': 'Subject already exists'}), 400

    # Add the new subject to the database
    new_subject = Subject(name=subject_name, year=year)
    db.session.add(new_subject)
    db.session.commit()

    return jsonify({'message': 'Subject added successfully'}), 200

# Route to remove a subject
@app.route('/remove_subject', methods=['POST'])
@login_required
def remove_subject():
    data = request.get_json()
    subject_name = data.get('subject')
    year = data.get('year')  # Get the year from the request

    if not subject_name or not year:
        return jsonify({'error': 'Subject name and year are required'}), 400

    # Find the subject in the database
    subject = Subject.query.filter_by(name=subject_name, year=year).first()
    if not subject:
        return jsonify({'error': 'Subject not found'}), 404

    # Remove the subject from the database
    db.session.delete(subject)
    db.session.commit()

    return jsonify({'message': 'Subject removed successfully'}), 200

# Route to create batches
@app.route('/create_batch', methods=['GET', 'POST'])
@login_required
def create_batch():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(url_for('create_batch'))
        
        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(url_for('create_batch'))
        
        if file:
            batch_size = int(request.form.get('batch_size', 1))
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'batch_students.xlsx')
            file.save(file_path)
            
            try:
                df = pd.read_excel(file_path)
                
                # Sort students by USN
                df = df.sort_values(by='USN')
                
                # Split data into multiple sheets based on batch size
                sheet_data = {}
                num_sheets = (len(df) // batch_size) + (1 if len(df) % batch_size != 0 else 0)
                
                for i in range(num_sheets):
                    start_idx = i * batch_size
                    end_idx = start_idx + batch_size
                    batch_df = df.iloc[start_idx:end_idx].copy()
                    batch_df.insert(0, 'Serial No', range(1, len(batch_df) + 1))  # Add Serial Number column
                    sheet_data[f'Batch_{i+1}'] = batch_df
                
                # Save the sorted and batched data to a new Excel file
                output_filename = 'sorted_batched_students.xlsx'
                output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
                
                with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
                    for sheet_name, batch_df in sheet_data.items():
                        batch_df.to_excel(writer, sheet_name=sheet_name, index=False)
                
                flash('Batch created successfully! Download the sheet below.', 'success')
                return send_file(output_path, as_attachment=True)
            
            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'error')
                return redirect(url_for('create_batch'))
    
    return render_template('create_batch.html')

if __name__ == '__main__':
    app.run(debug=True)

from flask import Flask, request, render_template, send_file
import pandas as pd
import os

app = Flask(__name__)

# Route for the home page
@app.route('/')
def index():
    return render_template('index.html')

# Route for handling the file upload and processing
@app.route('/upload', methods=['POST'])
def upload_file():
    if request.method == 'POST':
        # Get the file from the request
        file = request.files['file']
        
        # Get the selected subject and batch size from the form
        subject = request.form['subject'].strip().lower()
        batch_size = int(request.form['batch_size'])
        year = request.form['year'].strip().lower()

        # Read the Excel file
        df = pd.read_excel(file)

        # Determine column names based on the selected year
        if year == 'te':
            subject_columns = ['DLO1', 'DLO2', 'ILO1', 'ILO2']
        else:
            subject_columns = ['major', 'minor']

        # Convert subject columns to lower case for case-insensitive matching
        for col in subject_columns:
            df[col] = df[col].str.lower()
        
        # Filter rows where the selected subject is in any of the subject columns
        filtered_df = df[df[subject_columns].apply(lambda x: subject in x.values, axis=1)]
        
        # Sort the students by batch, starting with A1, A2, etc.
        filtered_df['Batch'] = filtered_df.groupby('Batch').ngroup() + 1
        filtered_df['Batch'] = filtered_df['Batch'].apply(lambda x: f"A{x}" if x <= 3 else f"B{x-3}")

        # Generate multiple sheets if the number of students exceeds batch size
        output_file = 'filtered_students.xlsx'
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            num_batches = (len(filtered_df) + batch_size - 1) // batch_size
            for i in range(num_batches):
                start_idx = i * batch_size
                end_idx = start_idx + batch_size
                batch_df = filtered_df.iloc[start_idx:end_idx]
                batch_df.to_excel(writer, sheet_name=f'Batch_{i+1}', index=False)
        
        # Send the generated file to the user
        return send_file(output_file, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)

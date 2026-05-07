from flask import Flask, render_template, request, redirect, url_for, jsonify
import pandas as pd
import json
import os

app = Flask(__name__)

# Storage paths
UPLOAD_FOLDER = 'data'
SETTINGS_FILE = 'settings.json'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Default Settings
DEFAULT_SETTINGS = {
    "fx_rate": 15400,
    "limits": {
        "FIAFSGVID": 10.3, "FIAFSCPID": 3.7, "FIAFSGVVL": 24.0, 
        "FIAFSCPVL": 30.0, "FIHTMGVID": 1.8, "FIHTMCPVL": 4.9
    }
}

def get_settings():
    if not os.path.exists(SETTINGS_FILE):
        return DEFAULT_SETTINGS
    with open(SETTINGS_FILE, 'r') as f:
        return json.load(f)

@app.route('/')
def dashboard():
    # In a real app, this would read the CSV and calculate everything live
    # For now, it serves the UI
    return render_template('dashboard.html', settings=get_settings())

@app.route('/admin')
def admin():
    return render_template('admin.html', settings=get_settings())

@app.route('/update-settings', methods=['POST'])
def update_settings():
    curr = get_settings()
    data = request.form
    
    # Update FX
    if 'fx_rate' in data:
        curr['fx_rate'] = float(data['fx_rate'])
    
    # Update Portfolio Limit
    if 'port_id' in data and 'limit_val' in data:
        curr['limits'][data['port_id']] = float(data['limit_val'])
        
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(curr, f)
    return redirect(url_for('admin'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files: return "No file"
    file = request.files['file']
    if file.filename == '': return "No selected file"
    file.save(os.path.join(UPLOAD_FOLDER, file.filename))
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
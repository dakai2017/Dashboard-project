import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# --- CONFIGURATION ---
UPLOAD_FOLDER = 'data'
SETTINGS_FILE = 'settings.json'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DEFAULT_SETTINGS = {
    "fx_rate": 15400,
    "limits": {
        "FIAFSGVID": 10.3, "FIAFSCPID": 3.7, "FIAFSGVVL": 24.0, 
        "FIAFSCPVL": 30.0, "FIHTMGVID": 1.8, "FIHTMCPID": 0.0,
        "FIHTMGVVL": 0.0, "FIHTMCPVL": 4.9
    }
}

# --- HELPERS ---
def get_settings():
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w') as f: json.dump(DEFAULT_SETTINGS, f)
        return DEFAULT_SETTINGS
    try:
        with open(SETTINGS_FILE, 'r') as f: return json.load(f)
    except:
        return DEFAULT_SETTINGS

def clean_num(val):
    if pd.isna(val): return 0.0
    s = str(val).replace(',', '').replace('%', '').replace(' ', '').strip()
    try:
        return float(s)
    except:
        return 0.0

# --- ROUTES ---
@app.route('/')
def index():
    settings = get_settings()
    file_path = os.path.join(UPLOAD_FOLDER, "FI-SISTEM.csv")
    
    # Check if file exists
    if not os.path.exists(file_path):
        return redirect(url_for('admin'))

    try:
        # 1. Load Data (assuming skip 2 rows based on previous session)
        df = pd.read_csv(file_path, skiprows=2)
        df.columns = [c.strip() for c in df.columns]
        
        # 2. Basic Cleaning
        if 'PORTFOLIO' not in df.columns or 'OUTSTANDING' not in df.columns:
            return f"Error: CSV headers mismatch. Found: {list(df.columns)}"
            
        df['OS_RAW'] = df['OUTSTANDING'].apply(clean_num)
        
        # 3. Aggregate Summary
        summary_df = df.groupby('PORTFOLIO')['OS_RAW'].sum().reset_index()
        summary = summary_df.to_dict('records')
        
        # 4. Prepare Details (Limited to 100 per port to save memory)
        details = {}
        for pid in df['PORTFOLIO'].unique():
            sub = df[df['PORTFOLIO'] == pid].copy()
            details[pid] = sub[['TICKER', 'OUTSTANDING']].head(100).to_dict('records')

        return render_template('dashboard.html', summary=summary, details=details, settings=settings)

    except Exception as e:
        return f"Logic Error in app.py: {str(e)}"

@app.route('/admin')
def admin():
    return render_template('admin.html', settings=get_settings())

@app.route('/update-settings', methods=['POST'])
def update_settings():
    settings = get_settings()
    if 'fx_rate' in request.form:
        try:
            settings['fx_rate'] = float(request.form['fx_rate'])
        except: pass
    if 'port_id' in request.form and 'limit_val' in request.form:
        try:
            settings['limits'][request.form['port_id']] = float(request.form['limit_val'])
        except: pass
        
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)
    return redirect(url_for('admin'))

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return redirect(url_for('admin'))
    file = request.files['file']
    if file.filename == '':
        return redirect(url_for('admin'))
    if file:
        file.save(os.path.join(UPLOAD_FOLDER, "FI-SISTEM.csv"))
    return redirect(url_for('admin'))

if __name__ == '__main__':
    # Railway provides the port via environment variable
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

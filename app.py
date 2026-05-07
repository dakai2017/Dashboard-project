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

# --- DATA PROCESSING HELPERS ---
def get_settings():
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w') as f: json.dump(DEFAULT_SETTINGS, f)
        return DEFAULT_SETTINGS
    with open(SETTINGS_FILE, 'r') as f: return json.load(f)

def clean_num(val):
    if pd.isna(val): return 0.0
    s = str(val).replace(',', '').replace('%', '').replace(' ', '').strip()
    try: return float(s)
    except: return 0.0

def calc_mod_duration(row, eval_date):
    y, c = (clean_num(row.get('YTM_TO_MTM', 0))/100), (clean_num(row.get('COUPON', 0))/100)
    mat_dt = pd.to_datetime(row.get('MATURITY_DATE'), errors='coerce')
    if pd.isna(mat_dt): return 0.0
    t = (mat_dt - eval_date).days / 365.25
    if t <= 0: return 0.0
    y_m = (y if y > 0 else 0.0001) / 2
    n = max(1, int(t * 2))
    k = np.arange(1, n + 1)
    cf = np.full(len(k), c/2)
    cf[-1] += 1.0
    dfac = (1 + y_m)**-k
    p = np.sum(cf * dfac)
    mac = np.sum((k/2) * cf * dfac) / p
    return mac / (1 + y_m)

# --- ROUTES ---
@app.route('/')
def index():
    settings = get_settings()
    file_path = os.path.join(UPLOAD_FOLDER, "FI-SISTEM.csv")
    
    if not os.path.exists(file_path):
        return redirect(url_for('admin'))

    # Load data
    df = pd.read_csv(file_path, skiprows=2)
    df.columns = [c.strip() for c in df.columns]
    
    # Process numeric columns
    df['OS_RAW'] = df['OUTSTANDING'].apply(clean_num)
    df['CCY'] = df['CCY'].fillna('IDR').str.strip()
    
    # Group by Portfolio for the summary
    summary = df.groupby('PORTFOLIO')['OS_RAW'].sum().reset_index().to_dict('records')
    
    # Prepare bond details for the drill-down
    details = {}
    for pid in df['PORTFOLIO'].unique():
        sub = df[df['PORTFOLIO'] == pid]
        details[pid] = sub[['TICKER', 'COUPON', 'MATURITY_DATE', 'OUTSTANDING']].to_dict('records')

    return render_template('dashboard.html', summary=summary, details=details, settings=settings)

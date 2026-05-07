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

def calc_mod_duration(row, eval_date):
    y = clean_num(row.get('YTM_TO_MTM', 0)) / 100
    c = clean_num(row.get('COUPON', 0)) / 100
    mat_dt = pd.to_datetime(row.get('MATURITY_DATE'), errors='coerce')
    if pd.isna(mat_dt): return 0.0
    t = (mat_dt - eval_date).days / 365.25
    if t <= 0: return 0.01 # Small value for expired/same day
    y_m = (y if y > 0 else 0.0001) / 2
    n = max(1, int(t * 2))
    k = np.arange(1, n + 1)
    cf = np.full(len(k), c/2)
    cf[-1] += 1.0
    dfac = (1 + y_m)**-k
    price = np.sum(cf * dfac)
    mac_dur = np.sum((k/2) * cf * dfac) / price
    return round(mac_dur / (1 + y_m), 2)

# --- ROUTES ---
@app.route('/')
def index():
    settings = get_settings()
    fx = settings['fx_rate']
    eval_date = datetime(2026, 5, 5) # Matches your data date
    file_path = os.path.join(UPLOAD_FOLDER, "FI-SISTEM.csv")
    
    if not os.path.exists(file_path):
        return redirect(url_for('admin'))

    try:
        # 1. Load Data
        df = pd.read_csv(file_path, skiprows=2)
        df.columns = [c.strip() for c in df.columns]
        
        # 2. Process Numeric & Duration
        df['OS_RAW'] = df['OUTSTANDING'].apply(clean_num)
        df['CCY'] = df['CCY'].fillna('IDR').str.strip()
        df['DUR'] = df.apply(lambda r: calc_mod_duration(r, eval_date), axis=1)
        
        # 3. Portfolio Logic
        summary = []
        details = {}
        all_pids = ["FITRGVID", "FITRGVVL", "FITRCPID", "FITRCPVL", "FIAFSGVID", "FIAFSGVVL", "FIAFSCPID", "FIAFSCPVL", "FIHTMGVID", "FIHTMGVVL", "FIHTMCPID", "FIHTMCPVL"]
        
        for pid in all_pids:
            sub = df[df['PORTFOLIO'] == pid].copy()
            os_act = sub['OS_RAW'].sum()
            
            # Weighted Duration
            avg_dur = round(np.average(sub['DUR'], weights=sub['OS_RAW']), 2) if os_act > 0 else 0
            
            # Limit & Util
            # Limits in settings are in Tn (IDR) or Mn (USD)
            limit_val = settings['limits'].get(pid, 0)
            ccy = 'USD' if pid.endswith('VL') else 'IDR'
            
            # Normalize limit to base units for percentage calc
            limit_base = limit_val * (1e12 if ccy == 'IDR' else 1e6)
            util = round((os_act / limit_base * 100), 1) if limit_base > 0 else 0
            
            summary.append({
                "id": pid,
                "os_act": os_act,
                "os_lim": f"{limit_val}T" if ccy == 'IDR' else f"{limit_val}M",
                "os_util": util,
                "dur": avg_dur
            })
            
            # Prep Details
            details[pid] = sub[['TICKER', 'COUPON', 'OUTSTANDING', 'DUR']].head(100).to_dict('records')

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
        try: settings['fx_rate'] = float(request.form['fx_rate'])
        except: pass
    if 'port_id' in request.form and 'limit_val' in request.form:
        try: settings['limits'][request.form['port_id']] = float(request.form['limit_val'])
        except: pass
    with open(SETTINGS_FILE, 'w') as f: json.dump(settings, f)
    return redirect(url_for('admin'))

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('file')
    if file and file.filename != '':
        file.save(os.path.join(UPLOAD_FOLDER, "FI-SISTEM.csv"))
    return redirect(url_for('admin'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

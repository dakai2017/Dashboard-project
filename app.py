import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

UPLOAD_FOLDER = 'data'
SETTINGS_FILE = 'settings.json'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# PV01 Limits (Based on our earlier discussion)
PV01_LIMITS = {
    "FITRGVID": 800.0, "FITRCPID": 700.0, "FITRGVVL": 15.0, "FITRCPVL": 15.0,
    "FIAFSGVID": 9000.0, "FIAFSCPID": 3300.0, "FIAFSGVVL": 37.0, "FIAFSCPVL": 27.0
}

DEFAULT_SETTINGS = {
    "fx_rate": 15400,
    "limits": {
        "FIAFSGVID": 10.3, "FIAFSCPID": 3.7, "FIAFSGVVL": 24.0, 
        "FIAFSCPVL": 30.0, "FIHTMGVID": 1.8, "FIHTMCPID": 0.0,
        "FIHTMGVVL": 0.0, "FIHTMCPVL": 4.9
    }
}

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
    y = clean_num(row.get('YTM_TO_MTM', 0)) / 100
    c = clean_num(row.get('COUPON', 0)) / 100
    mat_dt = pd.to_datetime(row.get('MATURITY_DATE'), errors='coerce')
    if pd.isna(mat_dt): return 0.0
    t = (mat_dt - eval_date).days / 365.25
    if t <= 0: return 0.01
    y_m = (y if y > 0 else 0.0001) / 2
    n = max(1, int(t * 2))
    k = np.arange(1, n + 1)
    cf = np.full(len(k), c/2)
    cf[-1] += 1.0
    dfac = (1 + y_m)**-k
    price = np.sum(cf * dfac)
    mac_dur = np.sum((k/2) * cf * dfac) / price
    return round(mac_dur / (1 + y_m), 2)

@app.route('/')
def index():
    settings = get_settings()
    eval_date = datetime(2026, 5, 5)
    file_path = os.path.join(UPLOAD_FOLDER, "FI-SISTEM.csv")
    
    if not os.path.exists(file_path):
        return redirect(url_for('admin'))

    try:
        df = pd.read_csv(file_path, skiprows=2)
        df.columns = [c.strip() for c in df.columns]
        df['OS_RAW'] = df['OUTSTANDING'].apply(clean_num)
        df['DUR'] = df.apply(lambda r: calc_mod_duration(r, eval_date), axis=1)
        df['PV01_RAW'] = df['OS_RAW'] * df['DUR'] * 0.0001
        
        summary = []
        details = {}
        all_pids = ["FITRGVID", "FITRGVVL", "FITRCPID", "FITRCPVL", "FIAFSGVID", "FIAFSGVVL", "FIAFSCPID", "FIAFSCPVL", "FIHTMGVID", "FIHTMGVVL", "FIHTMCPID", "FIHTMCPVL"]
        
        for pid in all_pids:
            sub = df[df['PORTFOLIO'] == pid].copy()
            os_act = sub['OS_RAW'].sum()
            pv_act = sub['PV01_RAW'].sum()
            
            # OS Calculation
            limit_val = settings['limits'].get(pid, 0)
            ccy = 'USD' if pid.endswith('VL') else 'IDR'
            limit_base = limit_val * (1e12 if ccy == 'IDR' else 1e6)
            os_util = round((os_act / limit_base * 100), 1) if limit_base > 0 else 0
            
            # PV01 Calculation
            pv_limit = PV01_LIMITS.get(pid, 0)
            # Adjust PV unit display
            pv_display_act = pv_act if ccy == 'USD' else (pv_act / 1e6)
            pv_util = round((pv_display_act / pv_limit * 100), 1) if pv_limit > 0 else 0

            summary.append({
                "id": pid, "ccy": ccy, "os_act": os_act, "os_util": os_util,
                "pv_act": round(pv_display_act, 1), "pv_util": pv_util, "pv_lim": pv_limit,
                "dur": round(np.average(sub['DUR'], weights=sub['OS_RAW']), 2) if os_act > 0 else 0,
                "type": "TRADING" if "TR" in pid else "BANKING"
            })
            details[pid] = sub[['TICKER', 'COUPON', 'OUTSTANDING', 'DUR']].to_dict('records')

        return render_template('dashboard.html', summary=summary, details=details, settings=settings)
    except Exception as e:
        return f"Logic Error: {str(e)}"

@app.route('/admin')
def admin(): return render_template('admin.html', settings=get_settings())

@app.route('/update-settings', methods=['POST'])
def update_settings():
    settings = get_settings()
    if 'fx_rate' in request.form: settings['fx_rate'] = float(request.form['fx_rate'])
    if 'port_id' in request.form and 'limit_val' in request.form:
        settings['limits'][request.form['port_id']] = float(request.form['limit_val'])
    with open(SETTINGS_FILE, 'w') as f: json.dump(settings, f)
    return redirect(url_for('admin'))

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('file')
    if file: file.save(os.path.join(UPLOAD_FOLDER, "FI-SISTEM.csv"))
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

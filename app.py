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

# PV01 Limits (IDR in Mn, USD in Th - Converted to base units for calculation)
PV01_LIMITS_BASE = {
    "FITRGVID": 800.0 * 1e6,    "FITRCPID": 700.0 * 1e6,
    "FITRGVVL": 15.0 * 1e3,     "FITRCPVL": 15.0 * 1e3,
    "FIAFSGVID": 9000.0 * 1e6,  "FIAFSCPID": 3300.0 * 1e6,
    "FIAFSGVVL": 37.0 * 1e3,    "FIAFSCPVL": 27.0 * 1e3
}

DEFAULT_SETTINGS = {
    "fx_rate": 15400,
    "limits": {
        "FIAFSGVID": 10.3, "FIAFSCPID": 3.7, "FIAFSGVVL": 24.0, 
        "FIAFSCPVL": 30.0, "FIHTMGVID": 1.8, "FIHTMCPID": 0.0,
        "FIHTMGVVL": 0.0, "FIHTMCPVL": 4.9
    }
}

def format_currency(val, ccy):
    if val == 0 or pd.isna(val): return "0"
    abs_val = abs(val)
    prefix = "-" if val < 0 else ""
    if ccy == 'IDR':
        if abs_val >= 1e12: res = f"{abs_val/1e12:.2f} Tn"
        elif abs_val >= 1e9: res = f"{abs_val/1e9:.2f} Bn"
        else: res = f"{abs_val/1e6:.2f} Mn"
    else:
        if abs_val >= 1e6: res = f"{abs_val/1e6:.2f} Mn"
        else: res = f"{abs_val/1e3:.2f} Th"
    return prefix + res

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
        df['GL_RAW'] = df['UNREALIZED_LOSS_GAIN_AFS_TB'].apply(clean_num)
        df['DUR'] = df.apply(lambda r: calc_mod_duration(r, eval_date), axis=1)
        df['PV01_RAW'] = df['OS_RAW'] * df['DUR'] * 0.0001
        
        # Pie Chart Data Construction
        # 1. Govt vs Corp
        govt_total = df[df['ISSUER_TYPE'].str.contains('Gov', na=False, case=False)]['OS_RAW'].sum()
        corp_total = df[~df['ISSUER_TYPE'].str.contains('Gov', na=False, case=False)]['OS_RAW'].sum()
        pie_data = {
            "govt_corp": [round(govt_total), round(corp_total)],
            "idr_books": [],
            "vl_books": []
        }
        
        summary = []
        details = {}
        all_pids = ["FITRGVID", "FITRGVVL", "FITRCPID", "FITRCPVL", "FIAFSGVID", "FIAFSGVVL", "FIAFSCPID", "FIAFSCPVL", "FIHTMGVID", "FIHTMGVVL", "FIHTMCPID", "FIHTMCPVL"]
        
        for pid in all_pids:
            sub = df[df['PORTFOLIO'] == pid].copy()
            os_act = sub['OS_RAW'].sum()
            gl_total = sub['GL_RAW'].sum() if "HTM" not in pid else 0
            ccy = 'USD' if pid.endswith('VL') else 'IDR'
            
            # OS Logic
            limit_val = settings['limits'].get(pid, 0)
            limit_base = limit_val * (1e12 if ccy == 'IDR' else 1e6)
            os_util = round((os_act / limit_base * 100), 1) if limit_base > 0 else 0
            
            # PV01 Logic (Comparing base units to base units)
            pv_act_base = sub['PV01_RAW'].sum()
            pv_limit_base = PV01_LIMITS_BASE.get(pid, 0)
            pv_util = round((pv_act_base / pv_limit_base * 100), 1) if pv_limit_base > 0 else 0

            summary.append({
                "id": pid, "ccy": ccy, "os_fmt": format_currency(os_act, ccy),
                "os_util": os_util, "gl_fmt": format_currency(gl_total, ccy) if "HTM" not in pid else "N/A",
                "pv_act_fmt": format_currency(pv_act_base, ccy), "pv_util": pv_util,
                "dur": round(np.average(sub['DUR'], weights=sub['OS_RAW']), 2) if os_act > 0 else 0,
                "type": "TRADING" if "TR" in pid else "BANKING"
            })
            
            bond_list = []
            for _, r in sub.iterrows():
                bond_list.append({
                    "t": str(r.get('TICKER', '-')), "c": f"{clean_num(r.get('COUPON', 0)):.2f}%", 
                    "m": pd.to_datetime(r.get('MATURITY_DATE')).strftime('%d-%m-%Y') if pd.notna(r.get('MATURITY_DATE')) else '-',
                    "os": format_currency(clean_num(r.get('OUTSTANDING', 0)), ccy),
                    "ad": pd.to_datetime(r.get('ACQ_DATE')).strftime('%d-%m-%Y') if pd.notna(r.get('ACQ_DATE')) else '-',
                    "cp": f"{clean_num(r.get('ACQ_PRICE', 0)):.2f}", "mtm": f"{clean_num(r.get('MTM', 0)):.2f}",
                    "gl": format_currency(clean_num(r.get('UNREALIZED_LOSS_GAIN_AFS_TB', 0)), ccy) if "HTM" not in pid else "-",
                    "d": r.get('DUR', 0)
                })
            details[pid] = bond_list

        return render_template('dashboard.html', summary=summary, details=details, settings=settings, pie=pie_data)
    except Exception as e:
        return f"Logic Error: {str(e)}"

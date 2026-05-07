import os, json, pandas as pd, numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)
UPLOAD_FOLDER = 'data'
SETTINGS_FILE = 'settings.json'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PV01_LIMITS_BASE = {
    "FITRGVID": 800.0 * 1e6, "FITRCPID": 700.0 * 1e6, "FITRGVVL": 15.0 * 1e3, "FITRCPVL": 15.0 * 1e3,
    "FIAFSGVID": 9000.0 * 1e6, "FIAFSCPID": 3300.0 * 1e6, "FIAFSGVVL": 37.0 * 1e3, "FIAFSCPVL": 27.0 * 1e3
}

DEFAULT_SETTINGS = {"fx_rate": 15400, "limits": {"FIAFSGVID": 10.3, "FIAFSCPID": 3.7, "FIAFSGVVL": 24.0, "FIAFSCPVL": 30.0, "FIHTMGVID": 1.8, "FIHTMCPID": 0.0, "FIHTMGVVL": 0.0, "FIHTMCPVL": 4.9}}

def get_settings():
    try:
        if not os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'w') as f: json.dump(DEFAULT_SETTINGS, f)
            return DEFAULT_SETTINGS
        with open(SETTINGS_FILE, 'r') as f: return json.load(f)
    except: return DEFAULT_SETTINGS

def clean_num(val):
    """Refined to preserve negative signs (-) and handles parentheses (loss)"""
    if pd.isna(val) or val == '': return 0.0
    s = str(val).strip().replace(',', '').replace('%', '')
    # Handle cases like (100.00) which some finance exports use for negative
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    try:
        return float(s)
    except:
        return 0.0

def format_currency(val, ccy):
    """Formatted to explicitly handle the negative sign for UI display"""
    if val == 0 or pd.isna(val): return "0"
    is_neg = val < 0
    v = abs(val)
    
    if ccy == 'IDR':
        if v >= 1e12: res = f"{v/1e12:.20f}"[:4].rstrip('.') + " Tn"
        elif v >= 1e9: res = f"{v/1e9:.2f} Bn"
        else: res = f"{v/1e6:.2f} Mn"
    else:
        if v >= 1e6: res = f"{v/1e6:.2f} Mn"
        else: res = f"{v/1e3:.2f} Th"
        
    return f"-{res}" if is_neg else res

def calc_mod_duration(row, eval_date):
    try:
        y, c = clean_num(row.get('YTM_TO_MTM', 0))/100, clean_num(row.get('COUPON', 0))/100
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
        p = np.sum(cf * dfac)
        mac = np.sum((k/2) * cf * dfac) / p
        return round(mac / (1 + y_m), 2)
    except: return 0.0

@app.route('/')
def index():
    try:
        settings = get_settings()
        eval_date = datetime(2026, 5, 5)
        file_path = os.path.join(UPLOAD_FOLDER, "FI-SISTEM.csv")
        if not os.path.exists(file_path): return redirect(url_for('admin'))
        
        df = pd.read_csv(file_path, skiprows=2)
        df.columns = [c.strip() for c in df.columns]
        
        df['OS_RAW'] = df['OUTSTANDING'].apply(clean_num)
        df['GL_RAW'] = df['UNREALIZED_LOSS_GAIN_AFS_TB'].apply(clean_num)
        df['DUR'] = df.apply(lambda r: calc_mod_duration(r, eval_date), axis=1)
        df['PV01_RAW'] = df['OS_RAW'] * df['DUR'] * 0.0001
        
        # Pie Data Safety
        is_gov = df['ISSUER_TYPE'].str.contains('Gov', na=False, case=False) if 'ISSUER_TYPE' in df.columns else df['TICKER'].str.startswith('FR', na=False)
        p1 = [float(df[is_gov]['OS_RAW'].sum()), float(df[~is_gov]['OS_RAW'].sum())]
        
        def get_book_sum(ccy_suffix):
            tr = df[df['PORTFOLIO'].str.contains(f'TR.*{ccy_suffix}', na=False)]['OS_RAW'].sum()
            afs = df[df['PORTFOLIO'].str.contains(f'AFS.*{ccy_suffix}', na=False)]['OS_RAW'].sum()
            htm = df[df['PORTFOLIO'].str.contains(f'HTM.*{ccy_suffix}', na=False)]['OS_RAW'].sum()
            return [float(tr), float(afs), float(htm)]

        summary, details = [], {}
        all_pids = ["FITRGVID", "FITRGVVL", "FITRCPID", "FITRCPVL", "FIAFSGVID", "FIAFSGVVL", "FIAFSCPID", "FIAFSCPVL", "FIHTMGVID", "FIHTMGVVL", "FIHTMCPID", "FIHTMCPVL"]
        
        for pid in all_pids:
            sub = df[df['PORTFOLIO'] == pid].copy()
            os_act = sub['OS_RAW'].sum()
            ccy = 'USD' if pid.endswith('VL') else 'IDR'
            lim_val = settings['limits'].get(pid, 0)
            lim_base = lim_val * (1e12 if ccy == 'IDR' else 1e6)
            pv_act_base = sub['PV01_RAW'].sum()
            pv_lim_base = PV01_LIMITS_BASE.get(pid, 0)
            
            summary.append({
                "id": pid, "ccy": ccy, "os_fmt": format_currency(os_act, ccy),
                "os_util": round((os_act/lim_base*100),1) if lim_base > 0 else 0,
                "gl_fmt": format_currency(sub['GL_RAW'].sum(), ccy) if "HTM" not in pid else "N/A",
                "gl_raw_total": sub['GL_RAW'].sum(),
                "pv_act_fmt": format_currency(pv_act_base, ccy),
                "pv_util": round((pv_act_base/pv_lim_base*100),1) if pv_lim_base > 0 else 0,
                "dur": round(np.average(sub['DUR'], weights=sub['OS_RAW']),2) if os_act > 0 else 0,
                "type": "TRADING" if "TR" in pid else "BANKING"
            })
            
            bond_rows = []
            for _, r in sub.iterrows():
                raw_gl = clean_num(r.get('UNREALIZED_LOSS_GAIN_AFS_TB', 0))
                bond_rows.append({
                    "t": str(r.get('TICKER','-')), 
                    "c": f"{clean_num(r.get('COUPON',0)):.2f}%", 
                    "m": pd.to_datetime(r.get('MATURITY_DATE')).strftime('%d-%m-%Y') if pd.notna(r.get('MATURITY_DATE')) else '-',
                    "os": format_currency(clean_num(r.get('OUTSTANDING',0)),ccy),
                    "ad": pd.to_datetime(r.get('ACQ_DATE')).strftime('%d-%m-%Y') if pd.notna(r.get('ACQ_DATE')) else '-',
                    "cp": f"{clean_num(r.get('ACQ_PRICE',0)):.2f}", 
                    "mtm": f"{clean_num(r.get('MTM',0)):.2f}",
                    "gl_val": raw_gl,
                    "gl": format_currency(raw_gl, ccy) if "HTM" not in pid else "-",
                    "d": r.get('DUR',0)
                })
            details[pid] = bond_rows

        return render_template('dashboard.html', summary=summary, details=details, settings=settings, pie={"p1":p1, "p2":get_book_sum('ID'), "p3":get_book_sum('VL')})
    except Exception as e:
        return f"<div style='color:white;background:red;padding:20px;font-family:sans-serif;'><h2>Logic Error</h2><p>{str(e)}</p></div>"

@app.route('/admin')
def admin(): return render_template('admin.html', settings=get_settings())

@app.route('/update-settings', methods=['POST'])
def update_settings():
    try:
        s = get_settings()
        if 'fx_rate' in request.form: s['fx_rate'] = float(request.form['fx_rate'])
        if 'port_id' in request.form: s['limits'][request.form['port_id']] = float(request.form['limit_val'])
        with open(SETTINGS_FILE, 'w') as f: json.dump(s, f)
    except: pass
    return redirect(url_for('admin'))

@app.route('/upload', methods=['POST'])
def upload():
    try:
        f = request.files.get('file')
        if f: f.save(os.path.join(UPLOAD_FOLDER, "FI-SISTEM.csv"))
    except: pass
    return redirect(url_for('admin'))

if __name__ == '__main__': app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

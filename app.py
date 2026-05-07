import os, json, pandas as pd, numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)
UPLOAD_FOLDER = 'data'
SETTINGS_FILE = 'settings.json'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Helper to load CSV safely
def load_csv(name, skip=0):
    path = os.path.join(UPLOAD_FOLDER, name)
    if not os.path.exists(path): return None
    try:
        df = pd.read_csv(path, skiprows=skip)
        df.columns = [c.strip() for c in df.columns]
        return df
    except: return None

# ... (Include the format_currency, clean_num, and get_settings from previous versions)

@app.route('/issuers')
def issuers_page():
    settings = get_settings()
    df = load_csv("FI-SISTEM.csv", skip=2)
    limits_df = load_csv("ISSUER_LIMITS.csv") # Our new second file
    
    if df is None: return redirect(url_for('admin'))

    try:
        df['OS_RAW'] = df['OUTSTANDING'].apply(clean_num)
        # Aggregate OS by ISSUER column
        issuer_grouped = df.groupby('ISSUER')['OS_RAW'].sum().reset_index()
        
        # Merge with Limits
        if limits_df is not None:
            # Assume limits_df has columns: 'ISSUER' and 'LIMIT_AMOUNT' (in IDR)
            merged = pd.merge(issuer_grouped, limits_df, on='ISSUER', how='left')
        else:
            merged = issuer_grouped
            merged['LIMIT_AMOUNT'] = 0 # Default if no file
            
        merged['LIMIT_AMOUNT'] = merged['LIMIT_AMOUNT'].fillna(0)
        merged['util'] = (merged['OS_RAW'] / merged['LIMIT_AMOUNT'] * 100).replace([np.inf, -np.inf], 0).fillna(0)
        
        # Final formatting
        issuer_data = []
        for _, r in merged.iterrows():
            issuer_data.append({
                "name": r['ISSUER'],
                "act": format_currency(r['OS_RAW'], 'IDR'),
                "lim": format_currency(r['LIMIT_AMOUNT'], 'IDR'),
                "util": round(r['util'], 2)
            })
            
        return render_template('issuers.html', issuers=issuer_data, settings=settings)
    except Exception as e:
        return f"Issuer Logic Error: {str(e)}"

# Update the upload route to handle multiple files
@app.route('/upload', methods=['POST'])
def upload():
    f = request.files.get('file')
    target = request.form.get('target') # We will add this to the admin form
    if f and target:
        f.save(os.path.join(UPLOAD_FOLDER, target))
    return redirect(url_for('admin'))

# (Keep existing / and /admin routes)

import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import sys
sys.path.insert(0, 'Features')
import trial
import ledger

# --- CORE LOGIC (From previous steps) ---

def to_decimal_exact(val):
    if val is None or pd.isna(val):
        return Decimal('0.00')
    s = str(val).replace(',', '').strip().replace('–', '-').replace('—', '-')
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    if s in ["", "-", "None", "."]:
        return Decimal('0.00')
    try:
        d = Decimal(s)
        return d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal('0.00')

def extract_from_pdf_bytes(pdf_file):
    data = []
    num_pattern = r'\(?[-–—]?\d(?:[\d,.]*\d)?\)?'
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            for line in text.split('\n'):
                match = re.match(r'^(\d{3})\b', line.strip())
                if match:
                    code = match.group(1)
                    found_nums = re.findall(num_pattern, line.strip())
                    clean_nums = [n for n in found_nums if n.strip('()') != code]
                    if len(clean_nums) >= 2:
                        data.append({
                            'Code': code,
                            'PDF_Current': to_decimal_exact(clean_nums[1]),
                            'PDF_Previous': to_decimal_exact(clean_nums[-1])
                        })
    return pd.DataFrame(data)

def extract_from_excel_bytes(excel_file):
    df_raw = pd.read_excel(excel_file)
    header_idx = None
    for i, row in df_raw.iterrows():
        if row.astype(str).str.contains('Code No', case=False).any():
            header_idx = i
            break
    df = pd.read_excel(excel_file, skiprows=header_idx + 1) if header_idx is not None else df_raw
    
    cols = df.columns
    code_col = next((c for c in cols if 'Code' in str(c)), None)
    curr_col = next((c for c in cols if 'Current Year' in str(c)), None)
    prev_col = next((c for c in cols if 'Previous Year' in str(c)), None)

    processed = []
    for _, row in df.iterrows():
        raw_code = str(row[code_col]).split('.')[0].strip()
        if raw_code.isdigit() and len(raw_code) == 3:
            processed.append({
                'Code': raw_code,
                'Excel_Current': to_decimal_exact(row[curr_col]),
                'Excel_Previous': to_decimal_exact(row[prev_col])
            })
    return pd.DataFrame(processed)

# --- GOOGLE DRIVE INTEGRATION ---


# def get_gdrive_service():
#     # 1. First, try to load from Streamlit Cloud Secrets (Production)
#     if "gcp_service_account" in st.secrets:
#         # We convert the secrets back into a dictionary format the library understands
#         service_account_info = dict(st.secrets["gcp_service_account"])
#         # We need to fix the newline characters in the private key if they got mangled
#         service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")
        
#         creds = service_account.Credentials.from_service_account_info(
#             service_account_info, 
#             scopes=['https://www.googleapis.com/auth/drive.readonly']
#         )

#     return build('drive', 'v3', credentials=creds)


def get_gdrive_service():
        # For Local Development: Use service_account.json
    import os
    if os.path.exists('service_account.json'):
        creds = service_account.Credentials.from_service_account_file(
            'service_account.json', 
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
    else:
        raise FileNotFoundError("Could not find service_account.json file.")
    
    return build('drive', 'v3', credentials=creds)

def list_files_in_folder(service, folder_id):
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

def download_file(service, file_id):
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return fh

# --- STREAMLIT UI ---

st.set_page_config(page_title="Auditor", layout="wide")
st.title("📊 Report Auditor")

# Feature selection
feature = st.selectbox("Select Feature", ["Balance Sheet Audit", "Trial Balance Audit", "Ledger Audit"])

# Folder ID input (or hardcode it)
FOLDER_ID = st.sidebar.text_input("Google Drive Folder ID")

if FOLDER_ID:
    try:
        drive_service = get_gdrive_service()
        files = list_files_in_folder(drive_service, FOLDER_ID)
        
        if not files:
            st.warning("No files found in this folder.")
        else:
            col1, col2 = st.columns(2)
            
            with col1:
                type1 = st.selectbox("File Type 1", ["Excel", "PDF"], key="type1")
                filtered1 = []
                if type1 == "Excel":
                    filtered1 = [f for f in files if f['name'].lower().endswith(('.xlsx', '.xls'))]
                elif type1 == "PDF":
                    filtered1 = [f for f in files if f['name'].lower().endswith('.pdf')]
                file1_info = st.selectbox("Select First File", filtered1, format_func=lambda x: x['name'], key="file1")
            
            with col2:
                type2 = st.selectbox("File Type 2", ["Excel", "PDF"], key="type2")
                filtered2 = []
                if type2 == "Excel":
                    filtered2 = [f for f in files if f['name'].lower().endswith(('.xlsx', '.xls'))]
                elif type2 == "PDF":
                    filtered2 = [f for f in files if f['name'].lower().endswith('.pdf')]
                file2_info = st.selectbox("Select Second File", filtered2, format_func=lambda x: x['name'], key="file2")

            if st.button("Run Comparison"):
                with st.spinner("Fetching files and analyzing..."):
                    # Download files into memory
                    file1_data = download_file(drive_service, file1_info['id'])
                    file2_data = download_file(drive_service, file2_info['id'])

                    if feature == "Balance Sheet Audit":
                        # Check file types
                        file1_ext = file1_info['name'].lower().split('.')[-1]
                        file2_ext = file2_info['name'].lower().split('.')[-1]
                        if (file1_ext in ['xlsx', 'xls'] and file2_ext == 'pdf') or (file1_ext == 'pdf' and file2_ext in ['xlsx', 'xls']):
                            # Assign correctly
                            if file1_ext in ['xlsx', 'xls']:
                                excel_data = file1_data
                                pdf_data = file2_data
                            else:
                                excel_data = file2_data
                                pdf_data = file1_data

                            # Process
                            df_excel = extract_from_excel_bytes(excel_data)
                            df_pdf = extract_from_pdf_bytes(pdf_data)

                            print(df_excel.head())
                            print(df_pdf.head())

                           # Align and Compare
                            comparison = pd.merge(df_excel, df_pdf, on='Code', how='outer').fillna(Decimal('0.00'))
                            comparison['Current_Match'] = comparison['Excel_Current'] == comparison['PDF_Current']
                            comparison['Previous_Match'] = comparison['Excel_Previous'] == comparison['PDF_Previous']
                            comparison['Status'] = (comparison['Current_Match'] & comparison['Previous_Match']).map({True: '✅ MATCH', False: '❌ MISMATCH'})

                            # Display results
                            st.subheader("Comparison Result")
                            st.dataframe(comparison.style.map(
                                lambda x: 'background-color: #ffcccc' if x == '❌ MISMATCH' else '', subset=['Status']
                            ), use_container_width=True)

                            # Download Report
                            output = io.BytesIO()
                            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                                comparison.to_excel(writer, index=False)
                            st.download_button(
                                label="Download Excel Report",
                                data=output.getvalue(),
                                file_name="BS_Comparison_Report.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )
                        else:
                            st.error("For Balance Sheet Audit, please select one Excel file and one PDF file.")
                    elif feature == "Trial Balance Audit":
                        # Assume file1 is old, file2 is new
                        if type1 == "PDF" and type2 == "PDF":
                            df_old = trial.extract_from_pdf(file1_data, 'old')
                            df_new = trial.extract_from_pdf(file2_data, 'new')
                            comparison = pd.merge(df_old, df_new, on='Code', how='outer').fillna(Decimal('0.00'))
                            # Add match columns if needed, but for now display
                            st.subheader("Trial Balance Comparison")
                            st.dataframe(comparison)
                        else:
                            st.error("For Trial Balance Audit, please select two PDF files.")
                    elif feature == "Ledger Audit":
                        # Assume extract from PDF
                        pdf_data = None
                        if type1 == "PDF":
                            pdf_data = file1_data
                        elif type2 == "PDF":
                            pdf_data = file2_data
                        if pdf_data is None:
                            st.error("Please select at least one PDF file for Ledger Audit.")
                        else:
                            df = ledger.extract_from_pdf(pdf_data)
                            st.subheader("Ledger Entries")
                            st.dataframe(df)

    except Exception as e:
        st.error(f"Error connecting to Google Drive: {e}")
else:
    st.info("Please enter a Google Drive Folder ID in the sidebar to begin.")
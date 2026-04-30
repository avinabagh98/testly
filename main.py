import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Import audit modules
from modules.ledger_audit import extract_from_pdf as ledger_extract, compare_ledgers
from Features import trial, ledger as ledger_module
from modules.html2pdf import convert_html_to_pdf


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

def extract_from_pdf_bytes(pdf_file,state):
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
                            f'{state}_Current': to_decimal_exact(clean_nums[1]),
                            f'{state}_Previous': to_decimal_exact(clean_nums[-1])
                        })
    return pd.DataFrame(data)

def extract_from_excel_bytes(file, state, type = 'excel' ):
    df_raw = df = None
    if(type == 'excel'):
        if hasattr(file, 'seek'):
            file.seek(0)
        df_raw = pd.read_excel(file)
    elif(type == 'csv'):
        if hasattr(file, 'seek'):
            file.seek(0)
        df_raw = pd.read_csv(file)
    print("Type of file being processed: ", type)
    header_idx = None
    for i, row in df_raw.iterrows():
        if row.astype(str).str.contains('Code No', case=False).any():
            header_idx = i
            break
        
    if header_idx is None:
        st.warning("Could not find header row with 'Code No'. Processing entire file, which may lead to errors.")
        df = df_raw
    else:
        if hasattr(file, 'seek'):
            file.seek(0)
        df = pd.read_excel(file, skiprows=header_idx + 1) if type == 'excel' else pd.read_csv(file, skiprows=header_idx + 1)
    
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
                f'{state}_Current': to_decimal_exact(row[curr_col]),
                f'{state}_Previous': to_decimal_exact(row[prev_col])
            })
    return pd.DataFrame(processed)

def extract_from_txt_bytes(txt_file, state):
    processed = []
    
    # Pattern: Line starts with 3 digits followed by a description [cite: 6, 12, 32]
    line_pattern = re.compile(r'^\s*(\d{3})\b')
    # Pattern for monetary values (including negatives) [cite: 57]
    num_pattern = r'-?\d+\.\d{2}'

    # Read content from the file-like object
    content = txt_file.read().decode('utf-8')
    
    for line in content.split('\n'):
        line = line.strip()
        if not line: continue
            
        match = line_pattern.match(line)
        if match:
            code = match.group(1)
            
            # Find all currency amounts in the line [cite: 7, 10, 13]
            amounts = re.findall(num_pattern, line)
            
            # Most TXT balance sheets list Current Year then Previous Year [cite: 3, 4, 62, 63]
            if len(amounts) >= 2:
                processed.append({
                    'Code': code,
                    f'{state}_Current': to_decimal_exact(amounts[-2]),
                    f'{state}_Previous': to_decimal_exact(amounts[-1])
                })
                    
    return pd.DataFrame(processed)





# --- GOOGLE DRIVE INTEGRATION ---


def get_gdrive_service():
    # 1. First, try to load from Streamlit Cloud Secrets (Production)
    if "gcp_service_account" in st.secrets:
        # We convert the secrets back into a dictionary format the library understands
        service_account_info = dict(st.secrets["gcp_service_account"])
        # We need to fix the newline characters in the private key if they got mangled
        service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")
        
        creds = service_account.Credentials.from_service_account_info(
            service_account_info, 
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )

    return build('drive', 'v3', credentials=creds)


# def get_gdrive_service():
#         # For Local Development: Use service_account.json
#     import os
#     if os.path.exists('service_account.json'):
#         creds = service_account.Credentials.from_service_account_file(
#             'service_account.json', 
#             scopes=['https://www.googleapis.com/auth/drive.readonly']
#         )
#     else:
#         raise FileNotFoundError("Could not find service_account.json file.")
    
#     return build('drive', 'v3', credentials=creds)

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

st.set_page_config(page_title="Testly", layout="wide")
st.title("📊 Report Auditor")

# Session state for tracking converted files
if 'converted_files' not in st.session_state:
    st.session_state.converted_files = []

# Feature selection
feature = st.selectbox("Select Feature", ["Balance Sheet Audit", "Trial Balance Audit", "Ledger Audit", "HTML to PDF"])

# Folder ID input (or hardcode it)
FOLDER_ID = st.sidebar.text_input("Google Drive Folder ID")

if FOLDER_ID:

    try:
        drive_service = get_gdrive_service()
        files = list_files_in_folder(drive_service, FOLDER_ID)
        
        if not files:
            st.warning("No files found in this folder.")
        else:
            # HTML to PDF feature - single file selection
            if feature == "HTML to PDF":
                html_files = [f for f in files if f['name'].lower().endswith(('.html', '.htm'))]
                if not html_files:
                    st.warning("No HTML files found in this folder.")
                else:
                    selected_html = st.selectbox("Select HTML File", html_files, format_func=lambda x: x['name'])

                    # Display converted files history
                    if st.session_state.converted_files:
                        st.sidebar.subheader("Recently Converted Files")
                        for fname in reversed(st.session_state.converted_files[-10:]):
                            st.sidebar.text(fname)

                    if st.button("Convert to PDF"):
                        with st.spinner("Converting HTML to PDF..."):
                            try:
                                html_data = download_file(drive_service, selected_html['id'])
                                pdf_bytes = convert_html_to_pdf(html_data, selected_html['name'])

                                # Add to converted files list
                                st.session_state.converted_files.append(
                                    f"{selected_html['name']} -> Generated{selected_html['name'].rsplit('.', 1)[0]}.pdf"
                                )

                                # Download button
                                st.download_button(
                                    label="Download PDF",
                                    data=pdf_bytes,
                                    file_name='Generated ' + selected_html['name'].rsplit('.', 1)[0] + '.pdf',
                                    mime="application/pdf"
                                )
                                st.success(f"Converted: {selected_html['name']}")
                            except Exception as e:
                                st.warning(f"Error converting HTML to PDF: {e}")
            else:
                # Other features - two file selection
                col1, col2 = st.columns(2)

                with col1:
                    type1 = st.selectbox("File Type (Purohisab 2.0)", ["Excel"] if feature == "Balance Sheet Audit" else ["Excel", "PDF"], key="type1")
                    filtered1 = []
                    if type1 == "Excel":
                        filtered1 = [f for f in files if f['name'].lower().endswith(('.xlsx', '.xls'))]
                    elif type1 == "PDF":
                        filtered1 = [f for f in files if f['name'].lower().endswith('.pdf')]
                    file1_info = st.selectbox("Select First File", filtered1, format_func=lambda x: x['name'], key="file1")

                with col2:
                    type2 = st.selectbox("File Type (Old System)", ["Excel", "PDF", "CSV", "Txt"], key="type2")
                    filtered2 = []
                    if type2 == "Excel":
                        filtered2 = [f for f in files if f['name'].lower().endswith(('.xlsx', '.xls',))]
                    elif type2 == "PDF":
                        filtered2 = [f for f in files if f['name'].lower().endswith('.pdf')]
                    elif type2 == "CSV":
                        filtered2 = [f for f in files if f['name'].lower().endswith('.csv')]
                    elif type2 == "Txt":
                        filtered2 = [f for f in files if f['name'].lower().endswith('.txt')]
                    file2_info = st.selectbox("Select Second File", filtered2, format_func=lambda x: x['name'], key="file2")

                # Show Ledger Audit parameters in sidebar when Ledger Audit is selected
                if feature == "Ledger Audit":
                    st.sidebar.subheader("Ledger Audit Parameters")
                    ledger_code = st.sidebar.text_input(
                        "Ledger Code",
                        help="Enter ledger code to extract (e.g., 3109001)"
                    )
                else:
                    ledger_code = None

                if st.button("Run Comparison"):
                    with st.spinner("Fetching files and analyzing..."):
                        # Download files into memory
                        file1_data = download_file(drive_service, file1_info['id'])
                        file2_data = download_file(drive_service, file2_info['id'])

                        if feature == "Balance Sheet Audit":
                            # Check file types
                            file1_ext = file1_info['name'].lower().split('.')[-1]
                            file2_ext = file2_info['name'].lower().split('.')[-1]
                            if (file1_ext in ['xlsx', 'xls'] and file2_ext in ['pdf', 'xls', 'xlsx', 'csv', 'txt']):
                                # Excel Files
                                if file2_ext in ['xlsx', 'xls']:
                                    excel_data_new = file1_data
                                    excel_data_old = file2_data
                                    try:
                                        df_new = extract_from_excel_bytes(excel_data_new, 'new')
                                        df_old = extract_from_excel_bytes(excel_data_old, 'old')
                                    except Exception as e:
                                        st.error(f"Error processing files: {e}")
                                        st.exception(e, width='stretch')

                                # CSV Files
                                elif(file2_ext in ['csv']):
                                    excel_data_new = file1_data
                                    csv_data_old = file2_data
                                    try:
                                        df_new = extract_from_excel_bytes(excel_data_new, 'new')
                                        df_old = extract_from_excel_bytes(csv_data_old, 'old', 'csv')
                                        print(" old data",df_old.head())
                                        print(" new data",df_new.head())
                                    except Exception as e:
                                        st.error(f"Error processing files: {e}")
                                        st.exception(e, width='stretch')



                                # TXT Files
                                elif(file2_ext in ['txt']):
                                    excel_data_new = file1_data
                                    txt_data_old = file2_data
                                    try:
                                            df_new = extract_from_excel_bytes(excel_data_new, 'new')
                                            df_old = extract_from_txt_bytes(txt_data_old, 'old')
                                    except Exception as e:
                                            st.error(f"Error processing files: {e}")
                                            st.exception(e, width='stretch')



                                # PDF Files
                                elif(file2_ext in ['pdf']):
                                    excel_data_new = file1_data
                                    pdf_data_old = file2_data
                                    try:
                                    # Process
                                        df_new = extract_from_excel_bytes(excel_data_new, 'new')
                                        df_old = extract_from_pdf_bytes(pdf_data_old, 'old')
                                    except Exception as e:
                                        st.error(f"Error processing files: {e}")
                                        st.exception(e, width='stretch')
    

                            # Align and Compare
                                comparison = pd.merge(df_new, df_old, on='Code', how='outer').fillna(Decimal('0.00'))
                                comparison['Current_Match'] = comparison['new_Current'] == comparison['old_Current']
                                comparison['Previous_Match'] = comparison['new_Previous'] == comparison['old_Previous']
                                comparison['Status'] = (comparison['Current_Match'] & comparison['Previous_Match']).map({True: '✅ MATCH', False: '❌ MISMATCH'})

                                # Display results
                                st.subheader("Comparison Result")
                                st.dataframe(comparison.style.map(
                                    lambda x: 'background-color: #ffcccc' if x == '❌ MISMATCH' else '', subset=['Status']
                                ), width='stretch')

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
                            # Ledger Audit requires two PDF files for comparison
                            if type1 == "PDF" and type2 == "PDF":
                                pdf_new_data = file1_data
                                pdf_old_data = file2_data

                                if not ledger_code:
                                    st.error("Please enter a Ledger Code in the sidebar.")
                                else:
                                    with st.spinner("Extracting ledger entries from PDFs..."):
                                        try:
                                            df_old = ledger_extract(
                                                pdf_old_data, state='old',
                                                desired_acc_head=ledger_code
                                            )
                                            df_new = ledger_extract(
                                                pdf_new_data, state='new',
                                                desired_acc_head=ledger_code
                                            )
                                            print("New Ledger Data:\n", df_new.head())
                                        except Exception as e:
                                            st.error(f"Error extracting ledger data: {e}")
                                            df_old, df_new = None, None

                                    if df_old is None or df_new is None:
                                        pass
                                    elif df_old.empty and df_new.empty:
                                        st.warning("No ledger entries found. Check the ledger code or PDF format.")
                                    elif df_old.empty:
                                        st.warning("No ledger entries found in the old PDF. Only new entries shown.")
                                        comparison = df_new.copy()
                                        comparison['Status'] = '✅ NEW ONLY'
                                        st.subheader("Ledger Entries (New)")
                                        st.dataframe(comparison, width = 'stretch')
                                    elif df_new.empty:
                                        st.warning("No ledger entries found in the new PDF. Only old entries shown.")
                                        comparison = df_old.copy()
                                        comparison['Status'] = '✅ OLD ONLY'
                                        st.subheader("Ledger Entries (Old)")
                                        st.dataframe(comparison, width = 'stretch')
                                    else:
                                        # Compare ledgers
                                        try:
                                            comparison = compare_ledgers(df_new, df_old)
                                        except Exception as e:
                                            st.error(f"Error comparing ledgers: {e}")
                                            st.write("New DF columns:", list(df_new.columns))
                                            st.write("Old DF columns:", list(df_old.columns))
                                            st.stop()

                                        st.subheader("Ledger Comparison Result")
                                        st.dataframe(
                                            comparison.style.map(
                                                lambda x: 'background-color: #ffcccc' if x == '❌ MISMATCH' else '',
                                                subset=['Status']
                                            ),
                                            width = 'stretch'
                                        )

                                        # Summary stats
                                        col1, col2, col3 = st.columns(3)
                                        total_entries = len(comparison)
                                        matched = len(comparison[comparison['Status'] == '✅ MATCH'])
                                        mismatched = len(comparison[comparison['Status'] == '❌ MISMATCH'])
                                        col1.metric("Total Entries", total_entries)
                                        col2.metric("Matched", matched)
                                        col3.metric("Mismatched", mismatched, delta=f"{mismatched/total_entries*100:.1f}%" if total_entries > 0 else "0%")

                                        # Download Report
                                        output = io.BytesIO()
                                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                                            comparison.to_excel(writer, index=False)
                                        st.download_button(
                                            label="Download Ledger Comparison Report",
                                            data=output.getvalue(),
                                            file_name="Ledger_Comparison_Report.xlsx",
                                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                                        )
                            else:
                                st.error("For Ledger Audit, please select two PDF files.")
                

    except Exception as e:
        st.error(f"Error occuring: {e}")
        st.exception(e, width='stretch')
else:
    st.info("Please enter a Google Drive Folder ID in the sidebar to begin.")
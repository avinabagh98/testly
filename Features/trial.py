
import pandas as pd
import pdfplumber
import re
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP



def to_decimal_exact(val):
    """
    Converts values to Decimal and forces exactly 2 decimal places
    to eliminate floating-point noise (e.g., .38000011 -> .38).
    """
    if val is None or pd.isna(val):
        return Decimal('0.00')
    
    # Clean the string
    s = str(val).replace(',', '').strip()
    s = s.replace('–', '-').replace('—', '-') # Normalize dashes
    
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
        
    if s in ["", "-", "None", "."]:
        return Decimal('0.00')
    
    try:
        d = Decimal(s)
        return d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None

def extract_from_pdf(pdf_file, state):
    data = []
    num_pattern = r'\(?[-–—]?\d(?:[\d,.]*\d)?\)?'
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            table = page.find_tables()
            print(page)
            print(table)

            if not text: continue
            for line in text.split('\n'):
                match = re.match(r'^(\d{7})\b', line.strip())
                if match:
                    code = match.group(1)
                    found_nums = re.findall(num_pattern, line.strip())
                    # clean_nums = [n for n in found_nums if n.strip('()') != code]
                    try:
                        if len(found_nums)>=2:
                            if(state == 'old'):
                                data.append({
                                    'Code': code,
                                    'Pdf_Old_Opening_Dr': to_decimal_exact(found_nums[1]),
                                    'Pdf_Old_Opening_Cr': to_decimal_exact(found_nums[2]),
                                    'Pdf_Old_Period_Dr': to_decimal_exact(found_nums[3]),
                                    'Pdf_Old_Period_Cr': to_decimal_exact(found_nums[4]),
                                    'Pdf_Old_Closing_Dr': to_decimal_exact(found_nums[5]),
                                    'Pdf_Old_Closing_Cr': to_decimal_exact(found_nums[6])
                                })
                            elif(state == 'new'):
                                data.append({
                                    'Code': code,
                                    'Pdf_New_Opening_Dr': to_decimal_exact(found_nums[1]),
                                    'Pdf_New_Opening_Cr': to_decimal_exact(found_nums[2]),
                                    'Pdf_New_Period_Dr': to_decimal_exact(found_nums[3]),
                                    'Pdf_New_Period_Cr': to_decimal_exact(found_nums[4]),
                                    'Pdf_New_Closing_Dr': to_decimal_exact(found_nums[5]),
                                    'Pdf_New_Closing_Cr': to_decimal_exact(found_nums[6])
                            })
                    except Exception as e:
                        # print(f"Error processing line: {line.strip()} with error: {e}")
                        continue
                    
                     
    return pd.DataFrame(data)

def extract_from_excel_bytes(excel_file, state):
    # 1. Load raw data to locate the header row dynamically
    df_raw = pd.read_excel(excel_file)
    header_idx = None
    
    # Search for 'Account Code' or 'Code No' to find where the table starts
    for i, row in df_raw.iterrows():
        if row.astype(str).str.contains('Code', case=False).any():
            header_idx = i
            break
            
    # 2. Re-read the file starting from the detected header
    if header_idx is not None:
        df = pd.read_excel(excel_file, skiprows=header_idx + 1)
    else:
        df = df_raw
    
    cols = df.columns
    
    # Helper to find columns by checking multiple keywords
    def find_col(keywords, exclude=None):
        for c in cols:
            col_name = str(c).lower()
            # Must contain all keywords
            if all(kw.lower() in col_name for kw in keywords):
                # Must NOT contain excluded keywords
                if exclude and any(ex.lower() in col_name for ex in exclude):
                    continue
                return c
        return None

    # Mapping based on your Bhadreswar TB structure:
    # "Opening Debit", "Debit Amount" (Period), "Closing Debit"
    mapping = {
        'code': find_col(['Code']),
        'op_dr': find_col(['Opening', 'Debit']),
        'op_cr': find_col(['Opening', 'Credit']),
        'per_dr': find_col(['Debit'], exclude=['Opening', 'Closing']), # Finds "Debit Amount"
        'per_cr': find_col(['Credit'], exclude=['Opening', 'Closing']), # Finds "Credit Amount"
        'clo_dr': find_col(['Closing', 'Debit']),
        'clo_cr': find_col(['Closing', 'Credit'])
    }

    processed = []
    col_prefix = f"Excel_{state.capitalize()}_"

    for _, row in df.iterrows():
        # Get the Code and clean it (remove .0 if it's a float)
        raw_val = str(row[mapping['code']]).split('.')[0].strip()
        
        # Validates 7-digit codes (Trial Balance) or 3-digit (Balance Sheet)
        if raw_val.isdigit() and len(raw_val) in [3, 7]:
            processed.append({
                'Code': raw_val,
                f'{col_prefix}Opening_Dr': to_decimal_exact(row[mapping['op_dr']]),
                f'{col_prefix}Opening_Cr': to_decimal_exact(row[mapping['op_cr']]),
                f'{col_prefix}Period_Dr': to_decimal_exact(row[mapping['per_dr']]),
                f'{col_prefix}Period_Cr': to_decimal_exact(row[mapping['per_cr']]),
                f'{col_prefix}Closing_Dr': to_decimal_exact(row[mapping['clo_dr']]),
                f'{col_prefix}Closing_Cr': to_decimal_exact(row[mapping['clo_cr']])
            })
            
    return pd.DataFrame(processed)




def run_comparison(pdf_new, pdf_old):
    # 1. Get Data
    df_new = extract_from_pdf(pdf_new, state='new')
    df_old = extract_from_pdf(pdf_old, state='old')

    # 2. Match on Code
    comparison = pd.merge(df_new, df_old, on='Code', how='outer')

    print(comparison.head())

    # 3. Exact Matching Logic
    # comparison['Opening_Dr_Match'] = (comparison['Pdf_New_Opening_Dr'] == comparison['Pdf_Old_Opening_Dr'])
    # comparison['Opening_Cr_Match'] = (comparison['Pdf_New_Opening_Cr'] == comparison['Pdf_Old_Opening_Cr'])
    # comparison['Period_Dr_Match'] = (comparison['Pdf_New_Period_Dr  '] == comparison['Pdf_Old_Period_Dr'])
    # comparison['Period_Cr_Match'] = (comparison['Pdf_New_Period_Cr'] == comparison['Pdf_Old_Period_Cr'])    
    # comparison['Closing_Dr_Match'] = (comparison['Pdf_New_Closing_Dr'] == comparison['Pdf_Old_Closing_Dr'])
    # comparison['Closing_Cr_Match'] = (comparison['Pdf_New_Closing_Cr'] == comparison['Pdf_Old_Closing_Cr'])

    # print("Comparison Results:", comparison['Opening_Dr_Match'])
    
    

# Filenames
pdf_new = './Public/TB_New_FY16-17.pdf'
pdf_old = './Public/TB_Old_FY16-17.pdf'

excel_old = './Public/TB_Old_FY25.xlsx'
excel_new = './Public/TB_New_FY25.xlsx'

if __name__ == "__main__":
    # run_comparison(pdf_new, pdf_old)

    # df_new = extract_from_pdf(pdf_old, state='new')
    # print("Extracted New PDF Data:")
    # print(df_new.tail())

    res = extract_from_excel_bytes(excel_old, state='new')
    # res.to_excel('./Public/Extracted_Excel_Old.xlsx', index=False)
    print(res.head())
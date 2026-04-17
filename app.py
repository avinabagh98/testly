

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
        # Convert to decimal first
        d = Decimal(s)
        # Force it to 2 decimal places (standard for Balance Sheets)
        # This is the ONLY way to fix the 947122064.38000011 error.
        return d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal('0.00')


# def clean_code(val):
#     """Standardizes code to 3-digit string."""
#     if pd.isna(val): return None
#     match = re.search(r'(\d{3})', str(val))
#     print(">>>>>>>>", match)
#     return match.group(1) if match else None

# def extract_from_pdf(pdf_path):
#     """Extracts data by scanning text for 3-digit codes and amounts."""
#     data = []
#     print(f"Scanning PDF text for codes...")
    
#     with pdfplumber.open(pdf_path) as pdf:
#         for page in pdf.pages:
#             text = page.extract_text()
#             if not text: continue

#             # print(f"Processing {text}...")
            
#             for line in text.split('\n'):
#                 # Look for lines starting with a 3-digit code
#                 # Pattern: Starts with 3 digits, followed by text and then numbers
#                 match = re.match(r'^(\d{3})\b', line.strip())
#                 if match:
#                     code = match.group(1)
                    
#                     # Find all potential currency/number strings in the line
#                     # This handles: 1,23,456.00 or -1234.56 or (123.00)
#                     num_pattern = '\(?[-–—]?\d(?:[\d,.]*\d)?\)?'
#                     # numbers = re.findall(r'\(?\d[\d,.]*\d\)?', line)
#                     numbers = re.findall(num_pattern, line)
                    
#                     # Usually: [Code, Current, Previous] or [Code, Junk, Current, Junk, Previous]
#                     # We filter out the code itself from the numbers list
#                     clean_nums = [n for n in numbers if n != code]
                    
#                     # Financial reports often have numbers in specific positions.
#                     # Based on your sample: the first number is Current, the second is Previous.
#                     if len(clean_nums) >= 2:
#                         data.append({
#                             'Code': code,
#                             'PDF_Current': to_decimal_exact(clean_nums[1]),
#                             'PDF_Previous': to_decimal_exact(clean_nums[-1]) # Grab the last one as previous
#                         })
#     return pd.DataFrame(data)

# def extract_from_excel(excel_path):
#     """Extracts data from an Excel file with strict decimal handling."""
#     # We read without dtype=str here because we handle the conversion manually for better control
#     df_raw = pd.read_excel(excel_path)
    
#     # 1. Find the header row (searching for 'Code No.')
#     header_idx = None
#     for i, row in df_raw.iterrows():
#         if row.astype(str).str.contains('Code No', case=False).any():
#             header_idx = i
#             break
            
#     if header_idx is not None:
#         # Re-read from the correct header
#         df = pd.read_excel(excel_path, skiprows=header_idx + 1)
#     else:
#         df = df_raw

#     # 2. Identify columns by keywords
#     cols = df.columns
#     code_col = next((c for c in cols if 'Code' in str(c)), None)
#     curr_col = next((c for c in cols if 'Current Year' in str(c)), None)
#     prev_col = next((c for c in cols if 'Previous Year' in str(c)), None)

#     if not all([code_col, curr_col, prev_col]):
#         print("Error: Could not find all required columns (Code, Current, Previous).")
#         return pd.DataFrame()

#     # 3. Process the data
#     processed_data = []
#     for _, row in df.iterrows():
#         # Clean the code (ensure it's a 3-digit string)
#         raw_code = str(row[code_col]).split('.')[0].strip()
        
#         if raw_code.isdigit() and len(raw_code) == 3:
#             processed_data.append({
#                 'Code': raw_code,
#                 'Excel_Current': to_decimal_exact(row[curr_col]),
#                 'Excel_Previous': to_decimal_exact(row[prev_col])
#             })

#     return pd.DataFrame(processed_data)

def extract_from_pdf_bytes(pdf_file, state):
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
                    if len(clean_nums)>=2:
                        if(state == 'old'):
                            data.append({
                                'Code': code,
                                'Pdf_Old_Current': to_decimal_exact(clean_nums[1]),
                                'Pdf_Old_Previous': to_decimal_exact(clean_nums[-1])
                            })
                        elif(state == 'new'):
                            data.append({
                                'Code': code,
                                'Pdf_New_Current': to_decimal_exact(clean_nums[1]),
                                'Pdf_New_Previous': to_decimal_exact(clean_nums[-1])
                            })
                     
    return pd.DataFrame(data)



def run_comparison(pdf_new, pdf_old):
    # 1. Get Data
    df_new = extract_from_pdf_bytes(pdf_new, state='new')
    df_old = extract_from_pdf_bytes(pdf_old, state='old')

    # 2. Match on Code
    comparison = pd.merge(df_new, df_old, on='Code', how='outer')
    
    # 3. Exact Matching Logic
    comparison['Current_Match'] = (comparison['Pdf_New_Current'] == comparison['Pdf_Old_Current'])
    comparison['Previous_Match'] = (comparison['Pdf_New_Previous'] == comparison['Pdf_Old_Previous'])
    
    comparison['Status'] = comparison.apply(
        lambda x: 'MATCH' if (x['Current_Match'] and x['Previous_Match']) else 'MISMATCH', axis=1
    )
    
    # 4. Save
    output = "Balance_Sheet_Match_Report.xlsx"
    # comparison.to_excel(output, index=False)
    print(f"\nReport generated: {output}")
    
    # Show summary
    mismatches = comparison[comparison['Status'] == 'MISMATCH']
    if mismatches.empty:
        print("✅ ALL CODES MATCH PERFECTLY!")
    else:
        print(f"❌ {len(mismatches)} discrepancies found. Details:")
        print(mismatches[['Code', 'Pdf_New_Current', 'Pdf_Old_Current', 'Pdf_New_Previous', 'Pdf_Old_Previous']])

# Filenames
pdf_new = './Public/BS_new_FY22.pdf'
pdf_old = './Public/BS_old_FY22.pdf'

if __name__ == "__main__":
    run_comparison(pdf_new, pdf_old)
    # extract_pdf = extract_from_pdf(pdf_name)
    # print(extract_pdf)
    # extract_pdf.to_excel("Extracted_PDF_Data.xlsx", index=False)

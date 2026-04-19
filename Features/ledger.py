
import pandas as pd
import pdfplumber
import re
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

desired_acc_head = '3109001'
start_date = '2012-04-01'
end_date = '2013-03-31'

# Extract the OpeningBalance seperately

#Transform the extracted data to a DataFrame with columns: date, vch_type, vch_no, debit, credit
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
    start_extract = False
    num_pattern = r'\(?[-–—]?\d[\d,]*\.?\d*\)?'
    ledger_code_pattern = re.compile(rf'\bLedger\s*Code\b.*\b{re.escape(desired_acc_head)}\b', re.I)
    ledger_name_pattern = re.compile(r'^\s*Ledger\s+Name\b', re.I)
    # date_pattern = re.compile(r'^(\d{2}/\d{2}/\d{4})\b')
    date_pattern = re.compile(
    r'^\s*\d{1,2}-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2,4}\b',
    re.I
    )
    # vch_pattern = re.compile(r'^(\d{2}/\d{2}/\d{4})\s+(Journal|Payment|Receipt|Contra)\b.*?\b(\d+)\b', re.I)
    vch_pattern = re.compile(
    r'^(\d{1,2}-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2,4})'  # date
    r'.*?\b(Journal|Payment|Receipt|Contra)\b'                               # voucher type
    r'.*?\b(\d+)\b',                                                         # voucher number
    re.I
    )

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()

            if not text:
                continue

            for line in text.split('\n'):
                line_stripped = line.strip()

                # print(f"Processing line: '{line_stripped}'")

                if not start_extract:
                    
                    if ledger_code_pattern.search(line_stripped):
                        # print("<<<<<<<<<<<<<<<<<<<<<<>>>>>>>>>>>>>>>>>>>>")
                        start_extract = True
                    continue

                if ledger_name_pattern.match(line_stripped):
                    return pd.DataFrame(data)

                if not date_pattern.search(line_stripped):
                    # print(f'Skipping line (no date match): "{line_stripped}"')
                    continue

                m = vch_pattern.search(line_stripped)
                if not m:
                    # print(f'Skipping line (no voucher match): "{line_stripped}"')
                    continue

                # print(f"Matched line: '{line_stripped}'")
              

                date_text = m.group(1)
                vch_type = m.group(3)
                vch_no = m.group(4)

                # remove voucher number from the line so it is not counted as a debit/credit amount
                line_for_amounts = re.sub(rf'\b{re.escape(vch_no)}\b', ' ', line_stripped, count=1)
                found_nums = re.findall(num_pattern, line_for_amounts)
                amounts = [to_decimal_exact(n) for n in found_nums if to_decimal_exact(n) is not None]

                debit = Decimal('0.00')
                credit = Decimal('0.00')
                if len(amounts) >= 2:
                    debit, credit = amounts[-2], amounts[-1]
                elif len(amounts) == 1:
                    debit = amounts[0]
                
                if(state == 'old'):
                    data.append({
                    'date': date_text,
                    'vch_type': vch_type,
                    'vch_no': vch_no,
                    'debit_old': debit,
                    'credit_old': credit,
                })
                elif(state == 'new'):
                    data.append({
                    'date': date_text,
                    'vch_type': vch_type,
                    'vch_no': vch_no,
                    'debit_new': debit,
                    'credit_new': credit,
                })
                

    return pd.DataFrame(data)



def run_comparison(pdf_new, pdf_old):
    # 1. Get Data
    df_new = extract_from_pdf(pdf_new, state='new')
    df_old = extract_from_pdf(pdf_old, state='old')

    print("New Data Extracted:\n", df_new)
    print("Old Data Extracted:\n", df_old)

    # 2. Match on Code
    comparison = pd.merge(df_new, df_old, on=['date','vch_type', 'vch_no'], how='outer')

    # 3. Exact Matching Logic
    comparison['dr_match'] = (comparison['debit_new'] == comparison['debit_old'])
    comparison['cr_match'] = (comparison['credit_new'] == comparison['credit_old'])

    print("Debit Comparison Results:", comparison['dr_match'] )
    print("Credit Comparison Results:", comparison['cr_match'] )


# Filenames
pdf_new = './Public/3109001_ledger_new_FY2013.pdf'
pdf_old = './Public/3109001_ledger_old_FY2013.pdf'


if __name__ == "__main__":
    run_comparison(pdf_new, pdf_old)
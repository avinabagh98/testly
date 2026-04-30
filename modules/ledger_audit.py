"""
Ledger Audit Module
Extracts and compares ledger entries from PDF files.
"""

import pandas as pd
import pdfplumber
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def to_decimal_exact(val):
    """
    Converts values to Decimal and forces exactly 2 decimal places
    to eliminate floating-point noise.
    """
    if val is None or pd.isna(val):
        return Decimal('0.00')

    s = str(val).replace(',', '').strip()
    s = s.replace('–', '-').replace('—', '-')

    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]

    if s in ["", "-", "None", "."]:
        return Decimal('0.00')

    try:
        d = Decimal(s)
        return d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def extract_from_pdf(pdf_file, state, desired_acc_head):

    """
    Extracts ledger entries from a PDF file for a specific ledger code.

    Args:
        pdf_file: File-like object (BytesIO) containing PDF data
        state: 'old' or 'new' - determines column naming
        desired_acc_head: Ledger code to filter by (e.g., '3109001')

    Returns:
        DataFrame with columns: date, vch_type, vch_no, debit, credit
    """
    data = []
    start_extract = False

    num_pattern = r'\(?[-–—]?\d[\d,]*\.?\d*\)?'
    # Pattern to find the ledger code header - matches "Ledger Code" followed by the specific code
    ledger_code_pattern = re.compile(rf'\bLedger\s*Code\b.*?\b{re.escape(desired_acc_head)}\b', re.I)
    # Pattern to detect end of ledger section
    ledger_name_pattern = re.compile(r'^\s*Ledger\s+Name\b', re.I)
    # Date pattern: DD-MMM-YYYY or DD-MMM-YY format
    date_pattern = re.compile(
        r'\d{1,2}-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2,4}',
        re.I
    )
    # Voucher pattern: date + voucher type + voucher number
    vch_pattern = re.compile(
        r'(\d{1,2}-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2,4})'
        r'.*?\b(Journal|Payment|Receipt|Contra)\b'
        r'.*?\b(\d+)\b',
        re.I
    )

    with pdfplumber.open(pdf_file) as pdf:

        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.split('\n'):
                line_stripped = line.strip()

                # Start extraction when ledger code is found
                if not start_extract:
                    if ledger_code_pattern.search(line_stripped):
                        start_extract = True
                        print(f"ledger code {line_stripped}" ) if state == 'new' else None
                    continue

                # Stop at ledger name (end of voucher section)
                if ledger_name_pattern.match(line_stripped):
                    # print(f"ledger name {line_stripped}" )
                    return pd.DataFrame(data)

                # Skip lines without date
                if not date_pattern.search(line_stripped):
                    # print(f"Skipping ::date not found {line_stripped}" )
                    continue

                m = vch_pattern.search(line_stripped)
                if not m:
                    # print(f"Skipping ::voucher pattern not found {line_stripped}" )
                    continue

                date_text = m.group(1)
                vch_type = m.group(3)
                vch_no = m.group(4)

                if state == 'new':
                    print(f"Extracted - Date: {date_text}, Voucher Type: {vch_type}, Voucher No: {vch_no}" )

                # Remove voucher number from line to avoid matching it as amount
                line_for_amounts = re.sub(rf'\b{re.escape(vch_no)}\b', ' ', line_stripped, count=1)
                found_nums = re.findall(num_pattern, line_for_amounts)
                amounts = [to_decimal_exact(n) for n in found_nums if to_decimal_exact(n) is not None]

                debit = Decimal('0.00')
                credit = Decimal('0.00')
                if len(amounts) >= 2:
                    debit, credit = amounts[-2], amounts[-1]
                elif len(amounts) == 1:
                    debit = amounts[0]

                if state == 'old':
                    data.append({
                        'date': date_text,
                        'vch_type': vch_type,
                        'vch_no': vch_no,
                        'debit_old': debit,
                        'credit_old': credit,
                    })
                elif state == 'new':
                    data.append({
                        'date': date_text,
                        'vch_type': vch_type,
                        'vch_no': vch_no,
                        'debit_new': debit,
                        'credit_new': credit,
                    })
        start_extract = False  # Reset for next PDF if needed       


    return pd.DataFrame(data)


def compare_ledgers(df_new, df_old):
    """
    Compares two ledger DataFrames on date, voucher type, and voucher number.

    Args:
        df_new: DataFrame with 'new' suffixed columns
        df_old: DataFrame with 'old' suffixed columns

    Returns:
        Merged DataFrame with match indicators
    """
    # Handle empty DataFrames
    if df_new.empty and df_old.empty:
        return pd.DataFrame()

    # Check required columns exist
    required_new = ['date', 'vch_type', 'vch_no', 'debit_new', 'credit_new']
    required_old = ['date', 'vch_type', 'vch_no', 'debit_old', 'credit_old']

    if not all(col in df_new.columns for col in required_new):
        raise ValueError(f"df_new missing columns. Expected: {required_new}, Got: {list(df_new.columns)}")
    if not all(col in df_old.columns for col in required_old):
        raise ValueError(f"df_old missing columns. Expected: {required_old}, Got: {list(df_old.columns)}")

    comparison = pd.merge(
        df_new, df_old,
        on=['date', 'vch_type', 'vch_no'],
        how='outer'
    )

    comparison['dr_match'] = comparison['debit_new'] == comparison['debit_old']
    comparison['cr_match'] = comparison['credit_new'] == comparison['credit_old']
    comparison['Status'] = comparison.apply(
        lambda x: '✅ MATCH' if (x['dr_match'] and x['cr_match']) else '❌ MISMATCH',
        axis=1
    )

    return comparison

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Balance sheet comparison tool that extracts financial data from Excel and PDF files, then compares values by 3-digit code to identify discrepancies.

## Commands

```bash
# Activate virtual environment
source venv/Scripts/activate  # Unix
venv\Scripts\activate         # Windows

# Run the comparison
python app.py
```

## Architecture

**Single-file structure** (`app.py`):

1. **`to_decimal_exact()`** - Converts values to Decimal with exactly 2 decimal places using ROUND_HALF_UP. Critical for eliminating floating-point noise in financial data.

2. **`clean_code()`** - Standardizes account codes to 3-digit strings using regex.

3. **`extract_from_pdf()`** - Uses pdfplumber to scan PDF text line-by-line, looking for lines starting with 3-digit codes followed by currency amounts. Handles Indian number formatting (e.g., 1,23,456.00) and negative values in parentheses.

4. **`extract_from_excel()`** - Reads Excel files, auto-detects header row by searching for "Code No", then identifies columns by keywords ("Code", "Current Year", "Previous Year").

5. **`run_comparison()`** - Merges Excel and PDF data on Code, performs exact Decimal matching, and generates `Balance_Sheet_Match_Report.xlsx`.

## Dependencies

Core packages in `venv`:
- `pandas` - Data manipulation and merging
- `pdfplumber` - PDF text extraction
- `openpyxl` - Excel file I/O

## Data Flow

```
Excel (Code, Current, Previous) ─┐
                                 ├─> Merge on Code ─> Match/Mismatch ─> Report
PDF (scanned for 3-digit codes) ─┘
```

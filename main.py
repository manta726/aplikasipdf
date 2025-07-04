from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from typing import List, Optional
import pdfplumber
import pandas as pd
import re
import tempfile
import os
import shutil
import zipfile
from datetime import datetime
import io
import json
import traceback

app = FastAPI(
    title="PDF Document Extractor API",
    description="API untuk ekstraksi data dari dokumen PDF (SKTT, EVLN, ITAS, ITK, Notifikasi, DKPTKA)",
    version="3.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# ========================= HELPER FUNCTIONS =========================
def clean_text(text, is_name_or_pob=False):
    if text is None:
        return ""
    text = re.sub(r"Reference No|Payment Receipt No|Jenis Kelamin|Kewarganegaraan|Pekerjaan|Alamat", "", text)
    if is_name_or_pob:
        text = re.sub(r"\.", "", text)
    text = re.sub(r"[^A-Za-z0-9\s,./-]", "", text).strip()
    return " ".join(text.split())

def format_date(date_str):
    if not date_str:
        return ""
    match = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})", date_str)
    if match:
        day, month, year = match.groups()
        return f"{day}/{month}/{year}"
    return date_str

def split_birth_place_date(text):
    if text:
        parts = text.split(", ")
        if len(parts) == 2:
            return parts[0].strip(), format_date(parts[1])
    return text, None

def sanitize_filename_part(text):
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r'[^\w\s-]', '', text).strip()
    if len(text) > 30:
        text = text[:30].strip()
    return text

def generate_new_filename(extracted_data, use_name=True, use_passport=True):
    name_raw = (
        extracted_data.get("Name") or
        extracted_data.get("Nama TKA") or
        ""
    )
    passport_raw = (
        extracted_data.get("Passport Number") or
        extracted_data.get("Nomor Paspor") or
        extracted_data.get("Passport No") or
        extracted_data.get("KITAS/KITAP") or
        ""
    )
    
    name = sanitize_filename_part(name_raw) if use_name and name_raw else ""
    passport = sanitize_filename_part(passport_raw) if use_passport and passport_raw else ""
    
    parts = [p for p in [name, passport] if p]
    base_name = " ".join(parts) if parts else "RENAMED"
    
    return f"{base_name}.pdf"

def get_greeting():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning"
    elif 12 <= hour < 17:
        return "Good afternoon"
    else:
        return "Good evening"

# ========================= IMPROVED EXTRACTORS =========================

def extract_sktt(text):
    nik = re.search(r'NIK/Number of Population Identity\s*:\s*(\d+)', text)
    name = re.search(r'Nama/Name\s*:\s*([\w\s]+)', text)
    gender = re.search(r'Jenis Kelamin/Sex\s*:\s*(MALE|FEMALE)', text)
    birth_place_date = re.search(r'Tempat/Tgl Lahir\s*:\s*([\w\s,0-9-]+)', text)
    nationality = re.search(r'Kewarganegaraan/Nationality\s*:\s*([\w\s]+)', text)
    occupation = re.search(r'Pekerjaan/Occupation\s*:\s*([\w\s]+)', text)
    address = re.search(r'Alamat/Address\s*:\s*([\w\s,./-]+)', text)
    kitab_kitas = re.search(r'Nomor KITAP/KITAS Number\s*:\s*([\w-]+)', text)
    expiry_date = re.search(r'Berlaku Hingga s.d/Expired date\s*:\s*([\d-]+)', text)

    # Extract Date Issue - improved pattern
    lines = text.strip().splitlines()
    date_issue = None
    for i, line in enumerate(lines):
        if "KEPALA DINAS" in line.upper():
            if i > 0:
                match = re.search(r'([A-Z\s]+),\s*(\d{2}-\d{2}-\d{4})', lines[i-1])
                if match:
                    date_issue = match.group(2)
            break

    birth_place, birth_date = split_birth_place_date(birth_place_date.group(1)) if birth_place_date else (None, None)

    return {
        "NIK": nik.group(1) if nik else None,
        "Name": clean_text(name.group(1), is_name_or_pob=True) if name else None,
        "Jenis Kelamin": gender.group(1) if gender else None,
        "Place of Birth": clean_text(birth_place, is_name_or_pob=True) if birth_place else None,
        "Date of Birth": birth_date,
        "Nationality": clean_text(nationality.group(1)) if nationality else None,
        "Occupation": clean_text(occupation.group(1)) if occupation else None,
        "Address": clean_text(address.group(1)) if address else None,
        "KITAS/KITAP": clean_text(kitab_kitas.group(1)) if kitab_kitas else None,
        "Passport Expiry": format_date(expiry_date.group(1)) if expiry_date else None,
        "Date Issue": format_date(date_issue) if date_issue else None,
        "Jenis Dokumen": "SKTT"
    }

def extract_evln(text):
    data = {
        "Name": "",
        "Place of Birth": "",
        "Date of Birth": "",
        "Passport No": "",
        "Passport Expiry": "",
        "Date Issue": "",
        "Jenis Dokumen": "EVLN"
    }
    
    lines = text.split("\n")
    
    # Improved name extraction - look for "Dear Mr./Ms." pattern
    for i, line in enumerate(lines):
        if re.search(r"Dear\s+(Mr\.|Ms\.|Sir|Madam)?", line, re.IGNORECASE):
            if i + 1 < len(lines):
                name_candidate = lines[i + 1].strip()
                if 3 < len(name_candidate) < 50:
                    data["Name"] = clean_text(name_candidate, is_name_or_pob=True)
            break
    
    # Parse other fields
    for line in lines:
        if not data["Name"] and re.search(r"(?i)\bName\b|\bNama\b", line):
            parts = line.split(":")
            if len(parts) > 1:
                data["Name"] = clean_text(parts[1], is_name_or_pob=True)
        
        elif re.search(r"(?i)\bPlace of Birth\b|\bTempat Lahir\b", line):
            parts = line.split(":")
            if len(parts) > 1:
                pob_text = parts[1].strip()
                pob_cleaned = re.sub(r'\s*Visa\s*Type\s*.*', '', pob_text)
                data["Place of Birth"] = clean_text(pob_cleaned, is_name_or_pob=True)
        
        elif re.search(r"(?i)\bDate of Birth\b|\bTanggal Lahir\b", line):
            match = re.search(r"(\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})", line)
            if match:
                data["Date of Birth"] = format_date(match.group(1))
        
        elif re.search(r"(?i)\bPassport No\b", line):
            match = re.search(r"\b([A-Z0-9]+)\b", line)
            if match:
                data["Passport No"] = match.group(1)
        
        elif re.search(r"(?i)\bPassport Expiry\b", line):
            match = re.search(r"(\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})", line)
            if match:
                data["Passport Expiry"] = format_date(match.group(1))
    
    # Extract Date Issue with improved patterns
    if not data["Date Issue"]:
        issue_patterns = [
            r"(?i)(?:Date\s+of\s+Issue|Issue\s+Date|Issued\s+on|Tanggal\s+Penerbitan)\s*:?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
            r"(?i)(?:Issued|Diterbitkan)\s*:?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})"
        ]
        
        for pattern in issue_patterns:
            match = re.search(pattern, text)
            if match:
                data["Date Issue"] = format_date(match.group(1))
                break
    
    return data

def extract_itas(text):
    data = {}
    
    name_match = re.search(r"([A-Z\s]+)\nPERMIT NUMBER", text)
    data["Name"] = name_match.group(1).strip() if name_match else None
    
    permit_match = re.search(r"PERMIT NUMBER\s*:\s*([A-Z0-9-]+)", text)
    data["Permit Number"] = permit_match.group(1) if permit_match else None
    
    expiry_match = re.search(r"STAY PERMIT EXPIRY\s*:\s*([\d/]+)", text)
    data["Stay Permit Expiry"] = format_date(expiry_match.group(1)) if expiry_match else None
    
    place_date_birth_match = re.search(r"Place / Date of Birth\s*.*:\s*([A-Za-z\s]+)\s*/\s*([\d-]+)", text)
    if place_date_birth_match:
        place = place_date_birth_match.group(1).strip()
        date = place_date_birth_match.group(2).strip()
        data["Place & Date of Birth"] = f"{place}, {format_date(date)}"
    else:
        data["Place & Date of Birth"] = None
    
    passport_match = re.search(r"Passport Number\s*: ([A-Z0-9]+)", text)
    data["Passport Number"] = passport_match.group(1) if passport_match else None
    
    passport_expiry_match = re.search(r"Passport Expiry\s*: ([\d-]+)", text)
    data["Passport Expiry"] = format_date(passport_expiry_match.group(1)) if passport_expiry_match else None
    
    nationality_match = re.search(r"Nationality\s*: ([A-Z]+)", text)
    data["Nationality"] = nationality_match.group(1) if nationality_match else None
    
    gender_match = re.search(r"Gender\s*: ([A-Z]+)", text)
    data["Gender"] = gender_match.group(1) if gender_match else None
    
    address_match = re.search(r"Address\s*:\s*(.+)", text)
    data["Address"] = address_match.group(1).strip() if address_match else None
    
    occupation_match = re.search(r"Occupation\s*:\s*(.+)", text)
    data["Occupation"] = occupation_match.group(1).strip() if occupation_match else None
    
    guarantor_match = re.search(r"Guarantor\s*:\s*(.+)", text)
    data["Guarantor"] = guarantor_match.group(1).strip() if guarantor_match else None
    
    # Improved Date Issue extraction with month name conversion
    date_issue_match = re.search(r"([A-Za-z]+),\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
    if date_issue_match:
        day = date_issue_match.group(2)
        month = date_issue_match.group(3)
        year = date_issue_match.group(4)
        
        month_dict = {
            'January': '01', 'February': '02', 'March': '03', 'April': '04',
            'May': '05', 'June': '06', 'July': '07', 'August': '08',
            'September': '09', 'October': '10', 'November': '11', 'December': '12'
        }
        month_num = month_dict.get(month, month)
        date_str = f"{day.zfill(2)}/{month_num}/{year}"
        data["Date Issue"] = format_date(date_str)
    else:
        fallback_date_match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
        if fallback_date_match:
            data["Date Issue"] = format_date(fallback_date_match.group(0))
        else:
            data["Date Issue"] = None
    
    data["Jenis Dokumen"] = "ITAS"
    return data

def extract_itk(text):
    # Similar to ITAS but with ITK document type
    data = extract_itas(text)  # Reuse ITAS logic
    data["Jenis Dokumen"] = "ITK"
    return data

def extract_notifikasi(text):
    data = {
        "Nomor Keputusan": "",
        "Nama TKA": "",
        "Tempat/Tanggal Lahir": "",
        "Kewarganegaraan": "",
        "Alamat Tempat Tinggal": "",
        "Nomor Paspor": "",
        "Jabatan": "",
        "Lokasi Kerja": "",
        "Berlaku": "",
        "Date Issue": ""
    }
    
    def find(pattern):
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else ""
    
    nomor_keputusan_match = re.search(r"NOMOR\s+([A-Z0-9./-]+)", text, re.IGNORECASE)
    data["Nomor Keputusan"] = nomor_keputusan_match.group(1).strip() if nomor_keputusan_match else ""
    
    data["Nama TKA"] = find(r"Nama TKA\s*:\s*(.*)")
    data["Tempat/Tanggal Lahir"] = find(r"Tempat/Tanggal Lahir\s*:\s*(.*)")
    data["Kewarganegaraan"] = find(r"Kewarganegaraan\s*:\s*(.*)")
    data["Alamat Tempat Tinggal"] = find(r"Alamat Tempat Tinggal\s*:\s*(.*)")
    data["Nomor Paspor"] = find(r"Nomor Paspor\s*:\s*(.*)")
    data["Jabatan"] = find(r"Jabatan\s*:\s*(.*)")
    data["Lokasi Kerja"] = find(r"Lokasi Kerja\s*:\s*(.*)")
    
    # Extract validity period
    valid_match = re.search(
        r"Berlaku\s*:?\s*(\d{2}[-/]\d{2}[-/]\d{4})\s*(?:s\.?d\.?|sampai dengan)?\s*(\d{2}[-/]\d{2}[-/]\d{4})",
        text, re.IGNORECASE)
    if not valid_match:
        valid_match = re.search(
            r"Tanggal Berlaku\s*:?\s*(\d{2}[-/]\d{2}[-/]\d{4})\s*s\.?d\.?\s*(\d{2}[-/]\d{2}[-/]\d{4})",
            text, re.IGNORECASE)
    if valid_match:
        start_date = format_date(valid_match.group(1))
        end_date = format_date(valid_match.group(2))
        data["Berlaku"] = f"{start_date} - {end_date}"
    
    # Extract Date Issue with Indonesian month names
    date_issue_match = re.search(
        r"Pada tanggal\s*:\s*(\d{1,2})\s+(Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember)\s+(\d{4})",
        text, re.IGNORECASE)
    
    if date_issue_match:
        day = date_issue_match.group(1).zfill(2)
        month_name = date_issue_match.group(2)
        year = date_issue_match.group(3)
        
        month_dict = {
            'januari': '01', 'februari': '02', 'maret': '03', 'april': '04',
            'mei': '05', 'juni': '06', 'juli': '07', 'agustus': '08',
            'september': '09', 'oktober': '10', 'november': '11', 'desember': '12'
        }
        month_num = month_dict.get(month_name.lower(), '01')
        data["Date Issue"] = f"{day}/{month_num}/{year}"
    
    data["Jenis Dokumen"] = "NOTIFIKASI"
    return data

def extract_dkptka(text):
    data = {
        "Nomor Keputusan": "",
        "Nama TKA": "",
        "Tempat/Tanggal Lahir": "",
        "Kewarganegaraan": "",
        "Alamat Tempat Tinggal": "",
        "Nomor Paspor": "",
        "Jabatan": "",
        "Lokasi Kerja": "",
        "Berlaku": "",
        "Date Issue": ""
    }
    
    def find(pattern):
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else ""
    
    nomor_keputusan_match = re.search(r"NOMOR\s+([A-Z0-9./-]+)", text, re.IGNORECASE)
    data["Nomor Keputusan"] = nomor_keputusan_match.group(1).strip() if nomor_keputusan_match else ""
    
    data["Nama TKA"] = find(r"Nama TKA\s*:\s*(.*)")
    data["Tempat/Tanggal Lahir"] = find(r"Tempat/Tanggal Lahir\s*:\s*(.*)")
    data["Kewarganegaraan"] = find(r"Kewarganegaraan\s*:\s*(.*)")
    data["Alamat Tempat Tinggal"] = find(r"Alamat Tempat Tinggal\s*:\s*(.*)")
    data["Nomor Paspor"] = find(r"Nomor Paspor\s*:\s*(.*)")
    data["Jabatan"] = find(r"Jabatan\s*:\s*(.*)")
    data["Lokasi Kerja"] = find(r"Lokasi Kerja\s*:\s*(.*)")
    
    # Extract validity period
    valid_match = re.search(
        r"Berlaku\s*:?\s*(\d{2}[-/]\d{2}[-/]\d{4})\s*(?:s\.?d\.?|sampai dengan)?\s*(\d{2}[-/]\d{2}[-/]\d{4})",
        text, re.IGNORECASE)
    if not valid_match:
        valid_match = re.search(
            r"Tanggal Berlaku\s*:?\s*(\d{2}[-/]\d{2}[-/]\d{4})\s*s\.?d\.?\s*(\d{2}[-/]\d{2}[-/]\d{4})",
            text, re.IGNORECASE)
    if valid_match:
        start_date = format_date(valid_match.group(1))
        end_date = format_date(valid_match.group(2))
        data["Berlaku"] = f"{start_date} - {end_date}"
    
    # Extract Date Issue with Indonesian month names
    date_issue_match = re.search(
        r"Pada tanggal\s*:\s*(\d{1,2})\s+(Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember)\s+(\d{4})",
        text, re.IGNORECASE)
    
    if date_issue_match:
        day = date_issue_match.group(1).zfill(2)
        month_name = date_issue_match.group(2)
        year = date_issue_match.group(3)
        
        month_dict = {
            'januari': '01', 'februari': '02', 'maret': '03', 'april': '04',
            'mei': '05', 'juni': '06', 'juli': '07', 'agustus': '08',
            'september': '09', 'oktober': '10', 'november': '11', 'desember': '12'
        }
        month_num = month_dict.get(month_name.lower(), '01')
        data["Date Issue"] = f"{day}/{month_num}/{year}"
    
    data["Jenis Dokumen"] = "DKPTKA"
    return data

# ========================= DOCUMENT TYPE DETECTION =========================

def detect_document_type(text):
    # Detection patterns for different document types
    if re.search(r"SURAT KETERANGAN TENAGA KERJA TERDAFTAR", text, re.IGNORECASE):
        return "SKTT"
    elif re.search(r"ENTRY VISA|VISA ENTRY", text, re.IGNORECASE):
        return "EVLN"
    elif re.search(r"STAY PERMIT|PERMIT TO STAY|IZIN TINGGAL", text, re.IGNORECASE):
        return "ITAS"
    elif re.search(r"IZIN TINGGAL KUNJUNGAN|VISIT PERMIT", text, re.IGNORECASE):
        return "ITK"
    elif re.search(r"NOTIFIKASI", text, re.IGNORECASE):
        return "NOTIFIKASI"
    elif re.search(r"DKPTKA", text, re.IGNORECASE):
        return "DKPTKA"
    else:
        return "UNKNOWN"

def extract_data_by_type(text, doc_type):
    """Extract data based on document type"""
    if doc_type == "SKTT":
        return extract_sktt(text)
    elif doc_type == "EVLN":
        return extract_evln(text)
    elif doc_type == "ITAS":
        return extract_itas(text)
    elif doc_type == "ITK":
        return extract_itk(text)
    elif doc_type == "NOTIFIKASI":
        return extract_notifikasi(text)
    elif doc_type == "DKPTKA":
        return extract_dkptka(text)
    else:
        return {"error": f"Unknown document type: {doc_type}"}

# ========================= API ENDPOINTS =========================

@app.get("/")
async def root():
    return {
        "message": f"{get_greeting()}! Welcome to PDF Document Extractor API",
        "version": "3.0.0",
        "supported_documents": ["SKTT", "EVLN", "ITAS", "ITK", "NOTIFIKASI", "DKPTKA"],
        "description": "API untuk ekstraksi data dari dokumen PDF dan export ke Excel"
    }

@app.post("/extract")
async def extract_single_document(
    file: UploadFile = File(...),
    document_type: str = Form(default="auto")
):
    """Extract data from a single PDF document"""
    try:
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="File must be a PDF")
        
        # Read PDF content
        content = await file.read()
        
        # Extract text from PDF
        with io.BytesIO(content) as pdf_file:
            with pdfplumber.open(pdf_file) as pdf:
                text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        
        if not text.strip():
            raise HTTPException(status_code=400, detail="No text found in PDF")
        
        # Detect document type if auto
        if document_type.lower() == "auto":
            document_type = detect_document_type(text)
        
        # Extract data
        extracted_data = extract_data_by_type(text, document_type.upper())
        
        return {
            "status": "success",
            "filename": file.filename,
            "document_type": document_type.upper(),
            "extracted_data": extracted_data
        }
        
    except Exception as e:
        return {
            "status": "error",
            "filename": file.filename,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.post("/extract-bulk")
async def extract_bulk_documents(
    files: List[UploadFile] = File(...),
    document_type: str = Form(default="auto"),
    export_format: str = Form(default="excel")
):
    """Extract data from multiple PDF documents and export to Excel"""
    try:
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")
        
        all_results = []
        
        for file in files:
            try:
                # Validate file type
                if not file.filename.lower().endswith('.pdf'):
                    all_results.append({
                        "filename": file.filename,
                        "status": "error",
                        "error": "File must be a PDF"
                    })
                    continue
                
                # Read PDF content
                content = await file.read()
                
                # Extract text from PDF
                with io.BytesIO(content) as pdf_file:
                    with pdfplumber.open(pdf_file) as pdf:
                        text = ""
                        for page in pdf.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text += page_text + "\n"
                
                if not text.strip():
                    all_results.append({
                        "filename": file.filename,
                        "status": "error",
                        "error": "No text found in PDF"
                    })
                    continue
                
                # Detect document type if auto
                current_doc_type = document_type
                if document_type.lower() == "auto":
                    current_doc_type = detect_document_type(text)
                
                # Extract data
                extracted_data = extract_data_by_type(text, current_doc_type.upper())
                
                # Add filename to extracted data
                extracted_data["Original_Filename"] = file.filename
                
                all_results.append({
                    "filename": file.filename,
                    "status": "success",
                    "document_type": current_doc_type.upper(),
                    "extracted_data": extracted_data
                })
                
            except Exception as e:
                all_results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": str(e)
                })
        
        # Create Excel file with results
        successful_extractions = [r for r in all_results if r["status"] == "success"]
        
        if not successful_extractions:
            raise HTTPException(status_code=400, detail="No successful extractions found")
        
        # Prepare data for Excel
        excel_data = []
        for result in successful_extractions:
            excel_data.append(result["extracted_data"])
        
        # Create DataFrame and save to Excel
        df = pd.DataFrame(excel_data)
        
        # Create temporary Excel file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
            df.to_excel(tmp_file.name, index=False, engine='openpyxl')
            excel_path = tmp_file.name
        
        # Generate filename for download
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_filename = f"extracted_data_{timestamp}.xlsx"
        
        return FileResponse(
            excel_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=download_filename,
            headers={"Content-Disposition": f"attachment; filename={download_filename}"}
        )
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.post("/extract-and-rename")
async def extract_and_rename_documents(
    files: List[UploadFile] = File(...),
    document_type: str = Form(default="auto"),
    use_name: bool = Form(default=True),
    use_passport: bool = Form(default=True)
):
    """Extract data from PDFs and return renamed files with extracted data in Excel"""
    try:
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")
        
        # Create temporary directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            extracted_data_list = []
            renamed_files = []
            
            for file in files:
                try:
                    # Validate file type
                    if not file.filename.lower().endswith('.pdf'):
                        continue
                    
                    # Read PDF content
                    content = await file.read()
                    
                    # Extract text from PDF
                    with io.BytesIO(content) as pdf_file:
                        with pdfplumber.open(pdf_file) as pdf:
                            text = ""
                            for page in pdf.pages:
                                page_text = page.extract_text()
                                if page_text:
                                    text += page_text + "\n"
                    
                    if not text.strip():
                        continue
                    
                    # Detect document type if auto
                    current_doc_type = document_type
                    if document_type.lower() == "auto":
                        current_doc_type = detect_document_type(text)
                    
                    # Extract data
                    extracted_data = extract_data_by_type(text, current_doc_type.upper())
                    
                    # Generate new filename
                    new_filename = generate_new_filename(
                        extracted_data, 
                        use_name=use_name, 
                        use_passport=use_passport
                    )
                    
                    # Save renamed PDF
                    renamed_path = os.path.join(temp_dir, new_filename)
                    with open(renamed_path, 'wb') as f:
                        f.write(content)
                    
                    # Add to extracted data list
                    extracted_data["Original_Filename"] = file.filename
                    extracted_data["New_Filename"] = new_filename
                    extracted_data_list.append(extracted_data)
                    renamed_files.append(renamed_path)
                    
                except Exception as e:
                    continue
            
            if not extracted_data_list:
                raise HTTPException(status_code=400, detail="No files could be processed")
            
            # Create Excel file with extracted data
            df = pd.DataFrame(extracted_data_list)
            excel_path = os.path.join(temp_dir, "extracted_data.xlsx")
            df.to_excel(excel_path, index=False, engine='openpyxl')
            
            # Create ZIP file with renamed PDFs and Excel data
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"renamed_documents_{timestamp}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add renamed PDFs
                for file_path in renamed_files:
                    zipf.write(file_path, os.path.basename(file_path))
                
                # Add Excel file
                zipf.write(excel_path, "extracted_data.xlsx")
            
            # Return ZIP file
            return FileResponse(
                zip_path,
                media_type="application/zip",
                filename=zip_filename,
                headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
            )
            
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "3.0.0"
    }

@app.get("/document-types")
async def get_document_types():
    return {
        "supported_types": [
            {
                "code": "SKTT",
                "name": "Surat Keterangan Tinggal Terbatas",
                "description": "Indonesian temporary residence permit"
            },
            {
                "code": "EVLN",
                "name": "Exit Visa Luar Negeri",
                "description": "Exit visa for foreign nationals"
            },
            {
                "code": "ITAS",
                "name": "Izin Tinggal Terbatas",
                "description": "Limited stay permit"
            },
            {
                "code": "ITK",
                "name": "Izin Tinggal Kunjungan",
                "description": "Visit stay permit"
            },
            {
                "code": "Notifikasi",
                "name": "Notifikasi TKA",
                "description": "Foreign worker notification"
            },
            {
                "code": "DKPTKA",
                "name": "Dana Kompensasi Penggunaan TKA",
                "description": "Foreign worker compensation fund"
            }
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)

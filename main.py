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
        
        month_map = {
            'januari': '01', 'februari': '02', 'maret': '03', 'april': '04',
            'mei': '05', 'juni': '06', 'juli': '07', 'agustus': '08',
            'september': '09', 'oktober': '10', 'november': '11', 'desember': '12'
        }
        month = month_map.get(month_name.lower(), '01')
        data["Date Issue"] = f"{day}/{month}/{year}"
    else:
        date_issue_match = re.search(
            r"Pada tanggal\s*:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
            text, re.IGNORECASE)
        if date_issue_match:
            data["Date Issue"] = format_date(date_issue_match.group(1))
    
    data["Jenis Dokumen"] = "Notifikasi"
    return data

def extract_dkptka(text):
    """Extract DKPTKA document data"""
    def safe_extract(pattern, text, group=1, flags=re.IGNORECASE):
        try:
            match = re.search(pattern, text, flags)
            if match:
                result = match.group(group).strip()
                result = re.sub(r'\s+', ' ', result)
                return result if result else None
            return None
        except Exception:
            return None

    def clean_extracted_text(text):
        if not text:
            return None
        cleaned = re.sub(r'\s+', ' ', text.strip())
        cleaned = re.sub(r'["\'\n\r\t]+', ' ', cleaned).strip()
        return cleaned if cleaned else None

    result = {}

    # Extract company name
    company_patterns = [
        r'Nama\s+Pemberi\s+Kerja\s*:\s*([^\n]+)',
        r'([A-Z][A-Z\s]*PT\.?[A-Z\s]*)\s*(?=\n.*Alamat)',
    ]
    
    company_name = None
    for pattern in company_patterns:
        company_name = safe_extract(pattern, text)
        if company_name:
            company_name = clean_extracted_text(company_name)
            break
    
    result["Nama Pemberi Kerja"] = company_name

    # Extract address
    address_patterns = [
        r'Alamat\s*:\s*(.*?)(?=\n\s*\d+\.\s*Nomor\s+Telepon|\n\s*3\.|$)',
        r'Alamat\s*:\s*(.*?)(?=Nomor\s+Telepon|Email|$)',
    ]
    
    address = None
    for pattern in address_patterns:
        address_match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if address_match:
            address_text = address_match.group(1)
            address = re.sub(r'\n\s*', ' ', address_text.strip())
            address = re.sub(r'\s+', ' ', address)
            break
    
    result["Alamat"] = clean_extracted_text(address)

    # Extract other fields
    result["No Telepon"] = safe_extract(r'Nomor\s+Telepon\s*:\s*([0-9\-\+$$$$\s]+)', text)
    result["Email"] = safe_extract(r'Email\s*:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', text)
    result["Nama TKA"] = clean_extracted_text(safe_extract(r'Nama\s+TKA\s*:\s*([^\n]+)', text))
    result["Tempat/Tanggal Lahir"] = clean_extracted_text(safe_extract(r'Tempat.*?Lahir\s*:\s*([^\n]+)', text))
    result["Nomor Paspor"] = safe_extract(r'Nomor\s+Paspor\s*:\s*([A-Z0-9]+)', text)
    result["Kewarganegaraan"] = clean_extracted_text(safe_extract(r'Kewarganegaraan\s*:\s*([^\n]+)', text))
    result["Jabatan"] = clean_extracted_text(safe_extract(r'Jabatan\s*:\s*([^\n]+)', text))
    result["Kanim"] = clean_extracted_text(safe_extract(r'Kanim.*?:\s*([^\n]+)', text))
    result["Lokasi Kerja"] = clean_extracted_text(safe_extract(r'Lokasi\s+Kerja\s*:\s*([^\n]+)', text))
    
    # Extract billing code
    billing_code = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if 'Kode Billing Pembayaran' in line:
            next_lines = lines[i+1:i+4]
            joined = " ".join(next_lines)
            match = re.search(r'(\d{12,})', joined)
            if match:
                billing_code = match.group(1).strip()
                break
    
    result["Kode Billing Pembayaran"] = billing_code
    result["DKPTKA"] = clean_extracted_text(safe_extract(r'DKPTKA.*?:\s*(US\$[^\n]+)', text))
    result["Jenis Dokumen"] = "DKPTKA"

    # Filter out None values
    filtered_result = {}
    for key, value in result.items():
        if value and str(value).strip():
            filtered_result[key] = value
        else:
            filtered_result[key] = None

    return filtered_result

# ========================= API ENDPOINTS =========================

@app.get("/")
async def root():
    return {
        "message": f"{get_greeting()}, PDF Document Extractor API is running",
        "timestamp": datetime.now().isoformat(),
        "supported_documents": ["SKTT", "EVLN", "ITAS", "ITK", "Notifikasi", "DKPTKA"],
        "endpoints": {
            "extract": "/extract - POST multiple PDF files with document type",
            "extract_batch": "/extract-batch - POST for batch processing with Excel export",
            "extract_with_rename": "/extract-with-rename - POST with file renaming feature",
            "docs": "/docs - API documentation"
        }
    }

@app.options("/extract")
async def options_extract():
    return JSONResponse(content={})

@app.post("/extract")
async def extract_documents(
    files: List[UploadFile] = File(...),
    document_type: Optional[str] = Form(None)
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if not document_type:
        document_type = "SKTT"
    
    if document_type not in ["SKTT", "EVLN", "ITAS", "ITK", "Notifikasi", "DKPTKA"]:
        raise HTTPException(status_code=400, detail="Invalid document type")
    
    results = []
    
    for file in files:
        if not file.filename.lower().endswith('.pdf'):
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": "File is not a PDF",
                "data": None
            })
            continue
        
        try:
            await file.seek(0)
            content = await file.read()
            
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                texts = [page.extract_text() for page in pdf.pages if page.extract_text()]
                full_text = "\n".join(texts)
            
            # Use improved extractors
            if document_type == "SKTT":
                extracted_data = extract_sktt(full_text)
            elif document_type == "EVLN":
                extracted_data = extract_evln(full_text)
            elif document_type == "ITAS":
                extracted_data = extract_itas(full_text)
            elif document_type == "ITK":
                extracted_data = extract_itk(full_text)
            elif document_type == "Notifikasi":
                extracted_data = extract_notifikasi(full_text)
            elif document_type == "DKPTKA":
                extracted_data = extract_dkptka(full_text)
            else:
                extracted_data = {}
            
            results.append({
                "filename": file.filename,
                "status": "success",
                "data": extracted_data,
                "document_type": document_type
            })
            
        except Exception as e:
            error_details = traceback.format_exc()
            print(f"Error processing {file.filename}: {str(e)}\n{error_details}")
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(e),
                "data": None
            })
    
    response_data = {
        "success": True,
        "timestamp": datetime.now().isoformat(),
        "document_type": document_type,
        "total_files": len(files),
        "processed_files": len([r for r in results if r["status"] == "success"]),
        "failed_files": len([r for r in results if r["status"] == "error"]),
        "results": results
    }
    
    return JSONResponse(
        content=response_data,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        }
    )

@app.post("/extract-with-rename")
async def extract_with_rename(
    files: List[UploadFile] = File(...),
    document_type: str = Form(...),
    use_name_for_rename: bool = Form(True),
    use_passport_for_rename: bool = Form(True)
):
    """Extract data and provide renamed files with ZIP download"""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if document_type not in ["SKTT", "EVLN", "ITAS", "ITK", "Notifikasi", "DKPTKA"]:
        raise HTTPException(status_code=400, detail="Invalid document type")
    
    all_data = []
    renamed_files = {}
    temp_dir = tempfile.mkdtemp()
    
    try:
        for file in files:
            if not file.filename.lower().endswith('.pdf'):
                continue
            
            content = await file.read()
            
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                texts = [page.extract_text() for page in pdf.pages if page.extract_text()]
                full_text = "\n".join(texts)
            
            # Extract data
            if document_type == "SKTT":
                extracted_data = extract_sktt(full_text)
            elif document_type == "EVLN":
                extracted_data = extract_evln(full_text)
            elif document_type == "ITAS":
                extracted_data = extract_itas(full_text)
            elif document_type == "ITK":
                extracted_data = extract_itk(full_text)
            elif document_type == "Notifikasi":
                extracted_data = extract_notifikasi(full_text)
            elif document_type == "DKPTKA":
                extracted_data = extract_dkptka(full_text)
            else:
                extracted_data = {}
            
            all_data.append(extracted_data)
            
            # Generate new filename
            new_filename = generate_new_filename(
                extracted_data, 
                use_name_for_rename, 
                use_passport_for_rename
            )
            
            # Save renamed file
            temp_file_path = os.path.join(temp_dir, new_filename)
            with open(temp_file_path, 'wb') as f:
                f.write(content)
            
            renamed_files[file.filename] = {
                'new_name': new_filename, 
                'path': temp_file_path
            }
        
        # Create Excel file
        df = pd.DataFrame(all_data)
        excel_path = os.path.join(temp_dir, f"Hasil_Ekstraksi_{document_type}.xlsx")
        df.to_excel(excel_path, index=False)
        
        # Create ZIP file with renamed PDFs
        zip_path = os.path.join(temp_dir, "Renamed_Files.zip")
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file_info in renamed_files.values():
                zipf.write(file_info['path'], arcname=file_info['new_name'])
        
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "document_type": document_type,
            "total_files": len(files),
            "processed_files": len(all_data),
            "extraction_data": all_data,
            "renamed_files": {k: v['new_name'] for k, v in renamed_files.items()},
            "download_links": {
                "excel": f"/download-excel/{os.path.basename(excel_path)}",
                "zip": f"/download-zip/{os.path.basename(zip_path)}"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing files: {str(e)}")
    finally:
        # Cleanup will be handled by the download endpoints
        pass

@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "service": "PDF Document Extractor API"
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

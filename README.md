# PDF Text Extractor - Full Stack Application

Aplikasi lengkap untuk ekstraksi teks dari multiple PDF files dengan arsitektur terpisah:

## 🎯 Backend (FastAPI - HuggingFace Space)

### Struktur Backend:
- `backend/main.py` - API endpoint untuk ekstraksi PDF
- `backend/requirements.txt` - Dependencies Python
- `backend/Dockerfile` - Konfigurasi Docker untuk HF Space

### Deployment ke HuggingFace Space:

1. **Buat Space Baru:**
   - Pergi ke https://huggingface.co/spaces
   - Klik "Create new Space"
   - Pilih SDK: "Docker"
   - Beri nama space (contoh: `pdf-extractor-api`)

2. **Upload Files:**
   \`\`\`bash
   # Clone repository atau copy files ke folder backend/
   # Upload ke HuggingFace Space:
   # - main.py
   # - requirements.txt  
   # - Dockerfile
   \`\`\`

3. **URL API akan tersedia di:**
   \`\`\`
   https://username-pdf-extractor-api.hf.space
   \`\`\`

## 🎨 Frontend (Next.js - Vercel)

### Fitur Frontend:
- Upload multiple PDF files
- Real-time extraction progress
- Display hasil ekstraksi
- Copy text to clipboard
- Download hasil sebagai TXT atau JSON
- Responsive design dengan Tailwind CSS

### Deployment ke Vercel:

1. **Push ke GitHub:**
   \`\`\`bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/username/pdf-extractor-frontend.git
   git push -u origin main
   \`\`\`

2. **Deploy di Vercel:**
   - Pergi ke https://vercel.com
   - Import project dari GitHub
   - Set environment variable:
     \`\`\`
     NEXT_PUBLIC_API_URL=https://username-pdf-extractor-api.hf.space
     \`\`\`
   - Deploy

## 🚀 Local Development

### Backend (FastAPI):
\`\`\`bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 7860
\`\`\`

### Frontend (Next.js):
\`\`\`bash
npm install
npm run dev
\`\`\`

## 📝 API Endpoints

- `GET /` - Health check dan info API
- `POST /extract` - Upload multiple PDF files
- `GET /docs` - Dokumentasi API interaktif
- `GET /health` - Health check

## 🔧 Environment Variables

### Frontend (.env.local):
\`\`\`
NEXT_PUBLIC_API_URL=https://your-hf-space.hf.space
\`\`\`

## 📦 Tech Stack

**Backend:**
- FastAPI
- PyPDF2
- Uvicorn
- Docker

**Frontend:**
- Next.js 14
- React
- Tailwind CSS
- shadcn/ui
- Lucide React Icons

## 🎯 Features

- ✅ Multiple PDF file upload
- ✅ Real-time extraction progress
- ✅ Error handling dan validation
- ✅ Copy text to clipboard
- ✅ Download results (TXT/JSON)
- ✅ Responsive design
- ✅ Modern UI dengan shadcn/ui
- ✅ CORS support
- ✅ Health check endpoints

# Backend

FastAPI backend for the ASI Hackathon project.

## Requirements

- Python 3.8+

## Setup

### 1. Create a virtual environment

**Mac / Linux**
```bash
python3 -m venv venv
```

**Windows**
```powershell
python -m venv venv
```

### 2. Activate the virtual environment

**Mac / Linux**
```bash
source venv/bin/activate
```

**Windows**
```powershell
.\venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

## Running the dev server

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`.  
Interactive docs (Swagger UI) are at `http://localhost:8000/docs`.

## Deactivating the virtual environment

```bash
deactivate
```

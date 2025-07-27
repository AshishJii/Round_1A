# Use a lightweight Python base on AMD64
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy the PDF processor script
COPY extract_outline_batch.py ./

# Install dependencies
RUN pip install --no-cache-dir PyMuPDF

# Default command: process PDFs in /app/input → /app/output
CMD ["python3", "extract_outline_batch.py"]

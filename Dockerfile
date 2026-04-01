FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY personal_auth.py main.py ./

# Create OAuth state directory
RUN mkdir -p .oauth-state

ENV PORT=8080
EXPOSE 8080

CMD ["python", "main.py"]

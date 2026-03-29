FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download PersonalAuthProvider
RUN pip install --no-cache-dir httpx && \
    python -c "import httpx; r = httpx.get('https://raw.githubusercontent.com/crumrine/fastmcp-personal-auth/main/personal_auth.py'); open('personal_auth.py','w').write(r.text); print('✅ personal_auth.py downloaded')"

# Copy application code
COPY main.py .

# Create OAuth state directory
RUN mkdir -p .oauth-state

EXPOSE 8000

CMD ["python", "main.py"]

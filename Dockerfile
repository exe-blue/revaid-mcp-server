FROM python:3.12-slim

WORKDIR /app

# Install curl for downloading personal_auth.py
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download PersonalAuthProvider (OAuth 2.1 for claude.ai)
RUN curl -fsSL -o personal_auth.py \
    "https://raw.githubusercontent.com/crumrine/fastmcp-personal-auth/main/personal_auth.py" \
    && python -c "from personal_auth import PersonalAuthProvider; print('✅ PersonalAuthProvider loaded')"

# Copy application code
COPY main.py .

# Create OAuth state directory
RUN mkdir -p .oauth-state

# Many K8s / PaaS readiness probes default to port 8080; override with -e PORT=... if needed
ENV PORT=8080
EXPOSE 8080

CMD ["python", "main.py"]

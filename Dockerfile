FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cache-bust: 2026-05-07
ARG CACHEBUST=1
COPY . .

# Inject SEO meta tags into Streamlit's index.html
RUN STREAMLIT_INDEX=$(python -c "import streamlit, os; print(os.path.join(os.path.dirname(streamlit.__file__), 'static', 'index.html'))") && \
    sed -i 's|<title>Streamlit</title>|<title>AccessCheck AI - WCAG 2.2 Accessibility Scanner</title>\n    <meta name="description" content="AI-powered WCAG 2.2 scanner that generates copy-paste ready code fixes automatically. Free plan includes 3 scans/month. No credit card required.">\n    <meta property="og:title" content="AccessCheck AI - WCAG 2.2 Accessibility Scanner">\n    <meta property="og:description" content="AI-powered WCAG 2.2 scanner with auto-generated code fixes. Scan any website for WCAG 2.2 violations instantly.">\n    <meta property="og:url" content="https://access.trytimeback.com">\n    <meta property="og:type" content="website">\n    <meta name="twitter:card" content="summary_large_image">\n    <meta name="twitter:title" content="AccessCheck AI - WCAG 2.2 Accessibility Scanner">\n    <meta name="twitter:description" content="AI-powered WCAG 2.2 scanner with copy-paste ready code fixes.">|' "$STREAMLIT_INDEX"

# Inject WCAG 2.4.1 landmark + skip link
RUN python patch_a11y.py

EXPOSE 8080

CMD streamlit run app.py \
    --server.port=${PORT:-8080} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false

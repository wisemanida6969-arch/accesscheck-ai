FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Force cache invalidation by injecting build version into env layer
ENV BUILD_VERSION=2026-05-20-landing-v3
RUN echo "Building version $BUILD_VERSION"

# Copy individual files / dirs so a single-file change creates a unique layer
COPY app.py ./app.py
COPY landing.html ./landing.html
COPY patch_a11y.py ./patch_a11y.py
COPY static ./static
COPY .streamlit ./.streamlit

# Verify critical files are present (build fails loudly if missing)
RUN test -f /app/landing.html && head -3 /app/landing.html
RUN grep -q "render_landing" /app/app.py && echo "app.py has render_landing - OK"

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

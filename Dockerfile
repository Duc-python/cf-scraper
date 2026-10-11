FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    xvfb \
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m invisible_playwright fetch

COPY . .

EXPOSE 3000

CMD ["xvfb-run", "-a", "python", "-m", "cf_scraper"]

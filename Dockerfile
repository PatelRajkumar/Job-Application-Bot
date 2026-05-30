FROM python:3.11-slim

# Install Node.js 22 and system Chromium
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs chromium --no-install-recommends \
        fonts-liberation \
        fonts-noto-core \
        fonts-freefont-ttf \
        fonts-dejavu-core \
        fontconfig && \
    fc-cache -fv && \
    rm -rf /var/lib/apt/lists/*

# Tell Puppeteer to skip downloading Chrome and use system Chromium instead
ENV PUPPETEER_SKIP_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY package.json .
RUN npm install

COPY . .

CMD ["python", "bot/bot.py"]

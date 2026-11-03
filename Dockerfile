FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/steelflow
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY web ./web
COPY start_public_demo.sh ./start_public_demo.sh
EXPOSE 10000
CMD ["bash", "start_public_demo.sh"]

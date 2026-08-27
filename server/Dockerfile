FROM python:3.12-alpine
EXPOSE 5555
WORKDIR /usr/src/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "coop-server.py"]

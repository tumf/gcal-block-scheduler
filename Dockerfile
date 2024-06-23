FROM python:3.11-slim
WORKDIR /app
COPY cli.py /app/cli.py
COPY main.py /app/main.py
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
ENTRYPOINT [ "python", "cli.py" ]
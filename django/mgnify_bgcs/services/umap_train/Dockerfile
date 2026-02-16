FROM python:3.10-slim

WORKDIR /module
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY train_umap.py .

ENTRYPOINT ["python", "/module/train_umap.py"]

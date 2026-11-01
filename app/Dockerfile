FROM python:3.12-slim
WORKDIR /kiln
COPY app/server.py app/server.py
COPY app/index.html app/index.html
COPY runs/ runs/
COPY runs-h100/ runs-h100/
ENV PORT=8080
CMD ["python", "app/server.py"]

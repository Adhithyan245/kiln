FROM python:3.12-slim
WORKDIR /kiln
COPY app/server.py app/server.py
COPY app/index.html app/index.html
COPY runs/ runs/
COPY results/ results/
ENV PORT=8080
CMD ["python", "app/server.py"]

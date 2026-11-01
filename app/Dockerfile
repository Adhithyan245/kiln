FROM python:3.12-slim
WORKDIR /kiln
COPY app/ app/
COPY runs/ runs/
COPY runs-h100/ runs-h100/
COPY runs-h100-cut/ runs-h100-cut/
COPY data/precursor_props.csv data/precursor_props.csv
COPY protocol/ protocol/
COPY results/ results/
ENV PORT=8080
CMD ["python", "app/server.py"]

# The Kiln lab app on Render (render.yaml): the recorded-run replay plus the recipe finder.
# Replay needs only the standard library; the recipe finder adds pymatgen (with NumPy and SciPy) and
# reads the committed energies-only cache, data/mp-energies; the temperature what-if adds pydantic
# for the frozen scorer. No PyTorch, no MACE, no labels; an optional MP_API_KEY (set in the Render
# dashboard) lets the recipe finder fetch systems outside the cache. Live mode is never on and the
# MACE check stays off. Render sets PORT.
FROM python:3.12-slim
RUN pip install --no-cache-dir "pymatgen>=2024.1" "pydantic>=2.7"
WORKDIR /kiln
COPY . /kiln/
RUN useradd --uid 1000 kiln
USER kiln
ENV KILN_HOST=0.0.0.0 PYTHONPATH=/kiln/src PYTHONUNBUFFERED=1
EXPOSE 10000
CMD ["python3", "app/server.py"]

# Relais Transcriptions : bibliotheque standard Python uniquement.
FROM python:3.12-slim
RUN useradd --create-home --uid 1000 relais
WORKDIR /app
COPY relais.py admin.py page.html icone.png ./
RUN mkdir /donnees && chown relais /donnees
USER relais
ENV RELAIS_DONNEES=/donnees RELAIS_PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sante', timeout=4)"
CMD ["python", "relais.py"]

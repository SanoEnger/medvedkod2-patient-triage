FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MEDVED_DISABLE_DOTENV=1
WORKDIR /app
ARG INSTALL_VOICE=0
COPY requirements-backend.txt requirements-voice.txt ./
RUN pip install --no-cache-dir -r requirements-backend.txt \
    && if [ "$INSTALL_VOICE" = "1" ]; then pip install --no-cache-dir -r requirements-voice.txt; fi \
    && groupadd --gid 10001 medved \
    && useradd --uid 10001 --gid medved --no-create-home medved
COPY app ./app
COPY alembic ./alembic
COPY clinic_catalog ./clinic_catalog
COPY alembic.ini ./
USER 10001:10001
EXPOSE 8443
CMD ["python", "-m", "app.container", "serve"]

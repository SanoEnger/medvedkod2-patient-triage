FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MEDVED_DISABLE_DOTENV=1
WORKDIR /app
COPY requirements-backend.txt ./
RUN pip install --no-cache-dir -r requirements-backend.txt \
    && groupadd --gid 10001 medved \
    && useradd --uid 10001 --gid medved --no-create-home medved
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
USER 10001:10001
EXPOSE 8443
CMD ["python", "-m", "app.container", "serve"]

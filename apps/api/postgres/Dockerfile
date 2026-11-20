FROM postgres:16-alpine
COPY pg_hba.conf /etc/postgresql/pg_hba.conf
COPY docker-entrypoint.sh /usr/local/bin/medved-postgres
RUN chmod 755 /usr/local/bin/medved-postgres
ENTRYPOINT ["/usr/local/bin/medved-postgres"]
CMD ["postgres", "-c", "ssl=on", "-c", "ssl_min_protocol_version=TLSv1.2", "-c", "ssl_cert_file=/tmp/postgres.crt", "-c", "ssl_key_file=/tmp/postgres.key", "-c", "hba_file=/etc/postgresql/pg_hba.conf", "-c", "log_statement=none", "-c", "log_min_error_statement=panic", "-c", "log_error_verbosity=terse", "-c", "log_parameter_max_length_on_error=0", "-c", "log_parameter_max_length=0", "-c", "log_line_prefix=%m [postgres] [%p] %e ", "-c", "log_checkpoints=on", "-c", "log_lock_waits=on"]

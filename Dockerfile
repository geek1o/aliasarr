FROM python:3.11-slim

WORKDIR /app

# Системные зависимости (компиляция, mkvtoolnix для склейки, ffmpeg, curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    mkvtoolnix \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Сборка и установка новейшей оптимизированной версии SQLite 3.53.4 из исходников
ARG SQLITE_YEAR=2026
ARG SQLITE_VERSION=3530400
RUN mkdir -p /tmp/sqlite && cd /tmp/sqlite && \
    (curl -fsSL https://www.sqlite.org/${SQLITE_YEAR}/sqlite-autoconf-${SQLITE_VERSION}.tar.gz -o sqlite.tar.gz || \
     curl -fsSL https://www.sqlite.org/2026/sqlite-autoconf-${SQLITE_VERSION}.tar.gz -o sqlite.tar.gz || \
     curl -fsSL https://www.sqlite.org/sqlite-autoconf-${SQLITE_VERSION}.tar.gz -o sqlite.tar.gz) && \
    tar -xzf sqlite.tar.gz --strip-components=1 && \
    CFLAGS="-O3 -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_JSON1 -DSQLITE_ENABLE_RTREE -DSQLITE_ENABLE_MATH_FUNCTIONS -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_ENABLE_STAT4 -DSQLITE_ENABLE_DBSTAT_VTAB" \
    ./configure --prefix=/usr --enable-all --disable-static && \
    make -j$(nproc) && \
    make install && \
    for dir in $(find /usr/lib /lib /usr/local/lib -name "libsqlite3.so*" 2>/dev/null | xargs -n1 dirname 2>/dev/null | sort -u); do \
        if [ "$dir" != "/usr/lib" ] && [ -d "$dir" ]; then \
            cp -df /usr/lib/libsqlite3.so* "$dir/" 2>/dev/null || true; \
        fi \
    done && \
    ldconfig && \
    cd / && rm -rf /tmp/sqlite && \
    python3 -c "import sqlite3; print('>>> Verified SQLite version in Python:', sqlite3.sqlite_version); assert sqlite3.sqlite_version.startswith('3.53'), f'SQLite version mismatch: {sqlite3.sqlite_version}'"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY run.py .
COPY app ./app
COPY web ./web

# Тома: конфиг/БД, данные, папка загрузок
VOLUME ["/config", "/data", "/downloads"]

ENV DATABASE_URL=sqlite:////config/aliasarr.db
ENV PYTHONUNBUFFERED=1
ARG COMMIT_HASH=""
ENV COMMIT_HASH=${COMMIT_HASH}

EXPOSE 8989

CMD ["python", "run.py"]

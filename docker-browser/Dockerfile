# syntax=docker/dockerfile:1
#
# Imagem do Superset com headless browser para Alerts & Reports (prints de gráficos).
#
# A imagem oficial `apache/superset` é o flavor "lean": não traz browser nenhum.
# Sem isso, todo Report que manda screenshot morre com
#   "Failed taking a screenshot ... chromedriver unexpectedly exited. Status code was: 127"
# (127 = biblioteca compartilhada faltando — libglib/libnss/libxcb/libdbus).
#
# Aqui usamos Playwright + Chromium, que é a abordagem recomendada pelo projeto
# desde a 4.1.x e o que o próprio Dockerfile oficial faz via --build-arg
# INCLUDE_CHROMIUM=true. Playwright baixa um Chromium autocontido e o
# `install-deps` instala as libs de sistema que faltavam.
#
# Pareado com FEATURE_FLAGS["PLAYWRIGHT_REPORTS_AND_THUMBNAILS"] = True em
# docker/pythonpath_dev/superset_config_docker.py. Com Playwright ativo o
# WEBDRIVER_TYPE deixa de ter efeito (Playwright é sempre Chromium).
#
# Build:
#   docker compose --profile browser build superset-worker
# ou:
#   docker build -t astecha/superset-browser:6.0.0 docker-browser/
#
ARG SUPERSET_VERSION=6.0.0
FROM apache/superset:${SUPERSET_VERSION}

USER root

# Browsers fora do $HOME: o compose roda os serviços como root, mas a imagem base
# tem USER superset. Um caminho de sistema funciona para os dois — senão o
# Playwright procuraria em ~/.cache/ms-playwright do usuário errado.
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright-browsers

# `pip` no PATH é o do sistema (/usr/local/bin/pip), mas o Superset roda no venv
# /app/.venv. Instalar com pip puro colocaria o pacote no interpretador errado e
# o import falharia em runtime — daí o --python explícito.
# Pinado para o build ser reproduzível: o Chromium é baixado pela CLI do
# Playwright, então a versão do pacote determina a versão do browser
# (1.62.0 -> Chromium 151.0.7922.34, validado nesta imagem).
ARG PLAYWRIGHT_VERSION="1.62.0"
RUN set -eux; \
    uv pip install --python /app/.venv/bin/python --no-cache \
        "playwright${PLAYWRIGHT_VERSION:+==${PLAYWRIGHT_VERSION}}"; \
    playwright install-deps chromium; \
    playwright install chromium; \
    chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /root/.cache/*; \
    /app/.venv/bin/python -c "import playwright; print('playwright ok')"

USER superset

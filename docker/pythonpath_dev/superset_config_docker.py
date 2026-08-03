# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
Superset Docker Configuration - Production
This file overrides settings from superset_config.py for production deployment
"""

import os

# =========================================================================
# ALERTS AND REPORTS CONFIGURATION
# =========================================================================

# Enable Alerts and Reports feature
FEATURE_FLAGS = {
    "ALERT_REPORTS": True,
    # Playwright + Chromium vêm na imagem astecha/superset-browser
    # (ver docker-browser/Dockerfile), usada pelo serviço superset-worker.
    # Com a flag ligada, WEBDRIVER_TYPE abaixo deixa de ter efeito:
    # Playwright é sempre Chromium.
    "PLAYWRIGHT_REPORTS_AND_THUMBNAILS": True,
}

# ⚠️ IMPORTANTE: Desabilitar dry-run mode para enviar emails reais
ALERT_REPORTS_NOTIFICATION_DRY_RUN = False

# =========================================================================
# SENDGRID / SMTP CONFIGURATION
# =========================================================================

# SendGrid SMTP Configuration (porta 465 com SSL)
SMTP_HOST = os.getenv("MAIL_SERVER", "smtp.sendgrid.net")
SMTP_PORT = int(os.getenv("MAIL_PORT", "465"))
SMTP_USER = os.getenv("MAIL_USERNAME", "apikey")
SMTP_PASSWORD = os.getenv("MAIL_PASSWORD", "")
SMTP_MAIL_FROM = os.getenv("MAIL_DEFAULT_SENDER", "noreply@dashboard.astecha.com.br")

# Configurações SSL para porta 465
SMTP_SSL = True  # SSL direto na porta 465
SMTP_STARTTLS = False  # Não usar STARTTLS quando SSL está ativo
SMTP_SSL_SERVER_AUTH = True  # Verificar certificado do servidor

# Prefixo opcional no assunto dos emails
EMAIL_REPORTS_SUBJECT_PREFIX = "[Astecha Dashboard] "

# =========================================================================
# WEBDRIVER CONFIGURATION
# =========================================================================

# URL base interna (para o worker acessar o Superset)
# Usar o nome do serviço Docker
WEBDRIVER_BASEURL = os.getenv(
    "SUPERSET_WEBDRIVER_BASEURL",
    "http://superset:8088/"
)

# URL base amigável (link que vai no email)
# Usar o domínio público
WEBDRIVER_BASEURL_USER_FRIENDLY = os.getenv(
    "WEBDRIVER_BASEURL_USER_FRIENDLY",
    "http://dashboard.astecha.com.br/"
)

# Ignorado enquanto PLAYWRIGHT_REPORTS_AND_THUMBNAILS estiver True.
# Mantido só como fallback caso a flag seja desligada.
WEBDRIVER_TYPE = os.getenv("WEBDRIVER_TYPE", "chrome")

# Argumentos do Chrome para headless mode
WEBDRIVER_OPTION_ARGS = [
    "--force-device-scale-factor=2.0",
    "--high-dpi-support=2.0",
    "--headless",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-extensions",
]

# Tempos de espera para screenshots
SCREENSHOT_LOCATE_WAIT = 100
SCREENSHOT_LOAD_WAIT = 600

# -------------------------------------------------------------------------
# Espera do Playwright: garantir que os graficos terminem de carregar dados
# antes do print. A sequencia em utils/webdriver.py e:
#   goto(wait_until=WAIT_EVENT) -> sleep(HEADSTART) -> espera .chart-container
#   -> espera os .loading sumirem -> sleep(ANIMATION_WAIT) -> screenshot
#
# O default "domcontentloaded" dispara assim que o HTML e parseado, ou seja
# ANTES de qualquer query voltar. "networkidle" espera a rede silenciar, que e
# o proxy pratico para "as consultas dos graficos terminaram".
SCREENSHOT_PLAYWRIGHT_WAIT_EVENT = "networkidle"

# Teto de cada espera individual do Playwright. Se a rede nunca silenciar, o
# goto estoura esse timeout, e logado e o fluxo segue assim mesmo (nao perde o
# print). Cuidado ao aumentar: CeleryConfig.task_soft_time_limit e 180s e vale
# para a execucao inteira do report.
SCREENSHOT_PLAYWRIGHT_DEFAULT_TIMEOUT = 60000

# A espera dos .loading so cobre os elementos existentes NAQUELE instante:
# grafico que ainda nao comecou a renderizar (lazy-load abaixo da dobra) nao
# tem .loading e por isso ninguem espera por ele. Esses dois sleeps fixos sao a
# folga que cobre esse buraco.
SCREENSHOT_SELENIUM_HEADSTART = 10
SCREENSHOT_SELENIUM_ANIMATION_WAIT = 10


# =========================================================================
# EXECUTORS CONFIGURATION
# =========================================================================

# Por padrão, alertas são executados como o dono do alert/report
# Se quiser usar um usuário fixo, descomente e configure:
# from superset.tasks.types import FixedExecutor
# ALERT_REPORTS_EXECUTORS = [FixedExecutor("admin")]

# =========================================================================
# ADDITIONAL FEATURES
# =========================================================================

# Permitir formatação de data no assunto do email (opcional)
# FEATURE_FLAGS["DATE_FORMAT_IN_EMAIL_SUBJECT"] = True

# Lista de métodos de notificação disponíveis
ALERT_REPORTS_NOTIFICATION_METHODS = ["Email"]

# Se quiser adicionar Slack no futuro, adicione suas configs aqui:
# SLACK_API_TOKEN = os.getenv("SLACK_API_TOKEN", "")
# FEATURE_FLAGS["ALERT_REPORT_SLACK_V2"] = True
# ALERT_REPORTS_NOTIFICATION_METHODS.append("Slack")

# =========================================================================
# LOGGING
# =========================================================================

# Aumentar log level se precisar debugar
# import logging
# LOG_LEVEL = logging.DEBUG

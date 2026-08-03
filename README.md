# superset-deploy

Configuração de deploy de uma instância **Apache Superset 6.0.0** em Docker Compose,
com **Alerts & Reports funcionando de verdade** — isto é, mandando print de gráfico
por e-mail.

Este repositório guarda **só o que é nosso**: a imagem customizada com headless
browser, o nginx com TLS, o override de configuração do Superset e os scripts de
certificado. O Superset em si continua vindo da imagem oficial.

---

## Por que este repositório existe

A instalação padrão fica num clone do repositório upstream `apache/superset`, e
isso cria um problema silencioso: **os dois arquivos mais importantes de um deploy
real são gitignorados pelo próprio Superset.**

```
docker/pythonpath_dev/.gitignore:19:*   →  superset_config_docker.py
.gitignore:123:docker/*local*           →  docker/.env-local
```

O `git status` mostra a pasta limpa e passa a impressão de que não há nada para
versionar — enquanto toda a configuração de produção (SMTP, feature flags,
webdriver) mora exatamente ali. Além disso, um clone do upstream não aceita push
e briga com `git pull` a cada alteração local.

---

## O problema principal que este setup resolve

A imagem publicada `apache/superset` é o flavor **lean: não traz browser nenhum**.
Todo Report que manda screenshot morre com:

```
Failed taking a screenshot ... chromedriver unexpectedly exited. Status code was: 127
```

O `127` engana: parece binário ausente, mas é **biblioteca de sistema faltando**
(`libglib`, `libnss`, `libnspr`, `libxcb`, `libdbus`). O selenium-manager do
Superset baixa o chromedriver sozinho, ele não roda, e o ciclo se repete a cada
execução — na nossa instância isso acumulou **3,9 GB** de cache com 10 versões do
Chrome baixadas em loop.

A correção é [`docker-browser/Dockerfile`](docker-browser/Dockerfile): a imagem
oficial + **Playwright com Chromium**, que é a abordagem recomendada pelo projeto
desde a 4.1.x e o que o Dockerfile oficial faz via `--build-arg INCLUDE_CHROMIUM=true`.

---

## Estrutura

| Caminho | O que é |
|---|---|
| `docker-browser/Dockerfile` | imagem `apache/superset:6.0.0` + Playwright + Chromium |
| `docker-compose.yml` | stack completa; só o `superset-worker` usa a imagem com browser |
| `conf/nginx/` | `nginx.conf` + vhost TLS com headers de segurança |
| `docker/pythonpath_dev/superset_config_docker.py` | override de config do Superset (SMTP, feature flags, esperas do screenshot) |
| `docker/.env-local.example` | modelo do arquivo de segredos (o real nunca é commitado) |
| `scripts/init-letsencrypt.sh` | emissão inicial do certificado |
| `scripts/renew-cert.sh` | renovação + reload seguro do nginx |

---

## Deploy

```bash
git clone <este-repo> superset-deploy && cd superset-deploy

# 1. Segredos (nunca commitados)
cp docker/.env-local.example docker/.env-local
$EDITOR docker/.env-local      # SUPERSET_SECRET_KEY, MAIL_PASSWORD, domínio

# 2. Imagem com o headless browser (só o worker precisa dela)
docker build -t astecha/superset-browser:6.0.0 docker-browser/

# 3. Certificado (primeira vez)
EMAIL=voce@dominio DOMAIN=seu.dominio ./scripts/init-letsencrypt.sh

# 4. Subir
docker compose up -d
```

O `docker/` do upstream (`docker-bootstrap.sh`, `docker-init.sh`, `.env`) continua
vindo do repositório do Superset — este repo cobre apenas os arquivos próprios.

---

## Armadilhas descobertas na prática

Cada uma destas custou tempo de diagnóstico. Estão anotadas aqui para não custarem
de novo.

### 1. `WEBDRIVER_BASEURL` apontando para o domínio público derruba TODOS os alertas

Se o worker acessa o Superset pela URL pública, ele sai para a internet, volta pelo
nginx e passa a **validar TLS**. Quando o certificado vence, todo alerta quebra com
`SSL: CERTIFICATE_VERIFY_FAILED` — inclusive os que não tiram print nenhum, porque o
caminho de CSV/dataframe usa a mesma base. Tem que ser a URL interna da rede docker:

```
SUPERSET_WEBDRIVER_BASEURL=http://superset:8088/
```

O link público que vai no corpo do e-mail é outro setting: `WEBDRIVER_BASEURL_USER_FRIENDLY`.

### 2. O nginx recusa o reload e serve o certificado vencido em silêncio

O `nginx -s reload` re-parseia a config inteira, e o nginx resolve **todos** os
upstreams nesse parse. Um container parado que apareça como `upstream` faz o reload
falhar — e o nginx segue no ar servindo o certificado antigo, sem erro visível.
Pior: um `docker compose restart nginx` nessa situação **falha no boot e derruba o
site**. Por isso `scripts/renew-cert.sh` roda `nginx -t` como gate e confere no fim
o que está sendo servido de fato, via `openssl s_client`.

### 3. `pip` não é o Python do Superset

Na imagem oficial, `pip` no PATH é o do sistema (`/usr/local/bin/pip`), mas o
Superset roda no venv `/app/.venv`. Instalar com `pip` puro coloca o pacote no
interpretador errado e o import só falha em runtime. Use:

```dockerfile
uv pip install --python /app/.venv/bin/python playwright
```

### 4. `PLAYWRIGHT_BROWSERS_PATH` tem que ser caminho de sistema

A imagem base tem `USER superset`, mas o compose roda os serviços como `root`. Se o
browser for para o `$HOME`, um dos dois não o encontra. Daí
`/usr/local/share/playwright-browsers`.

### 5. Screenshot saindo antes dos gráficos carregarem

A sequência de espera do Superset é:

```
goto(wait_until=SCREENSHOT_PLAYWRIGHT_WAIT_EVENT)
  → sleep(SCREENSHOT_SELENIUM_HEADSTART)
  → espera .chart-container
  → espera os .loading sumirem
  → sleep(SCREENSHOT_SELENIUM_ANIMATION_WAIT)
  → print
```

O default do `WAIT_EVENT` é `domcontentloaded`, que dispara assim que o HTML é
parseado — **antes de qualquer query voltar**. Usamos `networkidle`. E note que a
espera dos `.loading` só cobre os elementos existentes *naquele instante*: gráfico
que ainda nem começou a renderizar não tem `.loading`, e ninguém espera por ele —
por isso os dois sleeps fixos.

Teto: `CeleryConfig.task_soft_time_limit` é **180s** para a execução inteira do
report. Não adianta aumentar as esperas sem olhar isso.

### 6. Antes de culpar o tempo, meça

"Gráfico não carregou no print" muitas vezes não é timing. Vale inspecionar o DOM
depois do load — contar `.chart-container`, `.loading` restantes e a altura do
dashboard. No nosso caso, o branco embaixo do print era **área vazia do próprio
dashboard** (1874px de conteúdo num viewport de 2000px, `WEBDRIVER_WINDOW["dashboard"]`),
não gráfico faltando.

---

## Testar um report sem enviar e-mail para os destinatários reais

O dry-run é checado **depois** do screenshot (`commands/report/execute.py`), então
esse caminho exercita o pipeline de imagem por inteiro sem mandar nada a ninguém:

```python
from superset.app import create_app
app_ = create_app()
with app_.app_context():
    from flask import current_app
    current_app.config["ALERT_REPORTS_NOTIFICATION_DRY_RUN"] = True   # trava
    from superset.commands.report.execute import AsyncExecuteReportScheduleCommand
    from datetime import datetime; import uuid
    AsyncExecuteReportScheduleCommand(str(uuid.uuid4()), <REPORT_ID>, datetime.utcnow()).run()
```

Para diagnosticar um alerta que falhou, o metadata DB é Postgres: as tabelas são
`report_schedule` (coluna `last_state`) e `report_execution_log` (`error_message`).

---

## Licença

Os arquivos derivados do Apache Superset mantêm a licença Apache 2.0 original.

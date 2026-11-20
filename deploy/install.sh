#!/usr/bin/env bash
# =====================================================================================
#  Spazio Comune – installazione su macchina virtuale, senza Docker
# =====================================================================================
#
#  Dalla cartella del repository clonato, come root:
#
#    sudo ./deploy/install.sh                                   # http://<ip>:8000
#    sudo ./deploy/install.sh --dominio prenota.comune.x.it     # + nginx su :80
#    sudo ./deploy/install.sh --dominio prenota.comune.x.it --email-tls ced@comune.x.it   # + HTTPS Let's Encrypt
#
#  Rieseguito più volte aggiorna il codice e le dipendenze senza toccare dati e configurazione.
#
#  Cosa installa:
#    - PostgreSQL della distribuzione, database "spazio_comune" con utente dedicato;
#    - Python 3.11+ e un ambiente virtuale in /opt/spazio-comune/venv (app, inferenza, MCP);
#    - configurazione in /etc/spazio-comune/spazio-comune.env con segreti generati (chmod 640);
#    - servizi systemd: spazio-comune-app, spazio-comune-inference, spazio-comune-mcp (facoltativo);
#    - backup giornaliero del database (timer systemd, 14 giorni in /var/backups/spazio-comune);
#    - con --dominio: nginx come reverse proxy; con --email-tls: certificato Let's Encrypt.
#
#  L'interfaccia di amministrazione (React + Vite) è già compilata nel repository
#  (app/venue_booking/static/admin): sulla VM non serve Node.js.
#
#  Sistemi supportati: Debian 12/13, Ubuntu 22.04/24.04 (apt); RHEL/Rocky/Alma 9 (dnf).
# =====================================================================================
set -euo pipefail

DIR=/opt/spazio-comune
CONF_DIR=/etc/spazio-comune
CONF=$CONF_DIR/spazio-comune.env
SERVICE_USER=spaziocomune
BACKUP=/var/backups/spazio-comune
KEEP_DAYS=14
PORT=8000
WORKERS=2
DOMAIN=""
TLS_EMAIL=""
WITH_MCP=1
DB_NAME=spazio_comune
DB_USER=spazio

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  cat <<EOF
Opzioni:
  --dominio NOME       nome pubblico del servizio: configura nginx e BASE_URL=https://NOME
  --email-tls EMAIL    richiede il certificato HTTPS a Let's Encrypt (serve --dominio e DNS già puntato)
  --porta N            porta locale dell'applicazione (predefinita 8000)
  --workers N          processi dell'applicazione (predefinito 2)
  --senza-mcp          non installa il servizio MCP
  -h, --help           questo aiuto
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dominio) DOMAIN="${2:?manca il nome}"; shift 2 ;;
    --email-tls) TLS_EMAIL="${2:?manca il value}"; shift 2 ;;
    --porta) PORT="${2:?manca la porta}"; shift 2 ;;
    --workers) WORKERS="${2:?manca il numero}"; shift 2 ;;
    --senza-mcp) WITH_MCP=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Opzione sconosciuta: $1" >&2; usage; exit 2 ;;
  esac
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31mERRORE: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "eseguire come root: sudo $0 $*"
[[ "$PORT" =~ ^[0-9]+$ && "$WORKERS" =~ ^[0-9]+$ ]] || die "--porta e --workers vogliono un numero"
[[ -z "$TLS_EMAIL" || -n "$DOMAIN" ]] || die "--email-tls richiede --dominio"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$SRC/app/venue_booking/main.py" ]] || die "lanciare lo script dal repository (manca app/venue_booking/main.py)"
[[ -f "$SRC/app/venue_booking/static/admin/index.html" ]] \
  || warn "interfaccia di amministrazione non compilata: eseguire 'cd admin && npm ci && npm run build' su una macchina con Node.js"

HAS_SYSTEMD=1
[[ -d /run/systemd/system ]] || { HAS_SYSTEMD=0; warn "systemd non attivo (container?): i servizi vengono scritti ma non avviati"; }

# ------------------------------------------------------------------ pacchetti
. /etc/os-release
step "Sistema: ${PRETTY_NAME:-sconosciuto}"
case " ${ID:-} ${ID_LIKE:-} " in
  *" debian "*|*" ubuntu "*)
    OS_FAMILY=debian
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    PACKAGES=(postgresql ca-certificates curl tzdata)
    for v in 3.13 3.12 3.11; do
      if apt-cache show "python$v-venv" >/dev/null 2>&1; then PACKAGES+=("python$v" "python$v-venv"); break; fi
    done
    [[ -n "$DOMAIN" ]] && PACKAGES+=(nginx)
    [[ -n "$TLS_EMAIL" ]] && PACKAGES+=(certbot python3-certbot-nginx)
    apt-get install -y -qq "${PACKAGES[@]}" >/dev/null
    ;;
  *" rhel "*|*" fedora "*|*" centos "*)
    OS_FAMILY=rhel
    PACKAGES=(postgresql-server postgresql-contrib ca-certificates curl tzdata)
    for v in 3.12 3.11; do
      if dnf -q list --available "python$v" >/dev/null 2>&1 || rpm -q "python$v" >/dev/null 2>&1; then PACKAGES+=("python$v"); break; fi
    done
    [[ -n "$DOMAIN" ]] && PACKAGES+=(nginx)
    if [[ -n "$TLS_EMAIL" ]]; then dnf install -y -q epel-release >/dev/null || true; PACKAGES+=(certbot python3-certbot-nginx); fi
    dnf install -y -q "${PACKAGES[@]}" >/dev/null
    ;;
  *) die "distribuzione non supportata (${ID:-?}): usare Debian/Ubuntu o RHEL/Rocky/Alma 9, oppure Docker" ;;
esac

PYTHON=""
for v in 3.13 3.12 3.11; do command -v "python$v" >/dev/null && { PYTHON="$(command -v "python$v")"; break; }; done
if [[ -z "$PYTHON" ]] && command -v python3 >/dev/null \
   && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then PYTHON="$(command -v python3)"; fi
[[ -n "$PYTHON" ]] || die "serve Python 3.11 o successivo"
echo "Python: $($PYTHON --version)"

# ------------------------------------------------------------------ utente e codice
step "Utente di sistema e codice in $DIR"
id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
install -d -m 755 "$DIR"
for part in app inference mcp_server; do
  rm -rf "$DIR/$part.new"
  cp -a "$SRC/$part" "$DIR/$part.new"
  find "$DIR/$part.new" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  rm -rf "$DIR/$part.old"
  [[ -d "$DIR/$part" ]] && mv "$DIR/$part" "$DIR/$part.old"
  mv "$DIR/$part.new" "$DIR/$part"
  rm -rf "$DIR/$part.old"
done
cp "$SRC/.env.example" "$DIR/env.example"
git -C "$SRC" rev-parse --short HEAD > "$DIR/VERSIONE" 2>/dev/null || date +%F > "$DIR/VERSIONE"
chown -R root:"$SERVICE_USER" "$DIR"
chmod -R u=rwX,g=rX,o= "$DIR"

step "Ambiente Python e dipendenze"
[[ -x "$DIR/venv/bin/python" ]] || "$PYTHON" -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
REQ=(-r "$DIR/app/requirements.txt" -r "$DIR/inference/requirements.txt")
if [[ $WITH_MCP -eq 1 ]]; then REQ+=(-r "$DIR/mcp_server/requirements.txt"); fi
"$DIR/venv/bin/pip" install -q "${REQ[@]}"
chown -R root:"$SERVICE_USER" "$DIR/venv"; chmod -R g+rX,o= "$DIR/venv"

# ------------------------------------------------------------------ configurazione
gen_secret() { "$PYTHON" -c "import secrets,sys; print(secrets.token_urlsafe(int(sys.argv[1])))" "$1"; }
set_var() {   # set_var KEY value nel file di configurazione (aggiunge la riga se manca)
  local key="$1" value="$2"
  if grep -q "^${key}=" "$CONF"; then
    "$PYTHON" - "$CONF" "$key" "$value" <<'PY'
import sys, re
f, k, v = sys.argv[1:]
t = open(f).read()
open(f, "w").write(re.sub(rf"^{re.escape(k)}=.*$", lambda m: f"{k}={v}", t, count=1, flags=re.M))
PY
  else
    printf '%s=%s\n' "$key" "$value" >> "$CONF"
  fi
}

FIRST_INSTALL=0
install -d -m 750 -o root -g "$SERVICE_USER" "$CONF_DIR"
if [[ ! -f "$CONF" ]]; then
  step "Configurazione nuova in $CONF (segreti generati)"
  FIRST_INSTALL=1
  cp "$SRC/.env.example" "$CONF"
  DB_PASSWORD="$("$PYTHON" -c 'import secrets; print(secrets.token_hex(24))')"
  ADMIN_PASSWORD="$(gen_secret 18)"; OFFICE_PASSWORD="$(gen_secret 18)"; CARETAKER_PASSWORD="$(gen_secret 12)"
  if [[ -n "$DOMAIN" && -n "$TLS_EMAIL" ]]; then
    BASE_URL="https://$DOMAIN"
  elif [[ -n "$DOMAIN" ]]; then
    BASE_URL="http://$DOMAIN"
  else
    IP="$(hostname -I 2>/dev/null | cut -d' ' -f1)"
    BASE_URL="http://${IP:-localhost}:$PORT"
  fi
  set_var SECRET_KEY "$("$PYTHON" -c 'import secrets; print(secrets.token_hex(32))')"
  set_var FEED_TOKEN "$("$PYTHON" -c 'import secrets; print(secrets.token_hex(24))')"
  set_var ADMIN_PASSWORD "$ADMIN_PASSWORD"
  set_var UFFICIO_PASSWORD "$OFFICE_PASSWORD"
  set_var CUSTODE_PASSWORD "$CARETAKER_PASSWORD"
  set_var POSTGRES_PASSWORD "$DB_PASSWORD"
  set_var DATABASE_URL "postgresql://$DB_USER:$DB_PASSWORD@127.0.0.1:5432/$DB_NAME"
  set_var INFERENCE_URL "http://127.0.0.1:8080"
  set_var BASE_URL "$BASE_URL"
  set_var APP_PORT "$PORT"
  if [[ $BASE_URL == https://* ]]; then set_var COOKIE_SECURE true; else set_var COOKIE_SECURE false; fi
  {
    echo
    echo "# --- aggiunte da deploy/install.sh: installazione senza Docker"
    echo "# Credenziali iniziali generate il $(date +%F). ADMIN_USER/ADMIN_PASSWORD aprono /admin;"
    echo "# da lì si cambiano tutte le password (poi queste non valgono più)."
  } >> "$CONF"
else
  step "Configurazione esistente in $CONF: non modificata"
  DB_PASSWORD="$(sed -n 's/^POSTGRES_PASSWORD=//p' "$CONF")"
  grep -q '^INFERENCE_URL=' "$CONF" || set_var INFERENCE_URL "http://127.0.0.1:8080"
  grep -q '^ADMIN_USER=' "$CONF" || set_var ADMIN_USER amministratore
  if ! grep -q '^ADMIN_PASSWORD=.' "$CONF"; then
    ADMIN_PASSWORD="$(gen_secret 18)"; set_var ADMIN_PASSWORD "$ADMIN_PASSWORD"
    warn "aggiunta ADMIN_PASSWORD per il back-office /admin: $ADMIN_PASSWORD"
  fi
  PORT="$(sed -n 's/^APP_PORT=//p' "$CONF")"; PORT="${PORT:-8000}"
fi
chown root:"$SERVICE_USER" "$CONF"; chmod 640 "$CONF"
[[ -n "$DB_PASSWORD" ]] || die "POSTGRES_PASSWORD vuota in $CONF"

# ------------------------------------------------------------------ PostgreSQL
step "PostgreSQL: database $DB_NAME"
if [[ $OS_FAMILY == rhel ]]; then
  if [[ ! -f /var/lib/pgsql/data/PG_VERSION ]]; then postgresql-setup --initdb >/dev/null; fi
  # connessioni locali via TCP con password (di default RHEL usa "ident")
  HBA=/var/lib/pgsql/data/pg_hba.conf
  sed -i -E 's/^(host\s+all\s+all\s+(127\.0\.0\.1\/32|::1\/128)\s+)ident/\1scram-sha-256/' "$HBA"
fi
if [[ $HAS_SYSTEMD -eq 1 ]]; then
  systemctl enable --now postgresql >/dev/null 2>&1 || systemctl enable --now "postgresql@*" >/dev/null 2>&1 || true
  systemctl reload postgresql >/dev/null 2>&1 || true
else
  service postgresql start >/dev/null 2>&1 || true
fi
for _ in $(seq 1 30); do runuser -u postgres -- psql -qAtc "SELECT 1" >/dev/null 2>&1 && break; sleep 1; done
runuser -u postgres -- psql -qAtc "SELECT 1" >/dev/null 2>&1 || die "PostgreSQL non risponde"
runuser -u postgres -- psql -q -v ON_ERROR_STOP=1 -v db_user="$DB_USER" -v pw="$DB_PASSWORD" -v db_name="$DB_NAME" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'db_user') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user') \gexec
ALTER ROLE :"db_user" WITH LOGIN PASSWORD :'pw';
SELECT format('CREATE DATABASE %I OWNER %I ENCODING ''UTF8'' TEMPLATE template0', :'db_name', :'db_user')
  WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name') \gexec
SQL
install -d -m 700 -o postgres -g postgres "$BACKUP"

# ------------------------------------------------------------------ servizi
step "Servizi systemd"
APP_HOST=0.0.0.0
if [[ -n "$DOMAIN" ]]; then APP_HOST=127.0.0.1; fi   # dietro nginx l'app ascolta solo in locale
render() {   # copia un modello sostituendo i segnaposto
  sed -e "s#@DIR@#$DIR#g" -e "s#@CONF@#$CONF#g" -e "s#@SERVICE_USER@#$SERVICE_USER#g" -e "s#@PORT@#$PORT#g" \
      -e "s#@WORKERS@#$WORKERS#g" -e "s#@HOST@#$APP_HOST#g" \
      -e "s#@BACKUP@#$BACKUP#g" -e "s#@KEEP_DAYS@#$KEEP_DAYS#g" -e "s#@DOMAIN@#$DOMAIN#g" "$1" > "$2"
}
SERVICES=(spazio-comune-inference spazio-comune-app)
[[ $WITH_MCP -eq 1 ]] && SERVICES+=(spazio-comune-mcp)
for s in "${SERVICES[@]}" spazio-comune-backup; do
  render "$SRC/deploy/systemd/$s.service" "/etc/systemd/system/$s.service"
done
cp "$SRC/deploy/systemd/spazio-comune-backup.timer" /etc/systemd/system/
[[ $WITH_MCP -eq 1 ]] || rm -f /etc/systemd/system/spazio-comune-mcp.service

if [[ $HAS_SYSTEMD -eq 1 ]]; then
  systemctl daemon-reload
  [[ $WITH_MCP -eq 1 ]] || systemctl disable --now spazio-comune-mcp >/dev/null 2>&1 || true
  systemctl enable spazio-comune-backup.timer "${SERVICES[@]}" >/dev/null 2>&1
  systemctl start spazio-comune-backup.timer
  systemctl restart "${SERVICES[@]}"
fi

# ------------------------------------------------------------------ nginx e HTTPS
if [[ -n "$DOMAIN" ]]; then
  step "nginx per $DOMAIN"
  if [[ -d /etc/nginx/sites-available ]]; then
    render "$SRC/deploy/nginx/spazio-comune.conf" /etc/nginx/sites-available/spazio-comune.conf
    ln -sf /etc/nginx/sites-available/spazio-comune.conf /etc/nginx/sites-enabled/spazio-comune.conf
    rm -f /etc/nginx/sites-enabled/default
  else
    render "$SRC/deploy/nginx/spazio-comune.conf" /etc/nginx/conf.d/spazio-comune.conf
    command -v setsebool >/dev/null && setsebool -P httpd_can_network_connect 1 || true   # SELinux: proxy verso l'app
  fi
  nginx -t
  if [[ $HAS_SYSTEMD -eq 1 ]]; then systemctl enable --now nginx >/dev/null 2>&1; systemctl reload nginx; fi
  if [[ -n "$TLS_EMAIL" && $HAS_SYSTEMD -eq 1 ]]; then
    step "Certificato HTTPS Let's Encrypt"
    certbot --nginx -d "$DOMAIN" -m "$TLS_EMAIL" --agree-tos --non-interactive --redirect \
      || warn "certbot non riuscito: verificare che il DNS di $DOMAIN punti a questa VM e riprovare"
  fi
fi

# ------------------------------------------------------------------ verifica
if [[ $HAS_SYSTEMD -eq 1 ]]; then
  step "Verifica"
  HEALTHY=0
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$PORT/api/v1/health" >/dev/null 2>&1; then HEALTHY=1; break; fi
    sleep 1
  done
  if [[ $HEALTHY -eq 1 ]]; then
    curl -fsS "http://127.0.0.1:$PORT/api/v1/health"; echo
  else
    warn "l'app non risponde: journalctl -u spazio-comune-app -n 50"
  fi
fi

BASE_URL="$(sed -n 's/^BASE_URL=//p' "$CONF")"
step "Fatto"
cat <<EOF
  Servizio:          $BASE_URL
  Amministrazione:   $BASE_URL/admin   (luogo, tariffe, orari, pagoPA, SPID/CIE, password)
  Backoffice:        $BASE_URL/backoffice
  Custode:           $BASE_URL/checkin
  Configurazione:    $CONF
  Log:               journalctl -u spazio-comune-app -f
  Backup database:   $BACKUP (ogni notte alle 02:30, conservati $KEEP_DAYS giorni)
EOF
if [[ $FIRST_INSTALL -eq 1 ]]; then
  cat <<EOF

  Credenziali iniziali (sono anche in $CONF, leggibile solo da root):
    amministratore  $(sed -n 's/^ADMIN_USER=//p' "$CONF") / $ADMIN_PASSWORD
    ufficio         $(sed -n 's/^UFFICIO_USER=//p' "$CONF") / $OFFICE_PASSWORD
    custode         custode / $CARETAKER_PASSWORD
  Prossimi passi: entrare in /admin, compilare luogo, tariffe e orari secondo il regolamento,
  poi pagoPA e SPID/CIE; cambiare le password in "Accessi del personale".
EOF
fi

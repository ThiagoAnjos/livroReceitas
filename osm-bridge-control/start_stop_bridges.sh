#!/usr/bin/env bash
#
# start_stop_bridges.sh
#
# Wrapper shell para start/stop/status das Messaging Bridges do WebLogic 12c
# que sustentam o ambiente Oracle OSM 7.4.0, utilizando o processo nativo
# do WLST (wlst.sh) em modo online.
#
# Uso:
#   ./start_stop_bridges.sh <start|stop|status> [-f <arquivo_lista_bridges>]
#
# Se -f nao for informado, ou o arquivo estiver vazio, a acao e aplicada a
# TODAS as Bridges configuradas no dominio.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/env.conf"
PY_SCRIPT="${SCRIPT_DIR}/bridge_action.py"
LOG_DIR="${SCRIPT_DIR}/logs"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
ALL_MARKER="__ALL__"

usage() {
  cat <<EOF
Uso: $(basename "$0") <start|stop|status> [-f <arquivo_lista_bridges>]

  start   Inicia a(s) Bridge(s)
  stop    Para a(s) Bridge(s)
  status  Consulta o estado atual da(s) Bridge(s)

  -f <arquivo>   Arquivo texto com uma Bridge por linha (linhas iniciadas
                 com # sao ignoradas). Se omitido ou vazio, TODAS as
                 Bridges configuradas no dominio sao afetadas.

Pre-requisitos:
  - ${CONFIG_FILE} preenchido (ver env.conf.example)
  - Credenciais WLST criptografadas via storeUserConfig()/storeKey()
    (ver README.md, secao "Credenciais")
EOF
  exit 1
}

[[ $# -lt 1 ]] && usage

ACTION="$1"
shift || true

case "$ACTION" in
  start|stop|status) ;;
  -h|--help) usage ;;
  *)
    echo "Acao invalida: '${ACTION}'. Use start, stop ou status." >&2
    usage
    ;;
esac

BRIDGE_LIST_FILE=""
while getopts ":f:" opt; do
  case "$opt" in
    f) BRIDGE_LIST_FILE="$OPTARG" ;;
    \?) echo "Opcao invalida: -$OPTARG" >&2; usage ;;
    :) echo "A opcao -$OPTARG requer um argumento." >&2; usage ;;
  esac
done

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Arquivo de configuracao nao encontrado: $CONFIG_FILE" >&2
  echo "Copie env.conf.example para env.conf e preencha os valores do ambiente." >&2
  exit 2
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"

: "${WLST_HOME:?WLST_HOME nao definido em env.conf}"
: "${ADMIN_URL:?ADMIN_URL nao definido em env.conf}"
: "${WLS_USER_CONFIG_FILE:?WLS_USER_CONFIG_FILE nao definido em env.conf}"
: "${WLS_USER_KEY_FILE:?WLS_USER_KEY_FILE nao definido em env.conf}"

WLST_EXEC="${WLST_HOME%/}/wlst.sh"
if [[ ! -x "$WLST_EXEC" ]]; then
  echo "wlst.sh nao encontrado ou sem permissao de execucao em: $WLST_EXEC" >&2
  exit 2
fi

if [[ -n "$BRIDGE_LIST_FILE" && ! -f "$BRIDGE_LIST_FILE" ]]; then
  echo "Arquivo de lista de Bridges nao encontrado: $BRIDGE_LIST_FILE" >&2
  exit 2
fi

if [[ ! -f "$WLS_USER_CONFIG_FILE" || ! -f "$WLS_USER_KEY_FILE" ]]; then
  echo "Credenciais WLST criptografadas nao encontradas (WLS_USER_CONFIG_FILE / WLS_USER_KEY_FILE)." >&2
  echo "Gere-as com storeUserConfig()/storeKey() antes de usar este script (ver README.md)." >&2
  exit 2
fi

mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/bridges_${ACTION}_${TIMESTAMP}.log"

LIST_ARG="${BRIDGE_LIST_FILE:-$ALL_MARKER}"

echo "Acao: ${ACTION} | Lista: ${BRIDGE_LIST_FILE:-<todas as Bridges do dominio>}" | tee -a "$LOG_FILE"
echo "Admin URL: ${ADMIN_URL}" | tee -a "$LOG_FILE"
echo "----------------------------------------------------------------------" | tee -a "$LOG_FILE"

set +e
"$WLST_EXEC" "$PY_SCRIPT" \
  "$ACTION" \
  "$LIST_ARG" \
  "$ADMIN_URL" \
  "$WLS_USER_CONFIG_FILE" \
  "$WLS_USER_KEY_FILE" 2>&1 | tee -a "$LOG_FILE"
RC=${PIPESTATUS[0]}
set -e

echo "----------------------------------------------------------------------"
echo "Log salvo em: $LOG_FILE"
exit "$RC"

#!/usr/bin/env bash
# scripts/run.sh — supervisor wrapper for `acelerado run`.
#
# Restarts o bot quando:
#   - sai com exit 75 (EX_TEMPFAIL — bot pediu restart, ex.: /update)
#   - crasha com qualquer outro exit ≠ 0 (e ≠ 130 = Ctrl+C)
#
# Encerra o loop quando:
#   - bot sai com exit 0 (shutdown limpo)
#   - SIGINT (Ctrl+C → exit 130)
#
# Backoff em crash é exponencial: 2s → 4s → 8s → … → cap em 60s.
# Restart pedido (exit 75) não tem backoff — queremos que volte rápido.
#
# Uso típico:
#   tmux new -s acelerado 'bash scripts/run.sh'
#   # depois: Ctrl+B, D pra desanexar / tmux attach -t acelerado

set -uo pipefail

# Vai pra raiz do repo independente de onde o script é chamado.
cd "$(dirname "$0")/.." || exit 1

BACKOFF_INITIAL=2
BACKOFF_MAX=60
backoff=$BACKOFF_INITIAL

log() {
    printf '[%s] [run.sh] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

trap 'log "received SIGINT; quitting"; exit 130' INT
trap 'log "received SIGTERM; quitting"; exit 143' TERM

while true; do
    log "starting acelerado..."
    uv run acelerado run
    code=$?

    case "$code" in
        0)
            log "clean exit; quitting"
            exit 0
            ;;
        75)
            log "restart requested by bot (exit 75)"
            backoff=$BACKOFF_INITIAL
            ;;
        130 | 143)
            log "interrupted (exit $code); quitting"
            exit "$code"
            ;;
        *)
            log "crash exit=$code; sleeping ${backoff}s before restart"
            sleep "$backoff"
            backoff=$(( backoff * 2 ))
            (( backoff > BACKOFF_MAX )) && backoff=$BACKOFF_MAX
            ;;
    esac
done

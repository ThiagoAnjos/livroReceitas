# bridge_action.py
#
# Script Jython executado EXCLUSIVAMENTE pelo interpretador nativo do WLST
# (wlst.sh), fornecido pelo WebLogic Server 12c / Oracle Fusion Middleware,
# sobre o qual roda o Oracle OSM 7.4.0.
#
# NAO deve ser executado com um interpretador Python convencional (CPython):
# os comandos connect(), domainConfig(), domainRuntime(), cd(), cmo, exit()
# sao injetados dinamicamente pelo WLST no namespace do Jython.
#
# Uso (via start_stop_bridges.sh):
#   wlst.sh bridge_action.py <start|stop|status> <arquivo_lista|__ALL__> \
#           <admin_url> <userConfigFile> <userKeyFile>
#
# Estrategia:
#   1) Conecta no AdminServer com credenciais criptografadas
#      (storeUserConfig/storeKey - ver README.md).
#   2) Le a configuracao do dominio (domainConfig) e obtem, via CMO,
#      todas as Bridges configuradas (DomainMBean.getMessagingBridges()).
#   3) Le o runtime do dominio (domainRuntime) e obtem, via CMO, as
#      instancias runtime das Bridges em cada Managed Server
#      (ServerRuntimeMBean.getMessagingBridgeRuntimes()).
#   4) Filtra pela lista externa informada (se vazia/ausente, afeta TODAS
#      as Bridges configuradas no dominio).
#   5) Aplica a acao diretamente sobre o objeto MBean runtime de cada
#      Bridge (start()/stop()), sem parsing textual de ls(), o que torna
#      a navegacao robusta a diferencas de formatacao entre versoes.

import sys

ALL_MARKER = "__ALL__"


def log(msg):
    print msg


def read_bridge_list(path):
    if path is None or path == ALL_MARKER:
        return []
    names = []
    f = open(path, 'r')
    try:
        for raw_line in f:
            line = raw_line.strip()
            if line and not line.startswith('#'):
                names.append(line)
    finally:
        f.close()
    return names


def discover_configured_bridges():
    """Retorna dict {nome_da_bridge: MessagingBridgeMBean} a partir da
    configuracao do dominio (fonte da verdade de 'todas as Bridges')."""
    domainConfig()
    cd('/')
    bridges = {}
    try:
        for b in cmo.getMessagingBridges():
            bridges[b.getName()] = b
    except Exception, e:
        log("AVISO: falha ao ler MessagingBridges da configuracao do dominio: %s" % e)
    return bridges


def discover_bridge_runtimes():
    """Retorna dict {nome_da_bridge: [MessagingBridgeRuntimeMBean, ...]}
    percorrendo os ServerRuntimes do dominio. Uma bridge pode ter mais de
    uma instancia runtime se estiver targetizada para varios servers."""
    domainRuntime()
    cd('/')
    runtime_map = {}
    try:
        server_runtimes = cmo.getServerRuntimes()
    except Exception, e:
        log("ERRO: falha ao listar ServerRuntimes do dominio: %s" % e)
        return runtime_map

    for server_rt in server_runtimes:
        try:
            bridge_runtimes = server_rt.getMessagingBridgeRuntimes()
        except Exception:
            # Server pode estar down/nao acessivel via RMI no momento
            continue
        for br in bridge_runtimes:
            runtime_map.setdefault(br.getName(), []).append(br)
    return runtime_map


def apply_action(name, br, action, results):
    try:
        state = br.getState()
        if action == 'status':
            results.append((name, br.getParent().getName(), 'OK', state))
            return

        if action == 'start':
            if state in ('Running',):
                results.append((name, br.getParent().getName(), 'SKIP',
                                 'ja em execucao (%s)' % state))
            else:
                br.start()
                results.append((name, br.getParent().getName(), 'OK',
                                 'start solicitado (estado anterior: %s)' % state))
        elif action == 'stop':
            if state in ('Shutdown', 'Stopped'):
                results.append((name, br.getParent().getName(), 'SKIP',
                                 'ja parada (%s)' % state))
            else:
                br.stop()
                results.append((name, br.getParent().getName(), 'OK',
                                 'stop solicitado (estado anterior: %s)' % state))
    except Exception, e:
        try:
            server_name = br.getParent().getName()
        except Exception:
            server_name = '?'
        results.append((name, server_name, 'FAIL', str(e)))


def finish(exit_code):
    try:
        disconnect()
    except Exception:
        pass
    exit(exitcode=exit_code)


def main():
    args = sys.argv
    # args[0] = nome do script .py; args[1..5] = parametros do caller
    if len(args) < 6:
        log("ERRO: argumentos insuficientes.")
        log("Esperado: <action> <list_file|__ALL__> <admin_url> <userConfigFile> <userKeyFile>")
        exit(exitcode=2)
        return

    action = args[1]
    list_file = args[2]
    admin_url = args[3]
    user_config_file = args[4]
    user_key_file = args[5]

    if action not in ('start', 'stop', 'status'):
        log("ERRO: acao invalida '%s'. Use start|stop|status." % action)
        exit(exitcode=2)
        return

    requested = read_bridge_list(list_file)

    log("Conectando em %s ..." % admin_url)
    try:
        connect(userConfigFile=user_config_file, userKeyFile=user_key_file, url=admin_url)
    except Exception, e:
        log("ERRO: falha ao conectar no AdminServer: %s" % e)
        exit(exitcode=2)
        return

    configured = discover_configured_bridges()
    if not configured:
        log("Nenhuma Bridge configurada foi encontrada no dominio.")
        finish(1)
        return

    if requested:
        target_names = requested
    else:
        target_names = list(configured.keys())

    unknown = [n for n in target_names if n not in configured]
    if unknown:
        log("AVISO: as Bridges a seguir nao existem na configuracao do dominio "
            "e serao ignoradas: %s" % unknown)
        target_names = [n for n in target_names if n in configured]

    if not target_names:
        log("Nenhuma Bridge valida para processar.")
        finish(1)
        return

    runtime_map = discover_bridge_runtimes()

    results = []
    for name in target_names:
        instances = runtime_map.get(name)
        if not instances:
            results.append((name, '-', 'FAIL',
                             'runtime MBean nao encontrado (server de destino parado '
                             'ou bridge sem target ativo)'))
            continue
        for br in instances:
            apply_action(name, br, action, results)

    log("")
    log("=" * 100)
    log("%-30s %-20s %-6s %s" % ("BRIDGE", "SERVER", "STATUS", "DETALHE"))
    log("=" * 100)
    failures = 0
    for name, server_name, status, detail in results:
        log("%-30s %-20s %-6s %s" % (name, server_name, status, detail))
        if status == 'FAIL':
            failures += 1

    log("")
    if failures:
        log("Concluido com %d falha(s)." % failures)
        finish(1)
    else:
        log("Concluido com sucesso.")
        finish(0)


main()

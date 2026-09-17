# bridge_action.py
#
# Script Jython executado EXCLUSIVAMENTE pelo interpretador nativo do WLST
# (wlst.sh), fornecido pelo WebLogic Server 12c / Oracle Fusion Middleware,
# sobre o qual roda o Oracle OSM 7.4.0.
#
# NAO deve ser executado com um interpretador Python convencional (CPython):
# os comandos connect(), domainConfig(), domainRuntime(), cd(), ls(), cmo,
# exit() sao injetados dinamicamente pelo WLST no namespace do Jython.
#
# Compatibilidade: o WLST classico do WebLogic 12c roda sobre Jython 2.2.1,
# entao este script evita deliberadamente qualquer sintaxe posterior ao
# Python 2.4 (sem expressoes condicionais "x if c else y", sem "with",
# sem "except E as e", etc).
#
# Uso (via start_stop_bridges.sh):
#   wlst.sh bridge_action.py <start|stop|status> <arquivo_lista|__ALL__> \
#           <admin_url> <userConfigFile> <userKeyFile>
#
# Estrategia:
#   1) Conecta no AdminServer com credenciais criptografadas
#      (storeUserConfig/storeKey - ver README.md).
#   2) Navega a arvore de configuracao do dominio (domainConfig) usando
#      caminhos absolutos (cd('/MessagingBridges')) para descobrir os
#      NOMES de todas as Bridges configuradas.
#   3) Navega a arvore de runtime do dominio (domainRuntime), tambem com
#      caminhos absolutos por servidor
#      (cd('/ServerRuntimes/<server>/MessagingBridgeRuntimes/<bridge>')),
#      para localizar a instancia runtime de cada Bridge.
#
#      Importante: a navegacao usa sempre caminhos absolutos explicitos
#      (nunca cd('/') seguido de cmo.getXxx()). Em WLST classico, alternar
#      entre domainConfig()/domainRuntime() e depois usar cd('/') pode
#      deixar a variavel global 'cmo' presa no MBean da arvore anterior,
#      causando AttributeError (ex.: 'getServerRuntimes' no DomainMBean de
#      configuracao). Usar cd() com o caminho completo de cada MBean forca
#      a re-resolucao correta de 'cmo' a cada passo.
#   4) Filtra pela lista externa informada (se vazia/ausente, afeta TODAS
#      as Bridges configuradas no dominio).
#   5) Aplica start()/stop() diretamente sobre o objeto MBean runtime de
#      cada Bridge, capturado no momento do cd() para o seu caminho.

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


def discover_configured_bridge_names():
    """Retorna a lista de nomes de todas as Bridges configuradas no
    dominio (fonte da verdade de 'todas as Bridges')."""
    domainConfig()
    try:
        cd('/MessagingBridges')
        names = ls(returnMap='true')
    except Exception, e:
        log("AVISO: falha ao listar /MessagingBridges na configuracao do dominio: %s" % e)
        return []
    return list(names)


def discover_bridge_runtimes():
    """Retorna dict {nome_da_bridge: [(nome_do_server, MessagingBridgeRuntimeMBean), ...]}
    percorrendo os ServerRuntimes do dominio. Uma bridge pode ter mais de
    uma instancia runtime se estiver targetizada para varios servers."""
    domainRuntime()
    runtime_map = {}
    try:
        cd('/ServerRuntimes')
        server_names = ls(returnMap='true')
    except Exception, e:
        log("ERRO: falha ao listar /ServerRuntimes do dominio: %s" % e)
        return runtime_map

    for server_name in server_names:
        bridges_path = '/ServerRuntimes/%s/MessagingBridgeRuntimes' % server_name
        try:
            cd(bridges_path)
            bridge_names = ls(returnMap='true')
        except Exception:
            # Server sem bridges targetizadas, parado, ou sem acesso RMI no momento
            continue
        for bname in bridge_names:
            try:
                cd('%s/%s' % (bridges_path, bname))
                runtime_map.setdefault(bname, []).append((server_name, cmo))
            except Exception:
                continue
    return runtime_map


def apply_action(name, server_name, br, action, results):
    try:
        state = br.getState()
        if action == 'status':
            results.append((name, server_name, 'OK', state))
            return

        if action == 'start':
            if state in ('Running',):
                results.append((name, server_name, 'SKIP',
                                 'ja em execucao (%s)' % state))
            else:
                br.start()
                results.append((name, server_name, 'OK',
                                 'start solicitado (estado anterior: %s)' % state))
        elif action == 'stop':
            if state in ('Shutdown', 'Stopped'):
                results.append((name, server_name, 'SKIP',
                                 'ja parada (%s)' % state))
            else:
                br.stop()
                results.append((name, server_name, 'OK',
                                 'stop solicitado (estado anterior: %s)' % state))
    except Exception, e:
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

    configured = discover_configured_bridge_names()
    if not configured:
        log("Nenhuma Bridge configurada foi encontrada no dominio.")
        finish(1)
        return

    if requested:
        target_names = requested
    else:
        target_names = list(configured)

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
        for instance in instances:
            server_name = instance[0]
            br = instance[1]
            apply_action(name, server_name, br, action, results)

    log("")
    log("=" * 100)
    log("%-30s %-20s %-6s %s" % ("BRIDGE", "SERVER", "STATUS", "DETALHE"))
    log("=" * 100)
    failures = 0
    for row in results:
        log("%-30s %-20s %-6s %s" % (row[0], row[1], row[2], row[3]))
        if row[2] == 'FAIL':
            failures += 1

    log("")
    if failures:
        log("Concluido com %d falha(s)." % failures)
        finish(1)
    else:
        log("Concluido com sucesso.")
        finish(0)


main()

# bridge_action.py
#
# Script Jython executado EXCLUSIVAMENTE pelo interpretador nativo do WLST
# (wlst.sh), fornecido pelo WebLogic Server 12c / Oracle Fusion Middleware,
# sobre o qual roda o Oracle OSM 7.4.0.
#
# NAO deve ser executado com um interpretador Python convencional (CPython):
# os comandos connect(), domainConfig(), domainRuntime(), edit(), startEdit(),
# save(), activate(), cancelEdit(), cd(), ls(), cmo, exit() sao injetados
# dinamicamente pelo WLST no namespace do Jython.
#
# Compatibilidade: o WLST classico do WebLogic 12c roda sobre Jython 2.2.1,
# entao este script evita deliberadamente qualquer sintaxe posterior ao
# Python 2.4 (sem expressoes condicionais "x if c else y", sem "with", sem
# "except E as e", sem os literais True/False/bool que so existem a partir
# do Python 2.3 - usa-se 1/0 no lugar).
#
# Uso (via start_stop_bridges.sh):
#   wlst.sh bridge_action.py <start|stop|status> <arquivo_lista|__ALL__> \
#           <admin_url> <userConfigFile> <userKeyFile>
#
# Descoberta ("status"):
#   Le a arvore de runtime do dominio (domainRuntime) com caminhos
#   absolutos por servidor
#   (cd('/ServerRuntimes/<server>/MessagingBridgeRuntimes/<bridge>')) para
#   reportar o estado real de cada instancia da Bridge. Quando a Bridge
#   esta targetizada para um cluster, o WebLogic nomeia cada instancia
#   runtime como "<nome>@<servidor>"; o nome logico (sem o sufixo) e' o
#   mesmo usado na configuracao do dominio.
#
# Start/Stop:
#   O MBean de runtime da Messaging Bridge NAO implementa start()/stop()
#   nesta versao do WebLogic (erro observado:
#   "java.lang.UnsupportedOperationException: This method is not
#   implemented on runtime mbean. The way of start/stop a bridge at
#   runtime is to change the Started attribute on the configuration
#   mbean"). Por isso, start/stop sao feitos via arvore de EDICAO do
#   dominio (edit()/startEdit()/activate()), alterando o atributo
#   dinamico "Started" do MBean de configuracao (/MessagingBridges/<nome>),
#   que e' a forma nativa e suportada de ligar/desligar uma Bridge sem
#   reiniciar o servidor.
#
# Em ambos os casos, se a lista externa de Bridges estiver vazia/ausente,
# a acao e' aplicada a TODAS as Bridges configuradas no dominio.

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
        except Exception, e:
            log("AVISO: nao foi possivel acessar %s: %s" % (bridges_path, e))
            continue
        for bname in bridge_names:
            # Quando a Bridge esta targetizada para um cluster, o WebLogic
            # desambigua o nome do MBean runtime de cada membro anexando
            # "@<nome_do_servidor>" (ex.: "Bridge_X@vrainst01"). O nome
            # configurado no dominio (usado na lista externa e na
            # descoberta de todas as Bridges) e sempre sem esse sufixo.
            logical_name = bname.split('@')[0]
            try:
                cd('%s/%s' % (bridges_path, bname))
                runtime_map.setdefault(logical_name, []).append((server_name, cmo))
            except Exception, e:
                log("AVISO: falha ao acessar %s/%s: %s" % (bridges_path, bname, e))
                continue
    return runtime_map


def run_status(target_names, results):
    runtime_map = discover_bridge_runtimes()
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
            try:
                state = br.getState()
                results.append((name, server_name, 'OK', state))
            except Exception, e:
                results.append((name, server_name, 'FAIL', str(e)))


def run_start_stop(action, target_names, results):
    """Liga/desliga as Bridges alterando o atributo 'Started' no MBean de
    CONFIGURACAO (via arvore de edicao), que e' a forma suportada nesta
    versao do WebLogic (o MBean de runtime nao implementa start()/stop())."""
    if action == 'start':
        started_value = 1
    else:
        started_value = 0

    try:
        edit()
        startEdit()
    except Exception, e:
        for name in target_names:
            results.append((name, '-', 'FAIL',
                             'falha ao iniciar sessao de edicao (startEdit): %s' % e))
        return

    prepared = []
    for name in target_names:
        try:
            cd('/MessagingBridges/%s' % name)
            cmo.setStarted(started_value)
            prepared.append(name)
        except Exception, e:
            results.append((name, '-', 'FAIL', str(e)))

    if not prepared:
        try:
            cancelEdit('y')
        except Exception:
            pass
        return

    try:
        save()
        activate()
    except Exception, e:
        log("ERRO ao ativar as alteracoes (activate): %s" % e)
        try:
            cancelEdit('y')
        except Exception:
            pass
        for name in prepared:
            results.append((name, '-', 'FAIL', 'activate() falhou: %s' % e))
        return

    if started_value:
        detail = 'start aplicado (Started=true, configuracao ativada)'
    else:
        detail = 'stop aplicado (Started=false, configuracao ativada)'
    for name in prepared:
        results.append((name, '-', 'OK', detail))


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

    results = []
    if action == 'status':
        run_status(target_names, results)
    else:
        run_start_stop(action, target_names, results)

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

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
# do Python 2.3 - usa-se 1/0 no lugar), e evita caracteres nao-ASCII (o
# console do WLST classico pode nao lidar bem com Unicode).
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
#
# Experiencia do usuario:
#   O WLST imprime, por padrao, muito "ruido" nativo (banners de conexao,
#   avisos de protocolo, dump completo de cada ls()/cd()). Para manter a
#   tela limpa, este script redireciona temporariamente o stream Java
#   System.out para um destino nulo enquanto navega as arvores do WLST
#   (ver silence()/unsilence() para o motivo de NAO tocar em sys.stdout),
#   e usa log()/debug() - que escrevem diretamente no sys.stdout original,
#   guardado no inicio - para mostrar somente as mensagens proprias do
#   script. Defina a variavel de ambiente BRIDGE_DEBUG=1 para reexibir os
#   detalhes de navegacao (util em diagnostico).

import sys
import os

from java.io import OutputStream
from java.io import PrintStream
from java.lang import System

ALL_MARKER = "__ALL__"
LINE = "-" * 78
DOUBLE_LINE = "=" * 78

try:
    DEBUG = os.environ.get('BRIDGE_DEBUG', '0') not in ('', '0')
except Exception:
    DEBUG = 0

_REAL_STDOUT = sys.stdout
_REAL_JAVA_OUT = System.out


class _NullOutputStream(OutputStream):
    def write(self, b):
        pass


_NULL_JAVA_OUT = PrintStream(_NullOutputStream())


def log(msg):
    _REAL_STDOUT.write(str(msg) + "\n")
    _REAL_STDOUT.flush()


def debug(msg):
    if DEBUG:
        log("   [debug] %s" % msg)


def silence():
    """Suprime a saida nativa e verbosa do WLST redirecionando o stream
    Java System.out para um destino nulo. log()/debug() continuam
    visiveis pois escrevem direto no objeto sys.stdout original, salvo
    antes de qualquer redirecionamento.

    Importante: NAO trocamos sys.stdout (nivel Python) aqui. Comandos
    nativos do WLST como connect() fazem, internamente, escritas de
    baixo nivel em sys.stdout usando a assinatura Java
    write(buffer, offset, tamanho) (3 argumentos). Um objeto Python puro
    (com write(self, s) de 1 argumento) quebra essa chamada com
    "TypeError: write() too many arguments". Por isso a supressao usa
    apenas System.setOut(), que aponta para um java.io.OutputStream real
    e aceita todas as variantes de write()."""
    System.setOut(_NULL_JAVA_OUT)


def unsilence():
    System.setOut(_REAL_JAVA_OUT)


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
        debug("falha ao listar /MessagingBridges na configuracao do dominio: %s" % e)
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
        debug("falha ao listar /ServerRuntimes do dominio: %s" % e)
        return runtime_map

    debug("servidores encontrados: %s" % list(server_names))

    for server_name in server_names:
        bridges_path = '/ServerRuntimes/%s/MessagingBridgeRuntimes' % server_name
        try:
            cd(bridges_path)
            bridge_names = ls(returnMap='true')
        except Exception, e:
            debug("nao foi possivel acessar %s: %s" % (bridges_path, e))
            continue
        debug("%s -> %s" % (server_name, list(bridge_names)))
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
                debug("falha ao acessar %s/%s: %s" % (bridges_path, bname, e))
                continue
    return runtime_map


def run_status(target_names, results):
    runtime_map = discover_bridge_runtimes()
    for name in target_names:
        instances = runtime_map.get(name)
        if not instances:
            results.append((name, '-', 'FAIL',
                             'instancia runtime nao encontrada (servidor de destino '
                             'parado ou bridge sem target ativo)'))
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
                             'nao foi possivel iniciar a sessao de edicao do dominio '
                             '(pode haver outra edicao em andamento no Console/EM): %s' % e))
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
        debug("activate() falhou: %s" % e)
        try:
            cancelEdit('y')
        except Exception:
            pass
        for name in prepared:
            results.append((name, '-', 'FAIL', 'falha ao ativar a alteracao: %s' % e))
        return

    if started_value:
        detail = 'bridge iniciada (configuracao ativada)'
    else:
        detail = 'bridge parada (configuracao ativada)'
    for name in prepared:
        results.append((name, '-', 'OK', detail))


def print_header(action, admin_url, requested):
    log("")
    log(DOUBLE_LINE)
    log(" Oracle OSM - Controle de Bridges (WebLogic Messaging Bridges)")
    log(DOUBLE_LINE)
    log("Admin URL : %s" % admin_url)
    log("Acao      : %s" % action.upper())
    if requested:
        log("Escopo    : %d bridge(s) informada(s) na lista externa" % len(requested))
    else:
        log("Escopo    : TODAS as bridges do dominio")
    log(DOUBLE_LINE)


def print_results(action, results):
    log("")
    if action == 'status':
        log("%-42s %-16s %s" % ("BRIDGE", "SERVIDOR", "ESTADO"))
        log(LINE)
        for row in results:
            name, server_name, status, detail = row[0], row[1], row[2], row[3]
            if status == 'FAIL':
                log("%-42s %-16s FALHA: %s" % (name, server_name, detail))
            else:
                log("%-42s %-16s %s" % (name, server_name, detail))
    else:
        log("%-42s %-10s %s" % ("BRIDGE", "RESULTADO", "DETALHE"))
        log(LINE)
        for row in results:
            name, status, detail = row[0], row[2], row[3]
            if status == 'OK':
                tag = 'OK'
            elif status == 'SKIP':
                tag = 'IGNORADA'
            else:
                tag = 'FALHA'
            log("%-42s %-10s %s" % (name, tag, detail))
    log(LINE)


def print_summary(results):
    ok = 0
    skip = 0
    fail = 0
    for row in results:
        if row[2] == 'OK':
            ok += 1
        elif row[2] == 'SKIP':
            skip += 1
        elif row[2] == 'FAIL':
            fail += 1
    log("Total: %d | OK: %d | Ignoradas: %d | Falhas: %d" % (len(results), ok, skip, fail))
    log(DOUBLE_LINE)
    log("")
    return fail


def finish(exit_code):
    unsilence()
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

    print_header(action, admin_url, requested)

    log("Conectando ao AdminServer...")
    # IMPORTANTE: nao chamar silence() antes/durante o connect(). O
    # mecanismo interno do WLST usado por connect() para relatar
    # progresso/retentativas de conexao ("<iostream>") depende do
    # System.out original nesse momento; troca-lo aqui quebra o connect()
    # com "TypeError: write() too many arguments" mesmo usando um
    # java.io.OutputStream valido. O ruido do connect() (banner de
    # conexao, aviso de protocolo) e' pequeno e unico, entao fica visivel.
    try:
        connect(userConfigFile=user_config_file, userKeyFile=user_key_file, url=admin_url)
    except Exception, e:
        log("ERRO: falha ao conectar no AdminServer: %s" % e)
        exit(exitcode=2)
        return
    log("Conectado com sucesso.")

    results = []
    try:
        silence()
        try:
            configured = discover_configured_bridge_names()
            if not configured:
                unsilence()
                log("Nenhuma Bridge configurada foi encontrada no dominio.")
                finish(1)
                return

            if requested:
                target_names = requested
            else:
                target_names = list(configured)

            unknown = [n for n in target_names if n not in configured]
            if unknown:
                unsilence()
                log("AVISO: as Bridges a seguir nao existem na configuracao do dominio "
                    "e serao ignoradas: %s" % unknown)
                silence()
                target_names = [n for n in target_names if n in configured]

            if not target_names:
                unsilence()
                log("Nenhuma Bridge valida para processar.")
                finish(1)
                return

            log("Processando %d bridge(s)..." % len(target_names))

            if action == 'status':
                run_status(target_names, results)
            else:
                run_start_stop(action, target_names, results)
        finally:
            unsilence()
    except Exception, e:
        unsilence()
        log("ERRO inesperado durante o processamento: %s" % e)
        finish(2)
        return

    print_results(action, results)
    failures = print_summary(results)

    if failures:
        log("Concluido com %d falha(s). Verifique os detalhes acima." % failures)
        finish(1)
    else:
        log("Concluido com sucesso.")
        finish(0)


main()

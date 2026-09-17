# Controle de Bridges (Oracle OSM 7.4.0 / WebLogic 12c) via WLST

## Validação da abordagem

**Sim, é viável e é a forma recomendada pela Oracle.** As "Bridges" de um
ambiente Oracle OSM são, tecnicamente, **Messaging Bridges do WebLogic
Server** (Services > Messaging > Bridges no console), usadas para
encaminhar mensagens JMS entre as filas internas do OSM e sistemas
externos (ex.: filas de entrada/saída de pedidos). Esse é um recurso
**nativo** do WebLogic, com MBeans dedicados:

- Configuração: `weblogic.management.configuration.MessagingBridgeMBean`,
  em `/MessagingBridges/<nome>` na árvore de configuração/edição do
  domínio, com o atributo dinâmico `Started` (boolean).
- Runtime: `weblogic.management.runtime.MessagingBridgeRuntimeMBean`, em
  `/ServerRuntimes/<server>/MessagingBridgeRuntimes/<nome>`, com o
  atributo `State` (usado apenas para consulta de status).

Como o WLST (WebLogic Scripting Tool) é construído sobre **Jython**
(implementação de Python para a JVM) e expõe esses MBeans diretamente no
namespace do script, é totalmente possível — e é o processo nativo
suportado pela Oracle — escrever um script Python/Jython que:

1. Conecta no AdminServer do domínio (`connect()`).
2. Lê a configuração do domínio (`domainConfig()`) para descobrir todas
   as Bridges existentes.
3. Para `status`: lê o runtime do domínio (`domainRuntime()`) e localiza
   a instância runtime de cada Bridge no(s) servidor(es) em que está
   targetizada, reportando o atributo `State`.
4. Para `start`/`stop`: usa a árvore de **edição** do domínio
   (`edit()` + `startEdit()`), altera o atributo `Started` (`1`/`0`) do
   MBean de **configuração** de cada Bridge alvo e ativa a mudança
   (`save()` + `activate()`).

> **Por que não `start()`/`stop()` no MBean de runtime?** Nessa versão
> do WebLogic, o `MessagingBridgeRuntimeMBean` não implementa esses
> métodos — a chamada retorna
> `java.lang.UnsupportedOperationException: This method is not
> implemented on runtime mbean. The way of start/stop a bridge at
> runtime is to change the Started attribute on the configuration
> mbean`. Essa é, portanto, a forma nativa e suportada de ligar/desligar
> uma Bridge sem reiniciar o servidor: alterar `Started` no MBean de
> configuração e ativar a mudança (atributo dinâmico, não exige
> restart).

Não há necessidade de nenhuma ferramenta externa ao WebLogic/FMW — tudo é
feito com comandos WLST nativos (`connect`, `domainConfig`,
`domainRuntime`, `edit`, `startEdit`, `save`, `activate`, `cmo`, `exit`).

> Observação: se no seu ambiente o termo "Bridge" se referir, na
> verdade, a um módulo/aplicação Java EE implantado (ex.: um adaptador
> customizado implantado como `.ear`/`.war`), a mesma arquitetura de
> script serve, trocando apenas a lógica de descoberta/ação em
> `bridge_action.py` para usar `startApplication()`/`stopApplication()`
> sobre `cmo.getAppDeployments()`. A implementação atual assume o
> significado nativo do WebLogic (Messaging Bridges), por ser o que o
> WLST gerencia nativamente com esse nome.

## Arquivos

| Arquivo                     | Descrição                                                              |
|------------------------------|--------------------------------------------------------------------------|
| `start_stop_bridges.sh`      | Script Shell de entrada (parâmetros, validações, chamada ao WLST)        |
| `bridge_action.py`           | Script Jython executado pelo `wlst.sh` (lógica de start/stop/status)     |
| `env.conf.example`           | Modelo de configuração do ambiente (copiar para `env.conf`)              |
| `bridges.lst.example`        | Modelo de lista externa de Bridges (opcional)                            |
| `logs/`                      | Log de cada execução (criado automaticamente)                            |

## Uso

```bash
# Afeta TODAS as Bridges do domínio
./start_stop_bridges.sh stop
./start_stop_bridges.sh start

# Afeta apenas as Bridges listadas em um arquivo externo
./start_stop_bridges.sh stop  -f minhas_bridges.lst
./start_stop_bridges.sh start -f minhas_bridges.lst

# Consulta o estado atual (não altera nada)
./start_stop_bridges.sh status
```

Se `-f` for omitido, ou o arquivo indicado estiver vazio, **todas** as
Bridges configuradas no domínio são afetadas — conforme solicitado.

## Configuração

1. Copie `env.conf.example` para `env.conf` no mesmo diretório e ajuste:
   - `WLST_HOME`: diretório do WLST nativo (`$ORACLE_HOME/oracle_common/common/bin` em FMW 12c).
   - `ADMIN_URL`: URL `t3://host:porta` do AdminServer do domínio do OSM.
   - `WLS_USER_CONFIG_FILE` / `WLS_USER_KEY_FILE`: arquivos de credenciais
     criptografadas (ver seção abaixo). **Não** versionar `env.conf`.

2. (Opcional) Crie um arquivo de lista de Bridges com base em
   `bridges.lst.example`.

## Credenciais (sem senha em texto plano)

O script nunca recebe usuário/senha em texto plano. Gere uma vez, de
forma interativa, as credenciais criptografadas com o próprio WLST:

```bash
$ORACLE_HOME/oracle_common/common/bin/wlst.sh
```

```python
connect('usuario_admin', 'senha', 't3://osm-admin.exemplo.com:7001')
storeUserConfig(userConfigFile='/u01/oracle/security/osm.uc',
                 userKeyFile='/u01/oracle/security/osm.key')
disconnect()
```

Proteja esses dois arquivos com permissões restritas (ex.: `chmod 600`) e
referencie seus caminhos em `env.conf`. O `connect()` dentro de
`bridge_action.py` usa exclusivamente `userConfigFile`/`userKeyFile`.

## Códigos de saída

- `0`: sucesso (todas as Bridges alvo processadas sem erro).
- `1`: execução concluída, mas com uma ou mais falhas por Bridge
  (detalhado na tabela de saída e no log).
- `2`: erro de uso/ambiente (parâmetro inválido, `env.conf` ausente,
  `wlst.sh` não encontrado, credenciais ausentes, falha de conexão).

## Limitações conhecidas

- Uma Bridge sem instância runtime ativa (por exemplo, porque o Managed
  Server ao qual está targetizada está parado) é reportada como `FAIL`
  com o motivo "runtime MBean não encontrado" — isso é esperado e não
  aciona nenhuma ação sobre o servidor em si.
- Nomes informados na lista externa que não existirem na configuração do
  domínio são ignorados com um aviso, e não interrompem o processamento
  das demais Bridges.
- `start`/`stop` usam uma sessão de edição exclusiva do domínio
  (`startEdit()`). Se outra sessão (ex.: Console/Enterprise Manager ou
  outro WLST) já estiver com o lock de edição aberto, o script falha ao
  iniciar a sessão e reporta isso na coluna `DETALHE` — não fica preso
  aguardando o lock.
- Como `start`/`stop` atuam sobre o MBean de **configuração** (por
  domínio, não por servidor), a coluna `SERVER` no relatório dessas duas
  ações aparece como `-`; a distinção por servidor só é aplicável ao
  `status`, que lê o runtime de cada instância.

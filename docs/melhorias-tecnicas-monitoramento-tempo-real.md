# Documento técnico — melhorias de monitoramento de consumo em tempo real

**Projeto:** Codenotch Plasma  
**Status:** proposta técnica  
**Data da avaliação:** 24/09/2026  
**Escopo:** coleta em segundo plano, atualização do notch, qualidade dos dados dos cards e confiabilidade operacional  
**Fora de escopo:** implementação, mudança visual definitiva, novos provedores e alterações nos serviços externos

## 1. Resumo executivo

O Codenotch já executa as consultas de rede fora da thread da interface e atualiza o overlay por sinais do Qt. Portanto, existe uma base adequada para processamento em segundo plano. O principal problema está na política de atualização: o `refreshInterval` apenas acorda o agendador, mas um provedor considerado ocioso só é efetivamente consultado depois de cinco minutos. Na prática, Codex, Cursor e Kiro não acompanham o consumo no intervalo configurado, pois não possuem rastreamento de sessão ativo.

A recomendação é substituir o polling uniforme por uma estratégia híbrida:

1. observar eventos locais de uso com `inotify`/watchers;
2. atualizar imediatamente o estado de atividade no notch;
3. reconciliar a quota com a API usando debounce, cooldown e tentativas curtas após a atividade;
4. manter polling lento quando não houver atividade;
5. representar explicitamente atualização, origem, confiança, erro e idade do dado;
6. preservar um histórico local pequeno para calcular variação e tendência.

“Tempo real” deve significar que o Codenotch reage imediatamente aos sinais disponíveis e exibe a nova quota assim que ela passa a ser publicada pelo provedor. Não é possível garantir atualização instantânea da porcentagem quando a API oficial consolida o consumo com atraso ou não oferece push/websocket.

## 2. Diagnóstico do estado atual

### 2.1 O que já está bem estruturado

- As chamadas de provedores rodam em `ThreadPoolExecutor`, sem bloquear diretamente a interface (`store.py:37`, `store.py:157`).
- O resultado volta à thread Qt por sinal (`_fetch_done`) e o overlay reage ao sinal `changed` (`store.py:25`, `overlay.py:97`).
- Há cache de último snapshot, permitindo iniciar com informação anterior (`archive.py`).
- Existe tratamento de `Retry-After` nos principais provedores e persistência de `backoffUntil`.
- Reset de janela já possui observação dedicada e refresh programado próximo ao horário do reset.
- Claude e Antigravity já expõem uma noção de sessão local, usada para animar atividade.
- Os parsers normalizam os limites em `windows`, criando uma base comum para todos os cards.

### 2.2 Limitações que impedem acompanhamento em tempo real

#### A. `refreshInterval` não representa a frequência real de leitura

O timer usa o intervalo configurado, com mínimo de 15 segundos, mas `_refresh_all()` só consulta um provedor quando:

- passaram cinco minutos desde a última tentativa (`IDLE_REFRESH`);
- o provedor está marcado como ocupado; ou
- há reset pendente.

Consequências:

- Codex, Cursor Personal, Cursor Corp e Kiro, todos com `tracks_sessions = False`, normalmente atualizam a cada cinco minutos;
- o valor padrão de 60 segundos cria uma expectativa incorreta na configuração e na documentação;
- diminuir `refreshInterval` aumenta os despertares do timer, mas não necessariamente aumenta a atualização das quotas.

#### B. A atividade local ainda depende de varredura

- Sessões são verificadas a cada cinco segundos (`store.py:51`).
- Claude relê os JSONs do diretório de sessões.
- Antigravity percorre diretórios e relê `transcript.jsonl`; a contagem atual considera eventos do arquivo, não necessariamente prompts consumíveis.
- Grok declara `tracks_sessions = True`, mas `_scan_sessions()` não possui ramo que leia as sessões do Grok. Seu contador local só muda durante um `fetch`, que em repouso ocorre a cada cinco minutos.
- Não há watcher de arquivos, bancos SQLite, processos ou logs.

#### C. O estado do provedor é pouco expressivo

Hoje o estado é essencialmente `ok`, `stale` ou `error`, acompanhado por `fetching` e um erro opcional. Isso não diferencia adequadamente:

- dado fresco enquanto uma nova leitura está em andamento;
- offline com último dado válido;
- rate limit e seu próximo horário de tentativa;
- autenticação expirada;
- dado oficial, derivado de log ou cache potencialmente antigo;
- leitura local atual versus quota remota ainda não reconciliada.

Além disso, `state_of()` recalcula o status apenas pela idade do snapshot. Assim, um snapshot recente pode continuar `ok` mesmo quando a última tentativa falhou.

#### D. Falta proteção contra resultados obsoletos e agendamentos duplicados

- Não há geração/versão da requisição. Após recarregar provedores, uma requisição antiga pode retornar e tentar aplicar resultado ao estado novo.
- O controle `fetching` impede duas chamadas simultâneas do mesmo provedor, mas não coalesce as razões do refresh nem registra que uma nova leitura ficou pendente.
- Cada sucesso chama `_schedule_reset_refreshes()`, criando novos `QTimer.singleShot` não canceláveis para os mesmos resets.
- O pool possui três workers para até sete provedores. Um provedor lento ocupa uma vaga por até 15 segundos por request; o Kiro pode testar várias combinações sequencialmente e o Antigravity pode fazer descoberta/processamento adicional.
- O Cursor chama `/api/auth/me` duas vezes dentro da mesma leitura e poderia separar metadados de conta da quota.

#### E. O snapshot perde dados úteis

O modelo comum preserva principalmente porcentagem e reset. Campos absolutos existentes nas respostas, como `used`, `limit`, créditos disponíveis ou tipo da conta, frequentemente são descartados pelo parser. O cache também remove campos como `membershipType`, `email` e `ringMode` ao restaurar.

Sem histórico de snapshots não é possível mostrar:

- quanto aumentou desde a última leitura;
- velocidade de consumo;
- previsão de esgotamento;
- confirmação de que a API ainda não refletiu uma atividade recém-detectada.

#### F. Cards não comunicam frescor e confiabilidade de modo consistente

O card mostra a idade do dado apenas quando uma tentativa falha. Em uma leitura normal o usuário não sabe se o valor tem 5 segundos ou 14 minutos. Também não há estado visual explícito para “atualizando”, “local”, “oficial”, “cache”, “rate limited” ou “offline”.

Outros pontos:

- a UI mistura textos em inglês e português;
- notas longas são desenhadas em uma única linha, sem wrap ou elipse;
- a altura é estimada por quantidade de blocos, não pelo texto efetivamente renderizado;
- todos os limites têm o mesmo peso visual;
- o e-mail do Cursor pode aparecer inteiro, o que é indesejável em gravações de tela;
- o timer de animação acorda a cada 16 ms mesmo quando não existe atividade visível.

## 3. Objetivos e critérios de “tempo real”

### 3.1 Objetivos

- Refletir um evento local de atividade no notch em até 1 segundo no percentil 95.
- Consultar a quota logo após o uso, sem exceder limites ou gerar bloqueio do provedor.
- Aplicar a nova porcentagem em até um ciclo adaptativo depois de ela se tornar visível na fonte oficial.
- Manter o último valor válido durante falhas e indicar claramente sua idade e condição.
- Reduzir polling e leitura repetida de arquivos quando não há atividade.
- Permitir que todos os cards respondam às mesmas perguntas: quanto usei, quanto resta, quando reinicia, quão recente/confiável é o dado e o que está acontecendo agora.

### 3.2 Não objetivos

- Inferir consumo exato quando o provedor não publica limite ou unidade.
- Fazer scraping de interface web como fonte primária.
- contornar rate limits, autenticação ou proteções dos provedores;
- prometer atualização instantânea de uma API que consolida consumo com atraso;
- persistir tokens, conteúdo de prompts, nomes de arquivos completos ou texto das conversas.

## 4. Arquitetura proposta

```text
Fontes locais ──> Observadores de atividade ──> ActivityStore ──> notch imediatamente
                         │
                         └──> RefreshCoordinator ──> adapters ──> APIs/bridge/cache
                                      │
                                      ├── debounce/cooldown/backoff
                                      ├── coalescência e geração da request
                                      └── reset/retry/reconciliação

adapters ──> Snapshot normalizado ──> Diff + histórico curto ──> ProviderState
                                                               │
                                                               └──> cards/notch
```

Separar responsabilidades evita que regras de UI, atividade local e política de rede fiquem concentradas em `UsageStore`.

### 4.1 Componentes

#### `ActivityObserver`

Responsável por sinais locais e barato o suficiente para permanecer ativo continuamente.

- Usa watcher nativo do Linux para mudanças em arquivos/diretórios.
- Reinstala a observação quando um arquivo é substituído atomicamente.
- Mantém uma reconciliação lenta por polling para recuperar eventos perdidos.
- Processa somente o trecho novo de JSONL, guardando inode e offset; não relê todo o arquivo.
- Emite eventos normalizados: `started`, `progress`, `waiting`, `completed`, `file_changed`.
- Nunca envia conteúdo de prompt para logs ou para o snapshot.

`QFileSystemWatcher` pode ser suficiente para arquivos estáveis, mas não é recursivo e pode perder observação após rename. Como o projeto é exclusivo de Linux/KDE, um backend `inotify` com fallback para polling oferece comportamento mais previsível.

#### `RefreshCoordinator`

Centraliza decisões de quando consultar cada provedor.

- Uma única requisição em voo por provedor.
- Eventos adicionais durante a requisição são coalescidos em `pending_refresh = true`.
- Cada leitura recebe `generation` e `request_id`; resultados de gerações antigas são descartados.
- Cooldown mínimo e política de polling são definidos por capacidade do provedor.
- `Retry-After` tem precedência absoluta.
- Backoff exponencial com jitter é usado para offline/5xx.
- Timers de reset possuem chave `(provider, window, reset_at)` e são substituíveis/canceláveis.
- O scheduler registra `nextRefreshAt` para a UI e diagnóstico.

#### `ProviderAdapter`

Cada adapter declara capacidades em vez de depender de condicionais pelo ID:

```python
capabilities = {
    "activity": "watch" | "poll" | "none",
    "quota": "remote" | "bridge" | "local" | "hybrid",
    "min_refresh_seconds": 30,
    "supports_account": True,
    "supports_absolute_values": True,
}
```

O contrato do adapter deve separar:

- `read_activity()` — leitura local barata;
- `fetch_usage()` — leitura da quota;
- `fetch_account()` — metadados de baixa frequência;
- `health()` — autenticação, origem e qualidade da fonte.

#### `SnapshotHistory`

Mantém um histórico pequeno, local e sem conteúdo sensível.

- Somente pontos em que o valor mudou, mais um heartbeat esparso.
- Retenção sugerida: 24 horas ou no máximo 200 pontos por provedor.
- Escrita atômica e com debounce; não regravar o arquivo a cada sucesso idêntico.
- Reiniciar a série quando o limite reseta, o plano muda ou a janela troca de ID.

## 5. Política de atualização adaptativa

| Situação | Ação recomendada |
|---|---|
| Inicialização | exibir cache imediatamente e consultar todos os provedores em segundo plano, com pequeno jitter |
| Evento local de uso | atualizar atividade em até 1 s e agendar reconciliação da quota após 2 s |
| Quota ainda igual após uso | tentar novamente em 10 s e 30 s; encerrar a sequência quando mudar ou após o limite de tentativas |
| Sessão ativa | polling remoto a cada 30–60 s, conforme o provedor |
| Card aberto e dado antigo | refresh oportunista se o cooldown permitir |
| Inativo | polling a cada 5 min |
| Offline/5xx | manter snapshot, backoff exponencial com jitter, máximo sugerido de 15 min |
| HTTP 429 | respeitar `Retry-After`; não fazer tentativas intermediárias |
| Próximo ao reset | uma leitura pouco antes apenas para atualizar o countdown; confirmar em +5 s e +30 s |
| Retorno da rede/suspensão | revalidar cache e consultar apenas estados vencidos |

O `refreshInterval` deve ser renomeado ou redefinido. Alternativas:

- preferida: `idleRefreshInterval` para o ciclo ocioso, acompanhado por `activeRefreshInterval` e `minProviderCooldown`;
- compatível: manter `refreshInterval` como frequência ativa e introduzir `idleRefreshInterval = 300`.

Valores menores que o cooldown do adapter não devem provocar requests extras. A tela de configuração deve explicar essa limitação.

### 5.1 Perfis iniciais por provedor

| Provedor | Sinal local | Reconciliação sugerida | Observação |
|---|---|---:|---|
| Claude | diretório de sessões | 30 s ativo / 5 min ocioso | atividade já existe; trocar scan por watcher |
| Codex | watcher de artefatos locais apenas quando a fonte for estável; caso contrário processo/idle | 30–60 s ativo / 5 min ocioso | percentual depende da API remota |
| Cursor | mudanças no `state.vscdb`/processo | 60 s ativo / 5 min ocioso | cachear conta; evitar duas chamadas a `/api/auth/me` |
| Antigravity | append em transcripts + bridge local | bridge a cada 2–5 s ativo; API remota no máximo a cada 60 s | preferir bridge local quando disponível |
| Grok | append em `updates.jsonl` | contador imediato; quota em 60 s ativo | implementar atividade real no scanner/observer |
| Kiro | `state.vscdb` e `q-client.log` | local imediato; API em 60 s ativo | evitar matriz completa de endpoints em toda tentativa |

Esses intervalos são valores iniciais e devem ser ajustados por medições e comportamento de rate limit, não tratados como contrato fixo.

## 6. Modelo de dados v2

### 6.1 Estado do provedor

```json
{
  "providerId": "codex",
  "generation": 3,
  "status": "fresh",
  "refreshing": false,
  "lastAttemptAt": 0,
  "lastSuccessAt": 0,
  "nextRefreshAt": 0,
  "lastError": null,
  "sourceHealth": {
    "source": "official-api",
    "fidelity": "official",
    "observedAt": 0
  },
  "activity": null,
  "snapshot": {}
}
```

Estados sugeridos:

- `initializing`
- `refreshing`
- `fresh`
- `degraded` — há dado válido, mas a última leitura falhou ou a fonte é parcial
- `stale`
- `rate_limited`
- `auth_required`
- `offline`
- `unavailable`

### 6.2 Janela de consumo

```json
{
  "id": "weekly",
  "label": "Limite semanal",
  "scope": "all-models",
  "usedFraction": 0.62,
  "remainingFraction": 0.38,
  "usedValue": 620,
  "limitValue": 1000,
  "unit": "credits",
  "resetsAt": "2026-09-28T00:00:00Z",
  "observedAt": "2026-09-24T18:20:00Z",
  "isPrimary": true,
  "fidelity": "official"
}
```

Campos absolutos são opcionais. O card deve ocultá-los quando a fonte não os fornece, sem inventar equivalência entre percentual, requests, tokens e créditos.

### 6.3 Métricas derivadas

- `deltaUsedFraction`: variação desde o último snapshot comparável;
- `consumptionRate`: variação por hora, somente com pelo menos dois pontos válidos;
- `projectedExhaustionAt`: previsão opcional, somente com amostra suficiente e janela monotônica;
- `apiLag`: tempo entre atividade local e mudança confirmada na quota;
- `confidence`: `high`, `medium` ou `low`, derivada da fonte, idade e consistência.

Não mostrar previsão quando houver poucos pontos, reset recente, quota dinâmica ou comportamento não monotônico.

## 7. Nova hierarquia de informação dos cards

Todos os cards devem seguir uma estrutura comum, com dados específicos do provedor abaixo dela.

### 7.1 Cabeçalho

- ícone e nome do provedor;
- plano/conta como badge discreto;
- estado: “Ao vivo”, “Atualizando”, “Offline”, “Login necessário” ou “Limitado pela API”;
- idade do último sucesso: “Atualizado há 8 s”;
- origem/qualidade: “Oficial”, “Bridge local”, “Log”, “Cache”.

O e-mail deve ser mascarado por padrão, por exemplo `w***@empresa.com`, com uma preferência explícita para exibição completa.

### 7.2 Resumo primário

- percentual usado em destaque;
- percentual restante ao lado;
- reset relativo e horário absoluto em tooltip/copy secundária;
- variação desde a última leitura, quando houver: `+3% desde 14:20`;
- indicador de atividade local quando a API ainda não atualizou: “Uso detectado; aguardando consolidação”.

### 7.3 Limites secundários

- mostrar no máximo três linhas compactas antes de usar `+N limites`;
- ordenar por relevância: janela curta ativa, quota principal, quota crítica e limites por modelo;
- distinguir visualmente `usado` de `restante` e manter a mesma semântica em todos os provedores;
- não usar somente cor para comunicar criticidade; incluir texto/ícone.

### 7.4 Atividade e saúde

- sessão atual, estado (`trabalhando`, `aguardando`, `ociosa`) e duração;
- motivo de espera somente quando disponível sem expor conteúdo sensível;
- último erro em uma linha curta e acionável;
- próximo refresh quando rate limited;
- ação de atualizar manualmente sem abrir o dashboard; abrir o dashboard deve ser uma ação separada.

### 7.5 Renderização

- calcular altura com métricas reais de texto;
- suportar wrap/elipse e largura máxima dependente do monitor;
- usar componentes de layout ou um modelo de linhas em vez de acoplar medição e pintura;
- atualizar textos relativos por um timer global de baixa frequência;
- ligar a animação de 16 ms apenas enquanto existir animação/atividade visível.

## 8. Dados recomendados por card

### 8.1 Codex

**Prioridade visual:** janela de 5 horas e limite semanal.

- 5 h: usado, restante e horário do reset;
- semanal: usado, restante e data do reset;
- plano (`plan_type`) no cabeçalho;
- delta após a última sessão detectada;
- indicação “API ainda não consolidou” quando houver evento local sem mudança na quota;
- manter o anel duplo, mas incluir legenda inequívoca no card: externo = 5 h, interno = semanal.

Não afirmar número de requests ou tokens sem campo oficial correspondente.

### 8.2 Claude

**Prioridade visual:** sessão de 5 horas, total semanal e limites específicos por modelo.

- sessão atual/5 h;
- todos os modelos/semana;
- Opus, Sonnet e outros limites publicados, ordenados por criticidade;
- sessões ativas com origem (Terminal, VS Code, Agent), projeto abreviado e duração;
- espera por aprovação/ferramenta quando a sessão informar esse estado;
- plano `subscriptionType` no cabeçalho.

O observador deve reagir ao JSON de sessão; a quota remota continua sujeita ao tempo de consolidação da Anthropic.

### 8.3 Cursor Personal

**Prioridade visual:** total incluído mensal.

- total incluído e reset do ciclo;
- Auto model e API model, quando publicados;
- gasto on-demand, preferencialmente com valor absoluto e moeda/unidade se a resposta trouxer ambos;
- plano (Hobby/Pro etc.);
- conta mascarada;
- origem da autenticação: IDE ou agent.

Os campos `used` e `limit` devem ser preservados no modelo normalizado, não somente convertidos em percentual.

### 8.4 Cursor Corp

**Prioridade visual:** alocação individual e pool da equipe.

- alocação pessoal;
- uso compartilhado da equipe;
- on-demand, quando habilitado;
- plano Team/Business/Enterprise;
- conta corporativa mascarada;
- origem da sessão do navegador e eventual necessidade de relogin.

Separar claramente quota pessoal e quota da organização para evitar que um percentual do pool pareça limite individual.

### 8.5 Antigravity

**Prioridade visual:** quota oficial via bridge, com origem explícita.

- prompt credits e flow credits com usados/restantes absolutos quando disponíveis;
- quotas por modelo e respectivos resets;
- atividade local atual e requests estimados no dia;
- tier/plano;
- badge de fonte: `Bridge oficial`, `API` ou `Estimativa local`;
- alerta curto quando o app precisa estar aberto.

O contador de requests local deve contar eventos semanticamente relevantes, não todas as linhas do transcript. O parser precisa ser validado com fixtures anonimizadas.

### 8.6 Grok

**Prioridade visual:** créditos publicados ou, na ausência deles, contador local claramente marcado como estimativa.

- percentual de créditos e fim do período;
- breakdown por produto quando publicado;
- valor mensal usado/limite, se disponível;
- requests do dia em tempo real por append do log;
- status de autenticação e necessidade de executar `grok login`;
- badge `Oficial` ou `Estimativa local`.

O card não deve desenhar anel percentual para “requests hoje” quando não existe limite publicado.

### 8.7 Kiro

**Prioridade visual:** créditos principais e bônus.

- créditos usados, limite e restante em valores absolutos;
- bonus/free trial e data de expiração;
- próximo reset;
- assinatura/subscription title;
- fonte: API oficial, log recente ou cache do IDE;
- idade específica do cache e instrução curta para abrir `/usage` quando necessário.

O adapter deve memorizar qual host/origin/método funcionou e começar por ele nas próximas leituras. As demais combinações só devem ser tentadas quando a estratégia conhecida falhar.

## 9. Persistência, privacidade e segurança

- Persistir somente dados necessários para quota, status e tendência.
- Nunca persistir token, cookie, header, CSRF, prompt, resposta ou caminho completo do projeto.
- Mascarar e-mail e nomes de projeto na UI por padrão.
- Usar escrita atômica (`arquivo temporário + rename`) para cache e config.
- Incluir `schemaVersion` no arquivo de leituras e migração tolerante.
- Aplicar permissões restritivas ao cache, pois plano, e-mail mascarado e padrões de uso ainda são dados pessoais.
- Remover informações de conta do cache quando não forem necessárias para inicialização.
- Manter TLS desabilitado somente para o endpoint localhost do bridge já identificado; nunca reutilizar esse contexto em chamadas externas.

## 10. Observabilidade e diagnóstico

Adicionar logs estruturados e sanitizados por provedor:

- razão do refresh (`startup`, `activity`, `hover`, `timer`, `reset`, `retry`, `manual`);
- duração da leitura;
- origem selecionada;
- resultado (`changed`, `unchanged`, `failed`, `discarded_generation`);
- status HTTP sem corpo e sem headers sensíveis;
- atraso entre evento local e atualização da quota;
- número de requests evitadas por debounce/cooldown.

Uma tela/ação “Diagnóstico” pode mostrar, sem credenciais:

- último sucesso/tentativa;
- próximo refresh;
- cooldown/backoff;
- fonte e fidelidade;
- watcher ativo/inativo;
- erro resumido.

## 11. Configuração proposta

```json
{
  "idleRefreshInterval": 300,
  "activeRefreshInterval": 30,
  "activityDebounceMs": 750,
  "refreshOnHover": true,
  "historyRetentionHours": 24,
  "showAccountIdentity": "masked",
  "showTrends": true
}
```

Os cooldowns mínimos e políticas de Retry-After devem permanecer sob controle dos adapters, não totalmente configuráveis, para evitar uso inseguro da API.

## 12. Plano de entrega recomendado

### Fase 0 — métricas e contrato

- definir `ProviderState`, `UsageSnapshot` e capacidades do adapter;
- criar fake clock e fixtures anonimizadas dos provedores;
- registrar latência, requests e origem sem dados sensíveis.

### Fase 1 — correção do scheduler

- tornar o significado de `refreshInterval` honesto;
- implementar geração da request, coalescência e `pending_refresh`;
- deduplicar timers de reset;
- separar status de frescor do status da última tentativa;
- respeitar backoff com jitter;
- evitar regravar cache quando o snapshot não mudou.

### Fase 2 — eventos locais

- introduzir observadores com fallback de reconciliação;
- migrar Claude e Grok primeiro, por terem fontes locais simples;
- migrar Antigravity para leitura incremental;
- observar Cursor e Kiro sem bloquear a UI;
- validar a existência de uma fonte local estável para Codex antes de habilitá-la.

### Fase 3 — adapters e eficiência

- separar uso, conta e saúde;
- preservar valores absolutos;
- cachear metadados de conta do Cursor;
- memorizar estratégia funcional do Kiro;
- preferir bridge local do Antigravity;
- implementar estados degradados e rate limited.

### Fase 4 — cards

- adotar hierarquia comum;
- incluir frescor, origem e confiança;
- adicionar dados específicos de cada IA;
- suportar wrap, compactação e privacidade;
- desacoplar ação “abrir dashboard” da ação “atualizar”.

### Fase 5 — estabilização

- testes de suspensão/retorno, offline, reset e troca de conta;
- perfil de CPU, memória, wakeups e I/O;
- rollout gradual dos watchers por provedor;
- documentação do significado de “tempo real”.

## 13. Critérios de aceite

### Funcionais

- Cache válido aparece imediatamente ao iniciar; refresh acontece em background.
- Evento local suportado altera o estado de atividade em até 1 s no P95.
- Depois de um evento, a quota é reconciliada pela política 2 s/10 s/30 s sem requests simultâneas.
- Assim que a fonte oficial retorna um novo valor, notch e card mudam no mesmo ciclo de aplicação do resultado.
- Um erro não apaga o último valor válido e muda o card para estado degradado.
- HTTP 429 impede novas chamadas até `Retry-After`.
- Resultados de uma geração antiga nunca sobrescrevem provedor recarregado ou conta trocada.
- Cada reset possui no máximo um conjunto ativo de timers.
- Grok atualiza requests locais sem depender do polling de cinco minutos.
- Kiro e Antigravity informam claramente quando o valor vem de log/cache/estimativa.

### UX

- Todo card mostra última atualização, origem e estado.
- Todo limite com percentual mostra usado e restante.
- Reset relativo e absoluto são acessíveis sem ambiguidade de fuso.
- Texto não ultrapassa o card e informações secundárias são compactadas.
- E-mails e projetos permanecem mascarados por padrão.
- Cores de alerta possuem redundância textual/visual.

### Desempenho

- Sem animação ou atividade, o timer de 16 ms fica desligado.
- Leitura de JSONL é incremental.
- Nenhum watcher dispara tempestade de requests; eventos são debounced e coalescidos.
- O consumo ocioso de CPU e I/O não ultrapassa o baseline atual; meta de engenharia sugerida: CPU média inferior a 1% no cenário ocioso de referência.

## 14. Estratégia de testes

### Unitários

- scheduler com relógio falso: ativo, ocioso, debounce, cooldown, backoff e reset;
- descarte de resultado por geração;
- coalescência durante request em voo;
- parsers com respostas completas, parciais e inválidas;
- cálculo de delta/tendência atravessando resets;
- migração e restauração do cache v2;
- mascaramento de identidade e sanitização de logs.

### Integração

- servidor HTTP local simulando 200, 401, 403, 429, 5xx, timeout e atraso de consolidação;
- append, rename e recriação dos arquivos observados;
- suspensão e retomada do sistema;
- troca de conta enquanto uma leitura está em andamento;
- vários provedores lentos com prioridade para o provedor ativo.

### UI/visual

- snapshots de card para cada estado e provedor;
- textos longos, muitos limites, escalas e temas;
- monitores pequenos e múltiplos;
- contraste e comunicação sem depender exclusivamente de cor.

## 15. Priorização final

| Prioridade | Melhoria | Impacto |
|---|---|---|
| P0 | corrigir semântica do refresh e criar scheduler adaptativo | elimina atraso de até 5 min e expectativa incorreta |
| P0 | geração, coalescência, backoff e timers deduplicados | evita estado antigo, excesso de requests e corrida |
| P0 | frescor/origem/estado em todo card | torna o dado confiável e interpretável |
| P1 | watchers locais + reconciliação 2/10/30 s | entrega percepção de tempo real |
| P1 | modelo v2 com valores absolutos e histórico curto | melhora cards e permite delta/tendência |
| P1 | corrigir atividade do Grok e leitura incremental do Antigravity | reduz atraso e I/O |
| P1 | otimizar Cursor e Kiro | reduz latência e pressão sobre APIs |
| P2 | previsão de esgotamento com confiança | melhora planejamento, sem comprometer precisão |
| P2 | painel de diagnóstico | facilita suporte e manutenção |
| P2 | internacionalização integral | resolve inconsistência de idioma |

## 16. Decisão recomendada

Adotar a arquitetura híbrida, começando pelo scheduler e pelo modelo de estado antes dos watchers. Apenas reduzir o intervalo global de polling não resolve o problema: aumenta consumo e risco de rate limit, não reage bem a eventos locais e continua sem comunicar idade ou confiabilidade do dado.

O primeiro marco deve entregar: cache imediato, estado/frescor no card, refresh ativo coerente, proteção de concorrência e reconciliação pós-atividade. Com essa base, cada provider pode ganhar observação local gradualmente sem alterar o contrato visual ou comprometer os demais.

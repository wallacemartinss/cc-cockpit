# cc-cockpit

Painel de uso do Claude Code para o GNOME: indicador na bandeja com anel de
consumo + dashboard local + resumo no terminal.

Tudo é lido do que o próprio Claude Code já grava em `~/.claude`. Não fala com
a rede, não lê credenciais, não manda nada para lugar nenhum.

## O que ele mostra

| | |
|---|---|
| **Bloco de 5h** | quanto foi consumido na janela de rate limit atual, quanto falta para resetar, ritmo por hora, projeção até o fim do bloco e quanto tempo até bater o teto de referência |
| **7 dias / hoje / mês** | consumo agregado, com % contra o seu próprio pico histórico |
| **Sessões abertas** | cada instância viva do CLI: nome, projeto, `busy`/`idle`, uptime, RAM, pid e quanto aquela sessão já consumiu |
| **Projetos** | ranking por consumo, do histórico inteiro |
| **Blocos, dias e horas** | séries temporais para ver quando você gasta |
| **Composição de tokens** | input / output / cache write 5m / cache write 1h / cache read, com taxa de acerto de cache |
| **Modelos, effort e subagentes** | onde o consumo realmente vai |

O consumo é medido em **USD equivalente API**: quanto aquelas mensagens
custariam pela API avulsa. Em plano Pro/Max nada disso é cobrado — o número
serve como unidade de peso do consumo e mostra o quanto o plano rende.

## Instalação

```bash
sudo apt install gir1.2-ayatanaappindicator3-0.1   # só para a bandeja
./install.sh
cc-cockpit          # bandeja + dashboard em background
```

O `install.sh` cria `~/.local/bin/cc-cockpit` e registra o autostart do GNOME.

```bash
cc-cockpit report          # resumo no terminal
cc-cockpit serve --open    # só o dashboard (http://127.0.0.1:8765)
cc-cockpit json            # tudo em JSON, para script
cc-cockpit collect         # só incorpora os transcripts novos
cc-cockpit config          # caminho e conteúdo da configuração
```

## Configuração

`~/.config/cc-cockpit/config.json`:

```jsonc
{
  "block_hours": 5,
  "limits": { "block_usd": null, "week_usd": null },  // null = auto-calibra
  "tray_metric": "block",        // block | week | today | none
  "tray_show_cost": true,
  "refresh_seconds": 20,
  "plan_monthly_usd": null,      // ex.: 200 -> mostra quantas vezes o plano se pagou
  "plan_name": "",
  "usd_brl": null,               // ex.: 5.4 -> exibe R$ ao lado do USD
  "dashboard_port": 8765,
  "warn_pct": 70,
  "critical_pct": 90
}
```

**Sobre os tetos.** A Anthropic não publica o limite exato do plano em tokens,
e ele não aparece em lugar nenhum no disco. Com `limits` em `null`, o cc-cockpit
usa como referência o **seu maior bloco e sua maior semana já registrados** — ou
seja, o % responde "este bloco está pesado comparado ao meu pior?". Se você
descobrir seu teto real (por exemplo, anotando o consumo quando o CLI avisar
que você bateu o limite), coloque o valor em `limits` e o % passa a ser absoluto.

## Como funciona

```
~/.claude/projects/**/*.jsonl   transcripts (usage por request)
~/.claude/sessions/*.json       uma entrada por CLI vivo  ─┐
                                                            ├─> cockpit/
        ~/.local/share/cc-cockpit/events.ndjson  <──────────┘
```

- `collector.py` lê cada transcript **a partir do último offset**, então o
  refresh custa ~30 ms mesmo com 190 MB de histórico.
- Os eventos vão para um NDJSON próprio. Isso importa: o Claude Code **poda os
  transcripts em ~30 dias**, e o cc-cockpit passa a guardar o histórico completo
  a partir da primeira coleta.
- Dedup por `message.id:requestId`, então retomar sessão não conta duas vezes.
- `sessions.py` valida cada pid contra `/proc` **e** compara o `starttime`, para
  não confundir um pid reciclado com uma sessão viva.
- Preços em `pricing.py`, com cache write 5m a 1,25× e 1h a 2× o input, e cache
  read a 0,1× (0,025× no Fable 5.1). O transcript separa os dois TTLs de cache
  write — o cálculo usa essa separação em vez de assumir tudo em 5m.

## Limitações honestas

- O % do plano é relativo ao seu próprio histórico enquanto `limits` for `null`.
- Modelos lançados depois desta versão caem no preço da família (`opus`,
  `sonnet`, `haiku`, `fable`) até serem adicionados em `pricing.py`.
- Linhas `<synthetic>` são respostas geradas localmente pelo CLI: aparecem na
  contagem de requests e custam zero.

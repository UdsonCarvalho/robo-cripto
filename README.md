# Robô Cripto (spot, sem alavancagem)

Robô em Python para operar BTC/USDT (ou outro par) na OKX ou Binance, no mercado à vista.
Ele só compra e vende o que tem. Não usa alavancagem e não opera vendido.

> Não é recomendação de investimento. Comece **sempre** por backtest → paper → testnet.
> Só use dinheiro real com um valor que você aceite perder.

## Arquivos

| Arquivo | O que faz |
|---|---|
| `config.yaml` | Todos os parâmetros: modo, par, estratégia, risco |
| `estrategia.py` | Indicadores e regras de entrada/saída |
| `risco.py` | Tamanho da posição, limite diário, teto de capital |
| `backtest.py` | Testa a estratégia do config.yaml no histórico |
| `otimizar.py` | Testa dezenas de configurações (treino 2022–23, validação 2024–hoje) e gera `config_sugerida.yaml` |
| `bot.py` | O robô que roda ao vivo (paper / testnet / real) |
| `.env.example` | Modelo para suas chaves de API |
| `armazenamento.py` | Guarda estado/operações em arquivos locais ou no Supabase |
| `painel/` | Painel (usado no PC pelo `dashboard.py` e online pelo GitHub Pages) |
| `nuvem/supabase.sql` | Cria as tabelas no Supabase |
| `.github/workflows/` | Agenda o robô e publica o painel no GitHub |

## Estratégias (versão 2)

- **rompimento**: compra quando o preço rompe a máxima dos últimos N candles, a favor da tendência (acima da EMA 200), e sai ao perder a mínima dos últimos M candles.
- **ema_cruzamento**: compra no cruzamento da média rápida sobre a lenta, a favor da tendência, com filtro de RSI.
- Nas duas: stop inicial por ATR, alvo opcional e **stop móvel (trailing)** opcional.

Nenhuma delas é garantia de lucro. Use o `otimizar.py` para ver qual, se alguma, funciona.

## Passo 0 – Otimizar (versão 2)

```
py -3.13 otimizar.py
```

Escolhe as melhores configurações em 2022–23 e confere se continuam boas em 2024–hoje.
Só a que passa nos dois períodos é salva em `config_sugerida.yaml`. Para usá-la:

```
copy /Y config_sugerida.yaml config.yaml
```

## Gestão de risco (já embutida)

- Risco máximo de 1% do capital por operação.
- Exposição máxima de 25% do capital numa posição.
- Perdeu 3% no dia → não abre mais nada até o dia seguinte (UTC).
- Máximo de 3 operações por dia.
- `capital_maximo`: teto de USDT que o robô pode usar (use no modo real).
- Arquivo `PARAR` na pasta → o robô para de abrir operações (continua cuidando do stop da posição aberta).

## Instalação

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## Rodar na nuvem de graça (GitHub Actions + Supabase)

O robô roda sozinho a cada 15 min no GitHub, guarda tudo no Supabase e o painel fica num link
(GitHub Pages) que abre no celular. Seu PC pode ficar desligado. Os dois planos são grátis e não
pedem cartão.

1. **Supabase** → SQL Editor → cole `nuvem/supabase.sql` → Run.
2. **Supabase** → Project Settings → API Keys: anote a chave **publishable/anon** (pública) e a
   **secret/service_role** (secreta).
3. **GitHub** → New repository `robo-cripto` (Public) → "uploading an existing file" → arraste
   todo o conteúdo desta pasta (inclusive a pasta `.github`). Nunca envie o arquivo `.env`.
4. **GitHub** → Settings → Secrets and variables → Actions → New repository secret:
   `SUPABASE_URL` (https://SEU-PROJETO.supabase.co) e `SUPABASE_SERVICE_KEY` (a chave secreta).
5. **GitHub** → edite `painel/config.js` e cole a chave pública em `anonKey`.
6. **GitHub** → Settings → Pages → Source: **GitHub Actions**.
7. **GitHub** → Actions → habilite os workflows → "Robo (a cada 15 min)" → Run workflow.
   Painel: `https://SEU-USUARIO.github.io/robo-cripto/`

Observações: o GitHub pode atrasar o agendamento alguns minutos; em repositório sem commits por
60 dias ele pausa o agendamento (é só reativar na aba Actions). Para pausar o robô, mude
`pausado: true` no `config.yaml` pelo próprio site do GitHub.

## Ligar o robô + painel no PC (2 cliques)

Dê dois cliques em **`iniciar_robo.bat`**. Abrem duas janelas (robô e dashboard) e o
painel aparece no navegador em http://127.0.0.1:8050. Para desligar, feche as janelas.

## Passo 1 – Backtest

```bash
py -3.13 backtest.py --inicio 2022-01-01 --fim 2023-12-31
py -3.13 backtest.py --inicio 2024-01-01            # período diferente
```

O que olhar:
- **Fator de lucro** acima de 1,2 e **pelo menos 30 trades**.
- **Drawdown** (maior queda) que você aguentaria emocionalmente.
- Comparar com **"só comprar e segurar"**. Se o robô rende menos que isso, ele não está agregando nada.

**Cuidado com overfitting:** se você ficar ajustando os parâmetros até o resultado ficar lindo
num período, ele quase sempre piora no futuro. Ajuste num período (ex.: 2022–2023) e
confirme em outro que você **não** usou (ex.: 2024–hoje).

## Passo 2 – Paper (simulado com preço real)

No `config.yaml`: `modo: paper`. Não precisa de chave.

```bash
py -3.13 bot.py
```

Deixe rodando alguns dias ou semanas. Os trades vão para `logs/trades_paper.csv`.

## Conta DEMO da OKX (acompanhar pelo app)

1. Crie conta na OKX e ative o **Demo Trading** (no app: perfil → Demo Trading).
2. **Dentro do modo demo**, vá em API → Criar chave. Escolha permissão **Trade** (sem saque)
   e defina uma passphrase.
3. `copy .env.example .env` e preencha `DEMO_API_KEY`, `DEMO_API_SECRET` e `DEMO_API_PASSWORD`.
4. No `config.yaml`: `exchange: okx` e `modo: demo`. Ligue com `iniciar_robo.bat`.
5. As ordens do robô aparecem no Demo Trading da OKX (app e site), com dinheiro virtual.

## Passo 3 – Testnet da Binance

1. Entre em https://testnet.binance.vision, faça login com o GitHub e gere uma chave (HMAC).
2. Coloque a chave e o segredo em `TESTNET_API_KEY` e `TESTNET_API_SECRET` no `.env`.
3. No `config.yaml`: `modo: testnet`.
4. `py -3.13 bot.py`

Aqui as ordens são enviadas de verdade, mas com dinheiro fictício. Serve para validar a
integração (precisão de quantidade, mínimo de ordem, taxas).

## Passo 4 – Real (só depois de passar pelos anteriores)

Checklist:
- [ ] Backtest positivo em **dois períodos diferentes**.
- [ ] Paper/testnet por algumas semanas com resultado parecido com o backtest.
- [ ] Chave de API **só com spot trading**, **sem permissão de saque**, **restrita ao IP** do servidor.
- [ ] `capital_maximo` definido com um valor pequeno.
- [ ] `CONFIRMAR_REAL=SIM` no `.env` e `modo: real` no config.

## Rodando 24 horas (VPS Linux)

O stop é vigiado pelo próprio robô: **se ele cair, a posição fica sem proteção**.
Num VPS, use `tmux` para testar rápido ou um serviço `systemd` com `Restart=always`.

```bash
tmux new -s robo
source venv/bin/activate && py -3.13 bot.py
# Ctrl+B depois D para sair sem parar o robô; "tmux attach -t robo" para voltar
```

O estado (posição aberta, limites do dia) fica salvo em `estado_<modo>.json`, então o
robô continua de onde parou ao reiniciar.

## Impostos

Lucro com cripto tem regras de Imposto de Renda no Brasil, e as regras para
exchange estrangeira são diferentes das de exchange nacional. Antes de operar de
verdade, confirme as regras atuais com um contador.

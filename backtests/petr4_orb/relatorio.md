# Backtest simulado · PETR4 · rompimento da faixa de abertura (5 min)

**Modo simulado. Nenhuma ordem foi enviada para conta real** (o script não usa corretora nem chaves).

- Período testado: 01/09/2026 a 27/11/2026 (60 pregões com dados)
- Fonte: Yahoo Finance via yfinance, ticker PETR4.SA, candles de 5 min, horário de São Paulo. O Yahoo só guarda 60 dias de candles de 5 min, então esse é o período máximo disponível.
- Sessão regular usada: 10:00 até 16:55 (o último candle é o das 16:50; o leilão de fechamento fica de fora).
- Custos: taxas B3 de day trade 0,023% por lado (emolumentos + liquidação), corretagem R$ 0,00, slippage de R$ 0,01 por ação na entrada e nas saídas a mercado (stop e fim da sessão). Alvo sai sem slippage. IR não incluído.
- Limite de perda diário: R$ 2,00. Quantidade em ações inteiras (mercado fracionário, PETR4F).

**Dados faltando:** 21 dia(s) sem os 3 candles de abertura completos: 08/09 (faltam candles de abertura (82 candles na sessão)); 28/09 (faltam candles de abertura (82 candles na sessão)); 01/10 (faltam candles de abertura (82 candles na sessão)); 02/10 (faltam candles de abertura (81 candles na sessão)); 05/10 (faltam candles de abertura (82 candles na sessão)); 08/10 (faltam candles de abertura (82 candles na sessão)); 13/10 (faltam candles de abertura (82 candles na sessão)); 21/10 (faltam candles de abertura (82 candles na sessão)); 26/10 (faltam candles de abertura (73 candles na sessão)); 27/10 (faltam candles de abertura (82 candles na sessão)); 30/10 (faltam candles de abertura (82 candles na sessão)); 03/11 (faltam candles de abertura (82 candles na sessão)); 04/11 (faltam candles de abertura (82 candles na sessão)); 05/11 (faltam candles de abertura (82 candles na sessão)); 09/11 (faltam candles de abertura (82 candles na sessão)); 11/11 (faltam candles de abertura (82 candles na sessão)); 13/11 (faltam candles de abertura (82 candles na sessão)); 16/11 (faltam candles de abertura (73 candles na sessão)); 23/11 (faltam candles de abertura (82 candles na sessão)); 26/11 (faltam candles de abertura (82 candles na sessão)); 27/11 (faltam candles de abertura (34 candles na sessão))

## Operações

| Data | Entrada | Preço entrada | Stop | Alvo | Qtd | Saída | Preço saída | Motivo | Resultado |
|---|---|---:|---:|---:|---:|---|---:|---|---:|
| 01/09 | 10:35 | 46,07 | 45,70 | 46,81 | 4 | 14:30 | 46,81 | alvo | R$ 2,87 |
| 02/09 | 10:35 | 46,90 | 46,59 | 47,52 | 5 | 12:00 | 47,52 | alvo | R$ 2,99 |
| 03/09 | 10:25 | 49,16 | 48,93 | 49,62 | 7 | 10:25 | 48,92 | stop | R$ -1,84 |
| 10/09 | 10:25 | 49,21 | 49,14 | 49,35 | 19 | 10:30 | 49,13 | stop | R$ -1,95 |
| 11/09 | 11:55 | 48,66 | 48,49 | 49,00 | 9 | 13:25 | 49,00 | alvo | R$ 2,86 |
| 15/09 | 10:35 | 49,52 | 49,20 | 50,16 | 5 | 12:00 | 50,16 | alvo | R$ 3,09 |
| 17/09 | 10:20 | 48,33 | 48,21 | 48,57 | 13 | 10:30 | 48,20 | stop | R$ -1,98 |
| 18/09 | 10:45 | 48,67 | 48,43 | 49,15 | 7 | 11:20 | 48,42 | stop | R$ -1,91 |
| 21/09 | 11:45 | 48,34 | 48,27 | 48,48 | 19 | 11:45 | 48,26 | stop | R$ -1,94 |
| 22/09 | 10:45 | 47,80 | 47,54 | 48,32 | 6 | 13:00 | 48,32 | alvo | R$ 2,99 |
| 23/09 | 10:25 | 49,45 | 49,27 | 49,81 | 9 | 10:30 | 49,26 | stop | R$ -1,91 |
| 29/09 | 10:50 | 48,53 | 48,24 | 49,11 | 6 | 16:50 | 49,02 | fim da sessão | R$ 2,81 |
| 30/09 | 15:00 | 49,95 | 49,87 | 50,11 | 17 | 15:15 | 49,86 | stop | R$ -1,92 |
| 07/10 | 14:15 | 54,37 | 54,26 | 54,59 | 13 | 14:15 | 54,25 | stop | R$ -1,88 |
| 09/10 | 10:45 | 55,66 | 55,50 | 55,98 | 10 | 10:55 | 55,98 | alvo | R$ 2,94 |
| 14/10 | 10:25 | 57,48 | 57,20 | 58,04 | 6 | 16:50 | 57,99 | fim da sessão | R$ 2,90 |
| 15/10 | 10:25 | 57,94 | 57,73 | 58,36 | 8 | 10:30 | 57,72 | stop | R$ -1,97 |
| 16/10 | 10:20 | 57,98 | 57,74 | 58,46 | 7 | 11:05 | 57,35 | stop (gap: saiu na abertura) | R$ -4,60 ⚠ passou do limite |
| 22/10 | 10:25 | 58,58 | 58,33 | 59,08 | 6 | 10:30 | 58,32 | stop | R$ -1,72 |
| 23/10 | 10:25 | 58,60 | 58,50 | 58,80 | 14 | 10:30 | 58,80 | alvo | R$ 2,42 |
| 29/10 | 10:35 | 52,48 | 52,02 | 53,40 | 4 | 11:55 | 52,01 | stop | R$ -1,98 |
| 10/11 | 11:55 | 45,33 | 45,02 | 45,95 | 5 | 15:00 | 45,01 | stop | R$ -1,70 |
| 12/11 | 10:25 | 44,12 | 43,95 | 44,46 | 9 | 11:05 | 43,94 | stop | R$ -1,80 |
| 24/11 | 10:45 | 41,54 | 41,28 | 42,06 | 6 | 10:50 | 42,06 | alvo | R$ 3,00 |
| 25/11 | 10:35 | 41,17 | 40,93 | 41,65 | 7 | 10:50 | 40,92 | stop | R$ -1,88 |

## Resumo

- Operações: 25
- Taxa de acerto: 40,00%
- Resultado total após custos: R$ -2,12
- Resultado médio por operação: R$ -0,08
- Maior queda do saldo (drawdown): R$ 11,35
- Sinais pulados por passar do limite de risco: 0
- Outros dias pulados: 1 (abertura do candle de entrada na máxima da faixa ou abaixo, ou sem candle para entrar)
- Operações que perderam mais que o limite (gap/slippage): 1

## Sinais pulados

| Data | Horário | Motivo |
|---|---|---|
| 24/09 | 11:15 | abertura 50,05 ≤ máxima da faixa 50,05 |

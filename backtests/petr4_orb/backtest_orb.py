"""Backtest SIMULADO de rompimento da faixa de abertura (ORB) em PETR4, candles de 5 min.

NÃO envia ordens: este script não importa nenhuma corretora nem lê chaves.
Ele só baixa candles históricos públicos e simula as regras.

Regras (pedido do Silva):
 1. Faixa de abertura = máxima e mínima dos 3 primeiros candles de 5 min da sessão regular (10:00, 10:05, 10:10).
 2. Depois da faixa, espera o 1º candle que FECHA acima da máxima da faixa. Só compra.
 3. Entra na abertura do candle seguinte. Se essa abertura <= máxima da faixa, pula o dia.
 4. Stop = mínima do candle de rompimento. Alvo = entrada + 2 x (entrada - stop).
 5. No máximo 1 operação por dia. Sem alvo/stop, sai no fechamento do último candle da sessão regular.
Risco:
 - Limite diário R$ 2,00. Quantidade inteira = floor(2,00 / perda estimada por ação no stop, com taxas e slippage).
   Se nem 1 ação couber, pula e registra o motivo.
 - Gap além do stop: sai no primeiro preço disponível (abertura do candle) e registra se passou do limite.
 - Stop e alvo no mesmo candle: conta o stop.
"""
import math
import sys
from datetime import time

import pandas as pd
import yfinance as yf

TICKER = "PETR4.SA"
LIMITE_DIA = 2.00          # R$
TAXA = 0.00023             # 0,023% por lado: emolumentos (0,005%) + liquidação (0,018%) de day trade na B3, pessoa física
CORRETAGEM = 0.00          # R$ por ordem (corretoras de corretagem zero)
SLIPPAGE = 0.01            # R$ por ação na entrada e nas saídas a mercado (stop e fim da sessão) = 1 tick
INICIO_SESSAO = time(10, 0)
FIM_SESSAO = time(16, 55)  # leilão de fechamento começa 16:55; último candle negociado é o das 16:50


def baixar():
    df = yf.Ticker(TICKER).history(period="60d", interval="5m", auto_adjust=False, actions=False)
    if df.empty:
        sys.exit("Sem dados: o Yahoo Finance não devolveu candles de 5 min para PETR4.SA.")
    df.index = df.index.tz_convert("America/Sao_Paulo")
    return df[["Open", "High", "Low", "Close", "Volume"]]


def perda_por_acao(entrada, stop):
    """Perda estimada por ação se bater o stop, com slippage e taxas nas duas pontas."""
    fill_e = entrada
    fill_s = stop - SLIPPAGE
    return (fill_e - fill_s) + fill_e * TAXA + fill_s * TAXA


def simular(df):
    ops, pulos, faltas = [], [], []
    for dia, d in df.groupby(df.index.date):
        d = d[(d.index.time >= INICIO_SESSAO) & (d.index.time < FIM_SESSAO)]
        if len(d) < 4 or [t.strftime("%H:%M") for t in d.index[:3].time] != ["10:00", "10:05", "10:10"]:
            faltas.append((dia, f"faltam candles de abertura ({len(d)} candles na sessão)"))
            continue
        fx_max, fx_min = d.iloc[:3]["High"].max(), d.iloc[:3]["Low"].min()
        resto = d.iloc[3:]
        rompeu = resto[resto["Close"] > fx_max]
        if rompeu.empty:
            continue
        i_rb = d.index.get_loc(rompeu.index[0])
        if i_rb + 1 >= len(d):
            pulos.append((dia, rompeu.index[0], "rompimento no último candle da sessão, sem candle para entrar"))
            continue
        rb = d.iloc[i_rb]
        ent_c = d.iloc[i_rb + 1]
        if ent_c["Open"] <= fx_max:
            pulos.append((dia, d.index[i_rb + 1], f"abertura {ent_c['Open']:.2f} <= máxima da faixa {fx_max:.2f}"))
            continue
        entrada = ent_c["Open"] + SLIPPAGE
        stop = rb["Low"]
        alvo = entrada + 2 * (entrada - stop)
        risco_acao = perda_por_acao(entrada, stop)
        qtd = math.floor(LIMITE_DIA / risco_acao) if risco_acao > 0 else 0
        if qtd < 1:
            pulos.append((dia, d.index[i_rb + 1], f"1 ação arriscaria R$ {risco_acao:.2f} (> R$ {LIMITE_DIA:.2f})"))
            continue
        saida, motivo, hora_s = None, None, None
        for ts, c in d.iloc[i_rb + 1:].iterrows():
            o, h, l = c["Open"], c["High"], c["Low"]
            if ts != d.index[i_rb + 1] and o <= stop:          # gap abaixo do stop
                saida, motivo, hora_s = o - SLIPPAGE, "stop (gap: saiu na abertura)", ts
                break
            if ts != d.index[i_rb + 1] and o >= alvo:          # gap acima do alvo
                saida, motivo, hora_s = o, "alvo (gap: saiu na abertura)", ts
                break
            bateu_stop, bateu_alvo = l <= stop, h >= alvo
            if bateu_stop:                                       # se os dois no mesmo candle, conta o stop
                saida, motivo, hora_s = stop - SLIPPAGE, "stop" + (" (stop e alvo no mesmo candle)" if bateu_alvo else ""), ts
                break
            if bateu_alvo:
                saida, motivo, hora_s = alvo, "alvo", ts
                break
        if saida is None:
            ult = d.iloc[-1]
            saida, motivo, hora_s = ult["Close"] - SLIPPAGE, "fim da sessão", d.index[-1]
        custos = qtd * (entrada + saida) * TAXA + 2 * CORRETAGEM
        res = qtd * (saida - entrada) - custos
        ops.append(dict(data=str(dia), entrada_hora=d.index[i_rb + 1].strftime("%H:%M"), entrada=entrada, stop=stop, alvo=alvo,
                        qtd=qtd, saida_hora=hora_s.strftime("%H:%M"), saida=saida, motivo=motivo, custos=custos, resultado=res,
                        risco_estimado=qtd * risco_acao, passou_limite=res < -LIMITE_DIA - 1e-9))
    return ops, pulos, faltas


def relatorio(df, ops, pulos, faltas):
    br = lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    p = lambda v: f"{v:.2f}".replace(".", ",")
    L = []
    L.append("# Backtest simulado · PETR4 · rompimento da faixa de abertura (5 min)\n")
    L.append("**Modo simulado. Nenhuma ordem foi enviada para conta real** (o script não usa corretora nem chaves).\n")
    dias = sorted(set(df.index.date))
    L.append(f"- Período testado: {dias[0]:%d/%m/%Y} a {dias[-1]:%d/%m/%Y} ({len(dias)} pregões com dados)")
    L.append(f"- Fonte: Yahoo Finance via yfinance, ticker {TICKER}, candles de 5 min, horário de São Paulo. "
             "O Yahoo só guarda 60 dias de candles de 5 min, então esse é o período máximo disponível.")
    L.append(f"- Sessão regular usada: 10:00 até 16:55 (o último candle é o das 16:50; o leilão de fechamento fica de fora).")
    L.append(f"- Custos: taxas B3 de day trade {str(round(TAXA*100,3)).replace(".",",")}% por lado (emolumentos + liquidação), corretagem {br(CORRETAGEM)}, "
             f"slippage de {br(SLIPPAGE)} por ação na entrada e nas saídas a mercado (stop e fim da sessão). Alvo sai sem slippage. IR não incluído.")
    L.append(f"- Limite de perda diário: {br(LIMITE_DIA)}. Quantidade em ações inteiras (mercado fracionário, PETR4F).\n")
    if faltas:
        L.append(f"**Dados faltando:** {len(faltas)} dia(s) sem os 3 candles de abertura completos: " + "; ".join(f"{d:%d/%m} ({m})" for d, m in faltas) + "\n")
    L.append("## Operações\n")
    if ops:
        L.append("| Data | Entrada | Preço entrada | Stop | Alvo | Qtd | Saída | Preço saída | Motivo | Resultado |")
        L.append("|---|---|---:|---:|---:|---:|---|---:|---|---:|")
        for o in ops:
            L.append(f"| {o['data'][8:10]}/{o['data'][5:7]} | {o['entrada_hora']} | {p(o['entrada'])} | {p(o['stop'])} | {p(o['alvo'])} | {o['qtd']} | {o['saida_hora']} | {p(o['saida'])} | {o['motivo']} | {br(o['resultado'])}{' ⚠ passou do limite' if o['passou_limite'] else ''} |")
    else:
        L.append("Zero operações.")
    r = [o["resultado"] for o in ops]
    acc, pico, dd = 0.0, 0.0, 0.0
    for v in r:
        acc += v; pico = max(pico, acc); dd = max(dd, pico - acc)
    risco_pulos = [x for x in pulos if "arriscaria" in x[2]]
    L.append("\n## Resumo\n")
    L.append(f"- Operações: {len(ops)}")
    L.append(f"- Taxa de acerto: {p(100*sum(v>0 for v in r)/len(r)) + '%' if r else '–'}")
    L.append(f"- Resultado total após custos: {br(sum(r))}")
    L.append(f"- Resultado médio por operação: {br(sum(r)/len(r)) if r else '–'}")
    L.append(f"- Maior queda do saldo (drawdown): {br(dd)}")
    L.append(f"- Sinais pulados por passar do limite de risco: {len(risco_pulos)}")
    L.append(f"- Outros dias pulados: {len(pulos)-len(risco_pulos)} (abertura do candle de entrada na máxima da faixa ou abaixo, ou sem candle para entrar)")
    L.append(f"- Operações que perderam mais que o limite (gap/slippage): {sum(o['passou_limite'] for o in ops)}")
    if pulos:
        L.append("\n## Sinais pulados\n")
        L.append("| Data | Horário | Motivo |\n|---|---|---|")
        for d, ts, m in pulos:
            L.append(f"| {d:%d/%m} | {ts:%H:%M} | {m} |")
    return "\n".join(L)


if __name__ == "__main__":
    df = baixar()
    ops, pulos, faltas = simular(df)
    txt = relatorio(df, ops, pulos, faltas)
    print(txt)
    with open("relatorio.md", "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    pd.DataFrame(ops).to_csv("operacoes.csv", index=False)
    df.to_csv("candles_petr4_5m.csv")

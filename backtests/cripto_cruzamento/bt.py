"""Backtest SIMULADO da estratégia de expediente: cruzamento de EMAs em velas de 15 min,
R$ 1 por operação, entradas só das 9h às 18h (Brasília) com pausa de almoço 12h-13h,
posição encerrada às 18h. Usa o mesmo estrategia.calcular_indicadores do robô.
Não envia ordens. Dados: OKX (BTC/USDT e ETH/USDT, 15 min), porque a Foxbit tem pouco histórico pela API."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import ccxt, pandas as pd
from estrategia import calcular_indicadores, niveis_saida

TAXA, SLIP, VALOR, DIAS = 0.005, 0.001, 1.0, 90
EST = dict(tipo="ema_cruzamento", ema_rapida=9, ema_lenta=21, ema_tendencia=200, atr_periodo=14,
           stop_atr=2.0, alvo_atr=0, trailing_atr=0, rsi_periodo=14, rsi_min=45, rsi_max=70,
           saida_cruzamento=True, rompimento_entrada=0, mm_periodo=0)

def baixar(par):
    ex = ccxt.okx({"enableRateLimit": True})
    since = ex.milliseconds() - (DIAS + 4) * 86400000
    out = []
    while True:
        lote = ex.fetch_ohlcv(par, "15m", since=since, limit=300)
        if not lote: break
        out += lote; since = lote[-1][0] + 900000
        if since > ex.milliseconds() - 900000: break
    df = pd.DataFrame(out, columns=["t","open","high","low","close","volume"]).drop_duplicates("t")
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/Sao_Paulo")
    return df.drop(columns="t").astype(float)

def fase(ts):
    h = ts.hour + ts.minute / 60
    if h < 9 or h >= 18: return "fechado"
    if 12 <= h < 13: return "almoco"
    return "aberto"

def rodar(par):
    df = calcular_indicadores(baixar(par), EST)
    df = df[df.index >= df.index[-1] - pd.Timedelta(days=DIAS)]
    ops, pos = [], None
    idx = df.index
    for i in range(len(df) - 1):
        c, prox = df.iloc[i], df.iloc[i + 1]
        fim_do_candle = idx[i] + pd.Timedelta(minutes=15)
        if pos:
            # stop dentro do próximo candle
            if prox["open"] <= pos["stop"]:
                sai, mot = prox["open"] * (1 - SLIP), "stop (gap)"
            elif prox["low"] <= pos["stop"]:
                sai, mot = pos["stop"] * (1 - SLIP), "stop"
            elif fase(fim_do_candle) == "fechado":
                sai, mot = prox["open"] * (1 - SLIP), "fim do expediente"
            elif c["saida"]:
                sai, mot = prox["open"] * (1 - SLIP), "cruzou para baixo"
            else:
                continue
            res = pos["qtd"] * sai * (1 - TAXA) - VALOR
            ops.append(dict(par=par, entrada=pos["t"], saida=idx[i + 1], preco_e=pos["p"], preco_s=sai, motivo=mot, resultado=res))
            pos = None
            continue
        if c["entrada"] and fase(fim_do_candle) == "aberto":
            p = prox["open"] * (1 + SLIP)
            stop, _ = niveis_saida(p, c["atr"], EST)
            pos = dict(t=idx[i + 1], p=p, stop=stop, qtd=VALOR * (1 - TAXA) / p)
    return pd.DataFrame(ops), df.index[0], df.index[-1]

linhas = ["# Backtest simulado · cruzamento de EMAs 9×21 (15 min) · expediente 9h–18h com almoço\n",
          "**Simulação: nenhuma ordem enviada.** R$ 1 por operação, taxa 0,5% por lado (Foxbit) e slippage de 0,1% por lado.",
          "Filtros do robô: preço acima da EMA 200 e RSI entre 45 e 70 para comprar; sai no cruzamento para baixo, no stop de 2× ATR ou às 18h.",
          "Dados: OKX BTC/USDT e ETH/USDT em velas de 15 min (a Foxbit tem pouco histórico pela API). O resultado em % vale para BTC/BRL e ETH/BRL.\n"]
tudo = []
for par in ["BTC/USDT", "ETH/USDT"]:
    ops, a, b = rodar(par)
    tudo.append(ops)
    r = ops["resultado"] if len(ops) else pd.Series(dtype=float)
    eq = r.cumsum(); dd = (eq.cummax().clip(lower=0) - eq).max() if len(r) else 0
    linhas.append(f"## {par} · {a:%d/%m/%Y} a {b:%d/%m/%Y}\n")
    linhas.append(f"- Operações: {len(r)} · acertos: {(r>0).mean()*100:.0f}% · resultado: R$ {r.sum():.2f} · média por operação: R$ {r.mean() if len(r) else 0:.4f} ({(r.mean() if len(r) else 0)*100:.2f}% do valor)")
    linhas.append(f"- Maior ganho: R$ {r.max() if len(r) else 0:.3f} · maior perda: R$ {r.min() if len(r) else 0:.3f} · maior queda do saldo: R$ {dd:.2f}")
    if len(ops):
        m = ops.groupby("motivo")["resultado"].agg(["count", "sum"])
        linhas.append("- Saídas: " + "; ".join(f"{k}: {int(v['count'])} (R$ {v['sum']:.2f})" for k, v in m.iterrows()))
        sem_taxa = ((ops["preco_s"] / ops["preco_e"] - 1) * 1).mean() * 100
        linhas.append(f"- Média por operação **antes** das taxas e slippage: {sem_taxa:.2f}% (as taxas custam ~1,2% por operação)\n")
txt = "\n".join(linhas)
print(txt)
open("relatorio.md", "w", encoding="utf-8").write(txt + "\n")
pd.concat(tudo).to_csv("operacoes.csv", index=False)

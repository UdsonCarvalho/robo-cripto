"""Backtest: testa a estratégia do config.yaml no histórico, com taxa, slippage e as mesmas regras de risco do bot.

Uso:
  py -3.13 backtest.py --inicio 2022-01-01 --fim 2023-12-31
  py -3.13 backtest.py --inicio 2024-01-01
  py -3.13 backtest.py --csv meus_dados.csv

Regras de simulação (conservadoras):
  - sinal no fechamento do candle -> executa na ABERTURA do próximo;
  - se stop e alvo caírem no mesmo candle, considera que bateu o STOP;
  - gap abaixo do stop executa na abertura (pior que o stop);
  - o trailing stop só é atualizado no fechamento do candle.
"""
import argparse
import os

import numpy as np
import pandas as pd

from configuracao import PASTA, carregar_config
from estrategia import aquecimento, atualizar_trailing, calcular_indicadores, niveis_saida
from risco import pode_operar_hoje, tamanho_posicao


# ================================================================ dados
def segundos_timeframe(tf):
    import ccxt
    return ccxt.Exchange.parse_timeframe(tf)


def baixar_dados(exchange_id, par, tf, inicio, fim=None):
    import ccxt

    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    os.makedirs(os.path.join(PASTA, "dados"), exist_ok=True)
    cache = os.path.join(PASTA, "dados", f"{par.replace('/', '')}_{tf}_{inicio}_{fim or 'hoje'}.csv")
    if fim and os.path.exists(cache):
        return ler_csv(cache)

    print(f"Baixando {par} {tf} desde {inicio}...")
    since = ex.parse8601(f"{inicio}T00:00:00Z")
    limite_ms = ex.parse8601(f"{fim}T23:59:59Z") if fim else None
    passo = ex.parse_timeframe(tf) * 1000
    agora_ms = ex.milliseconds()
    linhas = []
    while True:
        lote = ex.fetch_ohlcv(par, tf, since=since, limit=1000)  # cada corretora devolve até seu limite
        if not lote or lote[-1][0] < since:
            break
        linhas += lote
        since = lote[-1][0] + passo
        if since > agora_ms or (limite_ms and since > limite_ms):
            break
    df = pd.DataFrame(linhas, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("timestamp")
    if limite_ms:
        df = df[df["timestamp"] <= limite_ms]
    df.to_csv(cache, index=False)
    return ler_csv(cache)


def ler_csv(caminho):
    df = pd.read_csv(caminho)
    ts = df["timestamp"]
    if pd.api.types.is_numeric_dtype(ts):
        df["timestamp"] = pd.to_datetime(ts, unit="s" if ts.max() < 1e11 else "ms", utc=True)
    else:
        df["timestamp"] = pd.to_datetime(ts, utc=True)
    return df.set_index("timestamp").sort_index()[["open", "high", "low", "close", "volume"]].astype(float)


def fonte_dados(cfg):
    """Corretora/par de onde vem o histórico (pode ser diferente da corretora onde o robô opera)."""
    d = cfg.get("dados") or {}
    return d.get("exchange", cfg["exchange"]), d.get("par", cfg["par"])


def inicio_com_aquecimento(inicio, tf, cfg_est):
    """Data a partir da qual baixar, para os indicadores já estarem prontos em `inicio`."""
    folga = pd.Timedelta(seconds=segundos_timeframe(tf) * (aquecimento(cfg_est) + 5))
    return (pd.Timestamp(inicio) - folga).strftime("%Y-%m-%d")


def recortar_periodo(df, cfg_est, inicio, fim=None):
    """Recorta o período mantendo antes dele os candles de aquecimento."""
    i0 = df.index.searchsorted(pd.Timestamp(inicio, tz="UTC"))
    i1 = df.index.searchsorted(pd.Timestamp(fim, tz="UTC") + pd.Timedelta(days=1)) if fim else len(df)
    return df.iloc[max(0, i0 - aquecimento(cfg_est)):i1]


# ================================================================ simulação
def rodar_backtest(df, cfg):
    est, risco = cfg["estrategia"], cfg["risco"]
    taxa, slip = cfg["custos"]["taxa"], cfg["custos"]["slippage"]
    df = calcular_indicadores(df, est)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a, ent, sai = df["atr"].to_numpy(), df["entrada"].to_numpy(), df["saida"].to_numpy()
    idx, dias = df.index, df.index.floor("D")

    caixa = float(cfg["backtest"]["saldo_inicial"])
    pos, pendente, atr_sinal = None, None, None
    trades, curva = [], np.full(len(df), np.nan)
    custos = 0.0
    dia_atual, capital_inicio_dia, pnl_dia, trades_dia = None, caixa, 0.0, 0

    def fechar(preco, i, motivo, com_slip):
        nonlocal caixa, pos, pnl_dia, custos
        bruto = pos["qtd"] * preco
        receita = bruto * (1 - taxa)
        custos += bruto * taxa + (bruto * slip if com_slip else 0)
        caixa += receita
        lucro = receita - pos["custo"]
        pnl_dia += lucro
        trades.append({"entrada_em": pos["quando"], "saida_em": idx[i], "preco_entrada": pos["entrada"],
                       "preco_saida": preco, "qtd": pos["qtd"], "lucro": lucro,
                       "lucro_pct": lucro / pos["custo"], "motivo": motivo})
        pos = None

    inicio = aquecimento(est)
    for i in range(inicio, len(df)):
        if dias[i] != dia_atual:
            dia_atual = dias[i]
            capital_inicio_dia = caixa + (pos["qtd"] * o[i] if pos else 0)
            pnl_dia, trades_dia = 0.0, 0

        # 1) ordens pendentes executam na abertura
        if pendente == "compra" and pos is None:
            preco = o[i] * (1 + slip)
            stop, alvo = niveis_saida(preco, atr_sinal, est)
            qtd = tamanho_posicao(caixa, preco, stop, risco)
            custo = qtd * preco * (1 + taxa)
            if qtd > 0 and custo <= caixa:
                caixa -= custo
                custos += qtd * preco * taxa + qtd * o[i] * slip
                pos = {"qtd": qtd, "entrada": preco, "stop": stop, "alvo": alvo, "custo": custo, "quando": idx[i]}
                trades_dia += 1
        elif pendente == "venda" and pos is not None:
            fechar(o[i] * (1 - slip), i, "sinal de saída", True)
        pendente = None

        # 2) stop / alvo dentro do candle
        if pos is not None:
            if l[i] <= pos["stop"]:
                fechar(min(pos["stop"], o[i]) * (1 - slip), i, "stop", True)
            elif pos["alvo"] is not None and h[i] >= pos["alvo"]:
                fechar(max(pos["alvo"], o[i]), i, "alvo", False)

        # 3) fechamento do candle: trailing e sinais
        if pos is not None:
            pos["stop"] = atualizar_trailing(pos["stop"], c[i], a[i], est)
        if i < len(df) - 1:
            if pos is not None and sai[i]:
                pendente = "venda"
            elif pos is None and ent[i]:
                ok, _ = pode_operar_hoje(pnl_dia, capital_inicio_dia, trades_dia, risco)
                if ok:
                    pendente, atr_sinal = "compra", a[i]

        curva[i] = caixa + (pos["qtd"] * c[i] if pos else 0)

    if pos is not None:
        fechar(c[-1] * (1 - slip), len(df) - 1, "fim do teste", True)
        curva[-1] = caixa

    curva = pd.Series(curva[inicio:], index=idx[inicio:], name="patrimonio")
    return pd.DataFrame(trades), curva, df, custos


# ================================================================ métricas
def metricas(trades, curva, df_ind, custos, cfg):
    inicial = float(cfg["backtest"]["saldo_inicial"])
    final = float(curva.iloc[-1])
    i0 = aquecimento(cfg["estrategia"])
    m = {
        "retorno": final / inicial - 1,
        "retorno_sem_custos": (final + custos) / inicial - 1,
        "buy_hold": df_ind["close"].iloc[-1] / df_ind["close"].iloc[i0] - 1,
        "drawdown": float((curva / curva.cummax() - 1).min()),
        "custos": custos,
        "trades": len(trades),
        "acerto": 0.0, "fator_lucro": 0.0, "ganho_medio": 0.0, "perda_media": 0.0,
        "inicio": curva.index[0], "fim": curva.index[-1], "final": final, "inicial": inicial,
    }
    if len(trades):
        g, p = trades[trades["lucro"] > 0], trades[trades["lucro"] <= 0]
        soma_p = abs(p["lucro"].sum())
        m.update(acerto=len(g) / len(trades),
                 fator_lucro=g["lucro"].sum() / soma_p if soma_p > 0 else float("inf"),
                 ganho_medio=g["lucro"].mean() if len(g) else 0.0,
                 perda_media=p["lucro"].mean() if len(p) else 0.0)
    return m


def relatorio(m, trades, cfg):
    e = cfg["estrategia"]
    print("\n" + "=" * 56)
    print(f" BACKTEST {fonte_dados(cfg)[1]} {cfg['timeframe']} ({e['tipo']})  {m['inicio']:%Y-%m-%d} -> {m['fim']:%Y-%m-%d}")
    print("=" * 56)
    print(f" Saldo inicial ........ {m['inicial']:,.2f}")
    print(f" Saldo final .......... {m['final']:,.2f}  ({m['retorno']:+.2%})")
    print(f" Sem taxas/slippage ... {m['retorno_sem_custos']:+.2%}   (custos pagos: {m['custos']:,.2f})")
    print(f" Só comprar e segurar . {m['buy_hold']:+.2%}")
    print(f" Maior queda (drawdown) {m['drawdown']:.2%}")
    print(f" Trades ............... {m['trades']}")
    if m["trades"]:
        print(f" Taxa de acerto ....... {m['acerto']:.1%}")
        print(f" Ganho médio .......... {m['ganho_medio']:,.2f}")
        print(f" Perda média .......... {m['perda_media']:,.2f}")
        print(f" Fator de lucro ....... {m['fator_lucro']:.2f}   (abaixo de 1 = perde dinheiro)")
        print(" Saídas por motivo:", trades["motivo"].value_counts().to_dict())
    print("=" * 56)
    if m["trades"] < 30:
        print(" ATENÇÃO: menos de 30 trades. Amostra pequena, resultado pouco confiável.")
    if m["retorno"] < m["buy_hold"]:
        print(" ATENÇÃO: rendeu menos que só comprar e segurar.")


def main():
    p = argparse.ArgumentParser(description="Backtest do robô")
    p.add_argument("--inicio")
    p.add_argument("--fim")
    p.add_argument("--csv")
    args = p.parse_args()

    cfg = carregar_config()
    est = cfg["estrategia"]
    inicio = args.inicio or cfg["backtest"]["inicio"]
    if args.csv:
        df = ler_csv(args.csv)
    else:
        ex_dados, par_dados = fonte_dados(cfg)
        df = baixar_dados(ex_dados, par_dados, cfg["timeframe"],
                          inicio_com_aquecimento(inicio, cfg["timeframe"], est), args.fim)
        df = recortar_periodo(df, est, inicio, args.fim)
    if len(df) <= aquecimento(est) + 10:
        raise SystemExit("Poucos candles para testar. Aumente o período.")

    trades, curva, df_ind, custos = rodar_backtest(df, cfg)
    relatorio(metricas(trades, curva, df_ind, custos, cfg), trades, cfg)

    pasta = os.path.join(PASTA, "resultados")
    os.makedirs(pasta, exist_ok=True)
    trades.to_csv(os.path.join(pasta, "trades.csv"), index=False)
    curva.to_csv(os.path.join(pasta, "patrimonio.csv"))
    print(f"\nDetalhes salvos em {pasta}")


if __name__ == "__main__":
    main()

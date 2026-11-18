"""Estratégias do robô (tudo calculado só com candles FECHADOS, sem olhar o futuro).

tipo: ema_cruzamento
  Compra quando a EMA rápida cruza a lenta para cima, preço acima da EMA de tendência
  e RSI entre rsi_min e rsi_max. Pode sair no cruzamento para baixo (saida_cruzamento).

tipo: rompimento  (seguidor de tendência clássico, "canal de Donchian")
  Compra quando o fechamento rompe a máxima dos últimos N candles, com preço acima da
  EMA de tendência. Sai quando o fechamento perde a mínima dos últimos M candles.

Nos dois: stop inicial = entrada - stop_atr x ATR; alvo opcional (alvo_atr = 0 desliga);
trailing stop opcional (trailing_atr = 0 desliga) que sobe junto com o preço e nunca desce.
"""
import numpy as np
import pandas as pd


def ema(serie, periodo):
    return serie.ewm(span=periodo, adjust=False).mean()


def rsi(fechamento, periodo=14):
    delta = fechamento.diff()
    ganho = delta.clip(lower=0).ewm(alpha=1 / periodo, adjust=False).mean()
    perda = (-delta.clip(upper=0)).ewm(alpha=1 / periodo, adjust=False).mean()
    rs = ganho / perda.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def atr(df, periodo=14):
    tr = pd.concat(
        [df["high"] - df["low"],
         (df["high"] - df["close"].shift()).abs(),
         (df["low"] - df["close"].shift()).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / periodo, adjust=False).mean()


def aquecimento(cfg_est):
    """Candles descartados no início até os indicadores estabilizarem."""
    return max(cfg_est["ema_tendencia"], cfg_est.get("rompimento_entrada", 0)) + 50


def calcular_indicadores(df, cfg_est):
    """Calcula indicadores e as colunas booleanas 'entrada' e 'saida'."""
    df = df.copy()
    df["ema_tendencia"] = ema(df["close"], cfg_est["ema_tendencia"])
    df["atr"] = atr(df, cfg_est["atr_periodo"])
    tendencia_ok = df["close"] > df["ema_tendencia"]

    if cfg_est["tipo"] == "ema_cruzamento":
        df["ema_rapida"] = ema(df["close"], cfg_est["ema_rapida"])
        df["ema_lenta"] = ema(df["close"], cfg_est["ema_lenta"])
        df["rsi"] = rsi(df["close"], cfg_est["rsi_periodo"])
        acima = df["ema_rapida"] > df["ema_lenta"]
        acima_antes = acima.shift(1, fill_value=False)
        cruzou_cima = acima & ~acima_antes
        cruzou_baixo = ~acima & acima_antes
        rsi_ok = df["rsi"].between(cfg_est["rsi_min"], cfg_est["rsi_max"])
        df["entrada"] = cruzou_cima & tendencia_ok & rsi_ok
        df["saida"] = cruzou_baixo if cfg_est.get("saida_cruzamento", True) else False

    elif cfg_est["tipo"] == "rompimento":
        maxima = df["high"].rolling(cfg_est["rompimento_entrada"]).max().shift(1)
        minima = df["low"].rolling(cfg_est["rompimento_saida"]).min().shift(1)
        df["canal_max"], df["canal_min"] = maxima, minima
        df["entrada"] = (df["close"] > maxima) & tendencia_ok
        df["saida"] = df["close"] < minima
    else:
        raise ValueError(f"tipo de estratégia desconhecido: {cfg_est['tipo']}")

    df["entrada"] = df["entrada"].fillna(False).astype(bool)
    df["saida"] = pd.Series(df["saida"], index=df.index).fillna(False).astype(bool)
    return df


def niveis_saida(preco_entrada, valor_atr, cfg_est):
    """Retorna (stop, alvo). alvo = None quando alvo_atr = 0."""
    stop = preco_entrada - cfg_est["stop_atr"] * valor_atr
    alvo = preco_entrada + cfg_est["alvo_atr"] * valor_atr if cfg_est["alvo_atr"] > 0 else None
    return stop, alvo


def atualizar_trailing(stop_atual, fechamento, valor_atr, cfg_est):
    """Sobe o stop conforme o preço sobe (nunca desce). Chamado no fechamento do candle."""
    k = cfg_est.get("trailing_atr", 0)
    if k <= 0:
        return stop_atual
    return max(stop_atual, fechamento - k * valor_atr)

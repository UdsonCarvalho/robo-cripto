"""Testa várias configurações de forma honesta, em 3 períodos:

  1. TREINO (2022-2023): ordena as combinações pelas melhores.
  2. VALIDAÇÃO (2024-2025): confere num período que NÃO foi usado para escolher.
  3. TESTE 2026 (até hoje): período final, só para conferir; mercado de baixa.

Só é "aprovada" a configuração que ganha dinheiro no TREINO e na VALIDAÇÃO.
A melhor aprovada é salva em config_sugerida.yaml, pronta para o modo paper.

Uso:  py -3.13 otimizar.py
"""
import copy
import itertools
import os

import pandas as pd
import yaml

from backtest import baixar_dados, fonte_dados, metricas, recortar_periodo, rodar_backtest
from configuracao import PASTA, carregar_config

TREINO = ("2022-01-01", "2023-12-31")
VALIDACAO = ("2024-01-01", "2025-12-31")
TESTE = ("2026-01-01", None)
BAIXAR_DESDE = "2021-01-01"   # sobra para o aquecimento dos indicadores
TIMEFRAMES = ["4h", "1d"]
MIN_TRADES = 5
PF_MINIMO = 1.1


def grade():
    for tf in TIMEFRAMES:
        for (rap, len_), saida, trail, stop, alvo in itertools.product(
                [(9, 21), (20, 50)], [True, False], [0, 3], [2, 3], [0, 4]):
            if not saida and trail == 0 and alvo == 0:
                continue  # sem nenhuma saída além do stop inicial
            yield tf, {"tipo": "ema_cruzamento", "ema_rapida": rap, "ema_lenta": len_,
                       "saida_cruzamento": saida, "trailing_atr": trail, "stop_atr": stop, "alvo_atr": alvo}
        for n, m, trail, stop in itertools.product([20, 55], [10, 20], [0, 3], [2, 3]):
            yield tf, {"tipo": "rompimento", "rompimento_entrada": n, "rompimento_saida": m,
                       "trailing_atr": trail, "stop_atr": stop, "alvo_atr": 0}
        for per, (compra, venda), stop in itertools.product([2, 14], [(None, 60), (None, 70)], [2, 3]):
            compra = 10 if per == 2 else 30
            yield tf, {"tipo": "reversao_rsi", "rsi_periodo": per, "rsi_compra": compra, "rsi_venda": venda,
                       "trailing_atr": 0, "stop_atr": stop, "alvo_atr": 0}
    for n, banda, stop in itertools.product([50, 100, 150, 200], [0.0, 0.02, 0.04], [4, 6]):
        yield "1d", {"tipo": "tendencia_mm", "mm_periodo": n, "mm_banda": banda,
                     "trailing_atr": 0, "stop_atr": stop, "alvo_atr": 0}


def descrever(tf, p):
    if p["tipo"] == "ema_cruzamento":
        s = f"{tf} EMA {p['ema_rapida']}/{p['ema_lenta']}"
        s += " saiCruz" if p["saida_cruzamento"] else ""
    elif p["tipo"] == "tendencia_mm":
        s = f"{tf} MM{p['mm_periodo']} banda{p['mm_banda']:.0%}"
    elif p["tipo"] == "reversao_rsi":
        s = f"{tf} RSI{p['rsi_periodo']}<{p['rsi_compra']}>{p['rsi_venda']}"
    else:
        s = f"{tf} Romp {p['rompimento_entrada']}/{p['rompimento_saida']}"
    s += f" stop{p['stop_atr']}"
    s += f" trail{p['trailing_atr']}" if p["trailing_atr"] else ""
    s += f" alvo{p['alvo_atr']}" if p["alvo_atr"] else ""
    return s


def avaliar(dados, cfg, periodo):
    sub = recortar_periodo(dados, cfg["estrategia"], *periodo)
    trades, curva, df_ind, custos = rodar_backtest(sub, cfg)
    return metricas(trades, curva, df_ind, custos, cfg)


def main():
    base = carregar_config()
    ex_dados, par_dados = fonte_dados(base)
    print(f"Histórico: {par_dados} da {ex_dados} | custos: taxa {base['custos']['taxa']:.2%} + slippage {base['custos']['slippage']:.2%} por ordem")
    dados = {tf: baixar_dados(ex_dados, par_dados, tf, BAIXAR_DESDE) for tf in TIMEFRAMES}

    combinacoes = list(grade())
    print(f"\nTestando {len(combinacoes)} configurações em 2 períodos...")
    linhas = []
    for n, (tf, params) in enumerate(combinacoes, 1):
        cfg = copy.deepcopy(base)
        cfg["timeframe"] = tf
        cfg["estrategia"].update(params)
        t, v, x = avaliar(dados[tf], cfg, TREINO), avaliar(dados[tf], cfg, VALIDACAO), avaliar(dados[tf], cfg, TESTE)
        linhas.append({
            "config": descrever(tf, params), "tf": tf, "params": params,
            "treino_ret": t["retorno"], "treino_pf": t["fator_lucro"], "treino_trades": t["trades"], "treino_dd": t["drawdown"],
            "valid_ret": v["retorno"], "valid_pf": v["fator_lucro"], "valid_trades": v["trades"], "valid_dd": v["drawdown"],
            "teste_ret": x["retorno"], "teste_trades": x["trades"], "teste_dd": x["drawdown"],
            "bh_treino": t["buy_hold"], "bh_valid": v["buy_hold"], "bh_teste": x["buy_hold"],
        })
        if n % 20 == 0:
            print(f"  {n}/{len(combinacoes)}")

    res = pd.DataFrame(linhas)
    res["aprovada"] = ((res["treino_pf"] >= PF_MINIMO) & (res["valid_pf"] >= PF_MINIMO)
                       & (res["treino_ret"] > 0) & (res["valid_ret"] > 0)
                       & (res["treino_trades"] >= MIN_TRADES) & (res["valid_trades"] >= MIN_TRADES))
    ranking = res[res["treino_trades"] >= MIN_TRADES].sort_values(["treino_pf", "treino_ret"], ascending=False)

    os.makedirs(os.path.join(PASTA, "resultados"), exist_ok=True)
    res.drop(columns="params").to_csv(os.path.join(PASTA, "resultados", "otimizacao.csv"), index=False)

    bh_t, bh_v, bh_x = res["bh_treino"].iloc[0], res["bh_valid"].iloc[0], res["bh_teste"].iloc[0]
    def tabela(titulo, df):
        print(f"\n{titulo}")
        print(f"{'configuração':<34}{'trein%':>8}{'PF':>6}{'n':>4} |{'valid%':>8}{'PF':>6}{'n':>4}{'DD':>7} |{'2026%':>8}{'n':>4}{'DD':>7}  ok")
        for _, r in df.iterrows():
            print(f"{r['config']:<34}{r['treino_ret']:>+8.1%}{r['treino_pf']:>6.2f}{r['treino_trades']:>4} |"
                  f"{r['valid_ret']:>+8.1%}{r['valid_pf']:>6.2f}{r['valid_trades']:>4}{r['valid_dd']:>7.1%} |"
                  f"{r['teste_ret']:>+8.1%}{r['teste_trades']:>4}{r['teste_dd']:>7.1%}  {'SIM' if r['aprovada'] else '-'}")
    print(f"\nSó comprar e segurar: treino {bh_t:+.1%} | validação {bh_v:+.1%} | 2026 {bh_x:+.1%}")
    tabela("TOP 15 NO TREINO (2022-23), com validação (2024-25) e 2026:", ranking.head(15))
    for tipo in ("tendencia_mm", "reversao_rsi"):
        sub = ranking[ranking["params"].apply(lambda p: p["tipo"] == tipo)].head(5)
        if len(sub):
            tabela(f"MELHORES DO TIPO {tipo}:", sub)

    aprovadas = ranking[ranking["aprovada"]]
    print(f"\nAprovadas (lucro e PF >= {PF_MINIMO} nos dois períodos): {len(aprovadas)} de {len(res)}")
    if aprovadas.empty:
        print("Nenhuma configuração passou nos dois períodos. NÃO recomendo operar nenhuma delas.")
        return

    melhor = aprovadas.iloc[0]
    sugerida = copy.deepcopy(base)
    sugerida["modo"] = "paper"
    sugerida["timeframe"] = melhor["tf"]
    sugerida["estrategia"].update(melhor["params"])
    with open(os.path.join(PASTA, "config_sugerida.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(sugerida, f, allow_unicode=True, sort_keys=False)
    print(f"\nMelhor aprovada: {melhor['config']}")
    print("Salva em config_sugerida.yaml. Para usar no modo demo, troque o config.yaml por ela.")
    if min(melhor["treino_trades"], melhor["valid_trades"]) < 30:
        print("ATENÇÃO: poucos trades. Pode ter passado por sorte; o teste no modo paper é obrigatório.")
    if melhor["valid_ret"] < bh_v:
        print("Obs.: mesmo aprovada, rendeu menos que só comprar e segurar na validação "
              "(mas com bem menos dinheiro exposto e menor queda).")


if __name__ == "__main__":
    main()

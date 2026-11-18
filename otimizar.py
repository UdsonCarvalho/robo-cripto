"""Testa várias configurações de forma honesta:

  1. TREINO (2022-2023): roda todas as combinações e ordena pelas melhores.
  2. VALIDAÇÃO (2024-hoje): confere se as melhores do treino continuam boas
     num período que NÃO foi usado para escolher. É isso que evita o overfitting.

Só é "aprovada" a configuração que ganha dinheiro nos DOIS períodos.
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
VALIDACAO = ("2024-01-01", None)
BAIXAR_DESDE = "2021-01-01"   # sobra para o aquecimento dos indicadores
TIMEFRAMES = ["4h", "1d"]
MIN_TRADES = 10
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


def descrever(tf, p):
    if p["tipo"] == "ema_cruzamento":
        s = f"{tf} EMA {p['ema_rapida']}/{p['ema_lenta']}"
        s += " saiCruz" if p["saida_cruzamento"] else ""
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
        t, v = avaliar(dados[tf], cfg, TREINO), avaliar(dados[tf], cfg, VALIDACAO)
        linhas.append({
            "config": descrever(tf, params), "tf": tf, "params": params,
            "treino_ret": t["retorno"], "treino_pf": t["fator_lucro"], "treino_trades": t["trades"], "treino_dd": t["drawdown"],
            "valid_ret": v["retorno"], "valid_pf": v["fator_lucro"], "valid_trades": v["trades"], "valid_dd": v["drawdown"],
            "bh_treino": t["buy_hold"], "bh_valid": v["buy_hold"],
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

    bh_t, bh_v = res["bh_treino"].iloc[0], res["bh_valid"].iloc[0]
    print("\nTOP 15 NO TREINO (2022-23) e como foram na VALIDAÇÃO (2024-hoje)")
    print(f"Só comprar e segurar: treino {bh_t:+.1%} | validação {bh_v:+.1%}\n")
    print(f"{'configuração':<36}{'trein%':>8}{'PF':>6}{'n':>5}  |{'valid%':>8}{'PF':>6}{'n':>5}{'DD':>8}  ok")
    for _, r in ranking.head(15).iterrows():
        print(f"{r['config']:<36}{r['treino_ret']:>+8.1%}{r['treino_pf']:>6.2f}{r['treino_trades']:>5}  |"
              f"{r['valid_ret']:>+8.1%}{r['valid_pf']:>6.2f}{r['valid_trades']:>5}{r['valid_dd']:>8.1%}  "
              f"{'SIM' if r['aprovada'] else '-'}")

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

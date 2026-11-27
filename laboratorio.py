"""Laboratório de estratégias: testadores em turnos de 8 h, 24 h por dia (Lia; Davi, Bia e Léo; Nina).

SÓ TESTA. Não importa corretora com chave, não lê API_KEY e não envia ordem nenhuma.

Cada execução (o GitHub Actions roda de hora em hora; cada testador do turno testa 90, então das 8h às 16h a equipe de 3 testa 270 por hora) pega o próximo lote da grade de
configurações, testa de forma honesta e grava o placar no Supabase para a sala mostrar:

  TREINO (2022-2023)     -> período usado para ranquear
  VALIDAÇÃO (2024-2025)  -> período que não foi usado para escolher
  TESTE (2026 até hoje)  -> conferência final

"Aprovada" = lucro e fator de lucro >= 1,1 no treino E na validação, com trades suficientes.
"Forte"    = aprovada + lucro também em 2026 + pelo menos 30 operações no total.
Testar milhares de combinações faz algumas passarem por sorte; por isso a sala mostra
quantas foram testadas e nenhuma vai para o dinheiro real sem passar antes pelo modo paper.

Uso local:  py -3.13 laboratorio.py --lote 50
"""
import argparse
import copy
import itertools
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from armazenamento import ArmazenamentoSupabase
from backtest import baixar_dados, metricas, recortar_periodo, rodar_backtest
from configuracao import carregar_config

TREINO = ("2022-01-01", "2023-12-31")
VALIDACAO = ("2024-01-01", "2025-12-31")
TESTE = ("2026-01-01", None)
BAIXAR_DESDE = "2021-06-01"
PARES = ["BTC/USD", "ETH/USD"]          # histórico longo da Bitstamp (a Foxbit tem pouco pela API)
TIMEFRAMES = ["1h", "4h", "1d"]
MIN_TRADES, PF_MINIMO = 8, 1.1
TURNOS = [  # (início, fim, equipe) no horário de Brasília; cada testador roda um lote de 90 por hora
    (0, 8, ["Lia"]),
    (8, 16, ["Davi", "Bia", "Léo"]),
    (16, 24, ["Nina"]),
]
POR_TESTADOR = 90
ATUAL = ("1d", {"tipo": "tendencia_mm", "mm_periodo": 50, "mm_banda": 0.02, "trailing_atr": 0, "stop_atr": 6.0, "alvo_atr": 0})


def grade():
    """Todas as combinações que o laboratório testa (por par e timeframe)."""
    for par, tf in itertools.product(PARES, TIMEFRAMES):
        for (rap, len_), saida, trail, stop, alvo in itertools.product(
                [(5, 13), (9, 21), (12, 26), (20, 50), (50, 200)], [True, False], [0, 2, 4], [1.5, 2, 3], [0, 3, 6]):
            if not saida and trail == 0 and alvo == 0:
                continue
            yield par, tf, {"tipo": "ema_cruzamento", "ema_rapida": rap, "ema_lenta": len_, "saida_cruzamento": saida,
                            "trailing_atr": trail, "stop_atr": stop, "alvo_atr": alvo}
        for n, m, trail, stop in itertools.product([10, 20, 55, 100], [5, 10, 20], [0, 3], [2, 3]):
            if m >= n:
                continue
            yield par, tf, {"tipo": "rompimento", "rompimento_entrada": n, "rompimento_saida": m,
                            "trailing_atr": trail, "stop_atr": stop, "alvo_atr": 0}
        for per, venda, stop in itertools.product([2, 14], [60, 70, 80], [2, 3]):
            yield par, tf, {"tipo": "reversao_rsi", "rsi_periodo": per, "rsi_compra": 10 if per == 2 else 30,
                            "rsi_venda": venda, "trailing_atr": 0, "stop_atr": stop, "alvo_atr": 0}
        if tf != "1h":
            for n, banda, stop in itertools.product([20, 50, 100, 150, 200], [0.0, 0.01, 0.02, 0.04], [3, 4, 6]):
                yield par, tf, {"tipo": "tendencia_mm", "mm_periodo": n, "mm_banda": banda,
                                "trailing_atr": 0, "stop_atr": stop, "alvo_atr": 0}


def descrever(tf, p):
    t = p["tipo"]
    if t == "ema_cruzamento":
        s = f"EMA {p['ema_rapida']}×{p['ema_lenta']}" + (" sai no cruzamento" if p["saida_cruzamento"] else "")
    elif t == "tendencia_mm":
        s = f"Média {p['mm_periodo']} faixa {p['mm_banda']:.0%}"
    elif t == "reversao_rsi":
        s = f"RSI {p['rsi_periodo']} <{p['rsi_compra']} >{p['rsi_venda']}"
    else:
        s = f"Rompimento {p['rompimento_entrada']}/{p['rompimento_saida']}"
    s += f" · stop {p['stop_atr']}×ATR"
    s += f" · trailing {p['trailing_atr']}" if p.get("trailing_atr") else ""
    s += f" · alvo {p['alvo_atr']}×ATR" if p.get("alvo_atr") else ""
    return f"{tf} · {s}"


def turno_agora(agora):
    h = agora.astimezone(ZoneInfo("America/Sao_Paulo")).hour
    for ini, fim, equipe in TURNOS:
        if ini <= h < fim:
            return {"nome": ", ".join(equipe[:-1]) + " e " + equipe[-1] if len(equipe) > 1 else equipe[0],
                    "equipe": equipe, "inicio": ini, "fim": fim}
    return {"nome": TURNOS[0][2][0], "equipe": TURNOS[0][2], "inicio": 0, "fim": 8}


def avaliar(dados, cfg, periodo):
    sub = recortar_periodo(dados, cfg["estrategia"], *periodo)
    if len(sub) < 50:
        return None
    trades, curva, df_ind, custos = rodar_backtest(sub, cfg)
    m = metricas(trades, curva, df_ind, custos, cfg)
    pf = m["fator_lucro"]
    return {"ret": round(float(m["retorno"]), 4), "pf": round(float(min(pf, 99.0)), 3), "n": int(m["trades"]),
            "dd": round(float(m["drawdown"]), 4), "acerto": round(float(m["acerto"]), 3), "bh": round(float(m["buy_hold"]), 4)}


def testar(base, dados, par, tf, params):
    cfg = copy.deepcopy(base)
    cfg["timeframe"] = tf
    cfg["estrategia"].update(params)
    t, v, x = (avaliar(dados[(par, tf)], cfg, p) for p in (TREINO, VALIDACAO, TESTE))
    ok = bool(t and v and t["ret"] > 0 and v["ret"] > 0 and t["pf"] >= PF_MINIMO and v["pf"] >= PF_MINIMO
              and t["n"] >= MIN_TRADES and v["n"] >= MIN_TRADES)
    forte = bool(ok and x and x["ret"] > 0 and (t["n"] + v["n"] + x["n"]) >= 30)
    return {"id": f"{par}|{tf}|{sorted(params.items())}", "par": par, "tf": tf, "tipo": params["tipo"],
            "nome": descrever(tf, params), "treino": t, "valid": v, "teste": x, "aprovada": ok, "forte": forte}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lote", type=int, default=int(os.getenv("LAB_LOTE", "0")), help="0 = 90 por testador do turno")
    args = ap.parse_args()

    base = carregar_config()
    base["risco"]["valor_fixo_reais"] = 0  # o backtest usa o dimensionamento por risco, igual ao otimizador
    url, chave = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    arm = ArmazenamentoSupabase(url, chave, "lab") if url and chave else None

    todas = list(grade())
    estado = (arm.ler("estado") if arm else None) or {"cursor": 0, "rodada": 1, "testes_feitos": 0}
    resultados = (arm.ler("resultados") if arm else None) or {}

    agora = datetime.now(timezone.utc)
    turno = turno_agora(agora)
    tamanho = args.lote or POR_TESTADOR * len(turno["equipe"])
    inicio = estado["cursor"] % len(todas)
    lote = [todas[(inicio + i) % len(todas)] for i in range(min(tamanho, len(todas)))]
    print(f"Turno de {turno['nome']} ({turno['inicio']:02d}h-{turno['fim']:02d}h) | rodada {estado['rodada']} | "
          f"lote {inicio + 1}-{inicio + len(lote)} de {len(todas)}")

    precisa = sorted({(p, tf) for p, tf, _ in lote} | {(PARES[0], ATUAL[0])})
    dados = {}
    for par, tf in precisa:
        dados[(par, tf)] = baixar_dados("bitstamp", par, tf, BAIXAR_DESDE)

    t0, novos = time.time(), []
    for par, tf, params in lote:
        try:
            r = testar(base, dados, par, tf, params)
        except Exception as e:
            print(f"  erro em {par} {descrever(tf, params)}: {e}")
            continue
        r["testada_em"], r["por"] = agora.isoformat(), turno["nome"]
        resultados[r["id"]] = r
        novos.append(r)
    atual = testar(base, dados, PARES[0], *ATUAL)
    print(f"Lote testado em {time.time() - t0:.0f} s: {len(novos)} configurações, "
          f"{sum(r['aprovada'] for r in novos)} aprovadas, {sum(r['forte'] for r in novos)} fortes")

    fim = inicio + len(lote)
    estado["cursor"] = fim % len(todas)
    if fim >= len(todas):
        estado["rodada"] += 1
    estado["testes_feitos"] += len(novos)

    lista = list(resultados.values())
    aprov = [r for r in lista if r["aprovada"]]
    chave_rank = lambda r: (r["forte"], min(r["treino"]["pf"], r["valid"]["pf"]), r["valid"]["ret"])
    ranking = sorted(aprov, key=chave_rank, reverse=True)[:12]
    por_tipo = {}
    for r in lista:
        d = por_tipo.setdefault(r["tipo"], {"testadas": 0, "aprovadas": 0})
        d["testadas"] += 1
        d["aprovadas"] += int(r["aprovada"])
    melhor_lote = max(novos, key=lambda r: (r["aprovada"], r["valid"]["ret"] if r["valid"] else -9), default=None)

    status = {
        "atualizado_em": agora.isoformat(), "turno": turno,
        "turnos": [{"equipe": e, "inicio": i, "fim": f} for i, f, e in TURNOS],
        "grade_total": len(todas), "testadas_unicas": len(lista), "testes_feitos": estado["testes_feitos"],
        "rodada": estado["rodada"], "cursor": estado["cursor"],
        "aprovadas": len(aprov), "fortes": sum(r["forte"] for r in lista),
        "por_tipo": por_tipo, "ranking": ranking, "atual": atual,
        "ultimo_lote": {"por": turno["nome"], "quando": agora.isoformat(), "qtd": len(novos),
                        "aprovadas": sum(r["aprovada"] for r in novos), "melhor": melhor_lote},
        "regras": {"treino": TREINO, "validacao": VALIDACAO, "teste": [TESTE[0], "hoje"], "pf_minimo": PF_MINIMO,
                   "min_trades": MIN_TRADES, "taxa": base["custos"]["taxa"], "slippage": base["custos"]["slippage"],
                   "dados": "Bitstamp BTC/USD e ETH/USD"},
    }
    if arm:
        arm.gravar("resultados", resultados)
        arm.gravar("estado", estado)
        arm.gravar("status", status)
        print("Placar gravado no Supabase (lab:status).")
    else:
        print("Sem SUPABASE_URL/SUPABASE_SERVICE_KEY: só mostrei na tela.")
    for r in ranking[:5]:
        print(f"  {'FORTE' if r['forte'] else 'aprov.'} {r['par']} {r['nome']} | valid {r['valid']['ret']:+.1%} PF {r['valid']['pf']}")


if __name__ == "__main__":
    main()

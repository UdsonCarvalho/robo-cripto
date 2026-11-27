"""Conselho da Agência COINS: decide quais estratégias do laboratório chegam até o Silva.

Funil (nada muda no dinheiro real sem o clique do Silva):
  1. CANDIDATA   - estratégia "forte" do laboratório que bate a estratégia atual na validação
  2. SIMULAÇÃO   - roda pelo menos DIAS_SIMULACAO dias em dados novos (depois de ter sido escolhida)
  3. CONSELHO    - 3 conselheiros votam: Rita (risco), Edu (estatística) e Duda (advogado do diabo)
  4. AGUARDANDO  - só com 3 votos "sim"; aparece na sala com o botão "Aprovar"
  5. APROVADA    - o Silva aprovou: este script troca a estratégia no config.yaml (o workflow faz o commit)
     REPROVADA   - algum conselheiro votou "não" ou o Silva reprovou

Com ANTHROPIC_API_KEY cadastrada, cada conselheiro escreve o parecer com o Claude (no máximo
MAX_CHAMADAS_IA por execução). Sem a chave, os votos e os textos saem só das regras.
Este script não usa as chaves da corretora e não envia ordens.
"""
import ast
import copy
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

import yaml

from armazenamento import ArmazenamentoSupabase
from backtest import baixar_dados, metricas, recortar_periodo, rodar_backtest
from configuracao import PASTA, carregar_config
from laboratorio import ATUAL, BAIXAR_DESDE, PARES

DIAS_SIMULACAO = 14
MAX_EM_SIMULACAO = 3
MAX_CHAMADAS_IA = 6
MODELO_IA = os.getenv("CONSELHO_MODELO", "claude-sonnet-5-5")
CONSELHEIROS = {
    "Rita": "risco: maior queda do saldo e perda nos piores momentos",
    "Edu": "estatística: se há operações suficientes e se o resultado não parece sorte",
    "Duda": "advogado do diabo: procura o ponto fraco e testa no outro mercado",
}


def agora():
    return datetime.now(timezone.utc)


def params_de(r):
    """Reconstrói os parâmetros a partir do id 'par|tf|[(chave, valor), ...]' gravado pelo laboratório."""
    _, tf, itens = r["id"].split("|", 2)
    return tf, dict(ast.literal_eval(itens))


def avaliar_desde(base, dados, tf, params, desde):
    cfg = copy.deepcopy(base)
    cfg["timeframe"] = tf
    cfg["estrategia"].update(params)
    sub = recortar_periodo(dados, cfg["estrategia"], desde, None)
    trades, curva, df_ind, custos = rodar_backtest(sub, cfg)
    m = metricas(trades, curva, df_ind, custos, cfg)
    return {"ret": round(float(m["retorno"]), 4), "pf": round(float(min(m["fator_lucro"], 99)), 3),
            "n": int(m["trades"]), "dd": round(float(m["drawdown"]), 4), "bh": round(float(m["buy_hold"]), 4)}


def votos_por_regra(c, atual, outro_par):
    t, v, x, s = c["treino"], c["valid"], c.get("teste") or {}, c.get("simulacao") or {}
    total = t["n"] + v["n"] + x.get("n", 0)
    risco_ok = v["dd"] >= -0.25 and v["dd"] >= (atual["valid"]["dd"] - 0.05) and s.get("dd", 0) >= -0.10
    est_ok = total >= 30 and min(t["pf"], v["pf"]) >= 1.2 and x.get("ret", 0) > 0
    diabo_ok = (outro_par is not None and outro_par["ret"] > 0) and s.get("ret", 0) > -0.03 and v["pf"] > atual["valid"]["pf"]
    return {
        "Rita": (risco_ok, f"Maior queda na validação {v['dd']:+.1%} (atual {atual['valid']['dd']:+.1%}); na simulação {s.get('dd', 0):+.1%}. "
                           + ("Dentro do limite de 25% e não pior que a atual." if risco_ok else "Queda grande demais ou pior que a estratégia atual.")),
        "Edu": (est_ok, f"{total} operações no total; PF treino {t['pf']:.2f} e validação {v['pf']:.2f}; 2026 {x.get('ret', 0):+.1%}. "
                        + ("Amostra e consistência suficientes." if est_ok else "Poucas operações, PF baixo ou prejuízo em 2026: pode ser sorte.")),
        "Duda": (diabo_ok, ("No outro mercado: " + (f"{outro_par['ret']:+.1%} na validação. " if outro_par else "sem dados. "))
                           + f"Simulação desde a escolha: {s.get('ret', 0):+.1%} em {s.get('n', 0)} operações. "
                           + ("Também funciona no outro mercado e supera a atual." if diabo_ok else "Não se sustenta no outro mercado, piorou na simulação ou não supera a atual.")),
    }


def parecer_ia(nome, foco, c, atual, voto, motivo, chave):
    prompt = (f"Você é {nome}, conselheiro(a) de {foco} da Agência COINS, que opera um robô de cripto com pouco dinheiro "
              "(R$ 10 por mercado) na Foxbit, taxa 0,5% por ordem. Analise a estratégia candidata e a atual. "
              f"As regras já deram o voto: {'SIM' if voto else 'NÃO'} ({motivo}). Escreva um parecer honesto em português, "
              "em no máximo 3 frases curtas, sem prometer lucro, apontando o principal risco.\n\n"
              f"Candidata: {json.dumps(c, ensure_ascii=False)}\nAtual: {json.dumps(atual, ensure_ascii=False)}")
    corpo = json.dumps({"model": MODELO_IA, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=corpo, headers={
        "x-api-key": chave, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        dados = json.loads(r.read())
    return "".join(b.get("text", "") for b in dados.get("content", [])).strip()


def aplicar_no_config(c):
    """Troca a estratégia do config.yaml pela aprovada, guardando a anterior para poder voltar."""
    caminho = os.path.join(PASTA, "config.yaml")
    with open(caminho, encoding="utf-8") as f:
        texto = f.read()
    cfg = yaml.safe_load(texto)
    anterior = {"timeframe": cfg["timeframe"], "estrategia": copy.deepcopy(cfg["estrategia"])}
    tf, params = params_de(c)
    cfg["timeframe"] = tf
    cfg["estrategia"].update(params)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("# Estratégia trocada pelo conselho da Agência COINS com aprovação do Silva em "
                f"{agora():%d/%m/%Y %H:%M} UTC: {c['nome']} ({c['par']}).\n")
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    return anterior


def voltar_config(anterior):
    caminho = os.path.join(PASTA, "config.yaml")
    with open(caminho, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["timeframe"] = anterior["timeframe"]
    cfg["estrategia"] = anterior["estrategia"]
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(f"# Estratégia anterior restaurada a pedido do Silva em {agora():%d/%m/%Y %H:%M} UTC.\n")
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def main():
    url, chave = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if not (url and chave):
        raise SystemExit("Precisa de SUPABASE_URL e SUPABASE_SERVICE_KEY.")
    lab = ArmazenamentoSupabase(url, chave, "lab")
    arm = ArmazenamentoSupabase(url, chave, "conselho")
    chave_ia = os.getenv("ANTHROPIC_API_KEY")
    base = carregar_config()
    base["risco"]["valor_fixo_reais"] = 0

    resultados = lab.ler("resultados") or {}
    lab_status = lab.ler("status") or {}
    atual = lab_status.get("atual")
    estado = arm.ler("estado") or {"candidatas": {}, "historico": [], "anterior": None}
    cand = estado["candidatas"]
    controle = arm.ler_global("controle") or {}
    log, mudou_config, chamadas = [], False, 0

    # 0) pedidos do Silva vindos da sala (gravados em "controle")
    pedido = controle.get("conselho") or {}
    if pedido.get("acao") and pedido.get("em") != estado.get("ultimo_pedido"):
        estado["ultimo_pedido"] = pedido.get("em")
        alvo = cand.get(pedido.get("id", ""))
        if pedido["acao"] == "aprovar" and alvo and alvo["etapa"] == "aguardando":
            estado["anterior"] = aplicar_no_config(alvo)
            alvo["etapa"], alvo["aprovada_em"] = "aprovada", agora().isoformat()
            for outra in cand.values():  # só uma estratégia ativa por vez
                if outra is not alvo and outra["etapa"] == "aprovada":
                    outra["etapa"] = "substituida"
            mudou_config = True
            log.append(f"Silva aprovou: {alvo['nome']} ({alvo['par']}). config.yaml atualizado.")
        elif pedido["acao"] == "reprovar" and alvo and alvo["etapa"] == "aguardando":
            alvo["etapa"], alvo["motivo"] = "reprovada", "reprovada pelo Silva"
            log.append(f"Silva reprovou: {alvo['nome']}.")
        elif pedido["acao"] == "voltar" and estado.get("anterior"):
            voltar_config(estado["anterior"])
            for c in cand.values():
                if c["etapa"] == "aprovada":
                    c["etapa"] = "revertida"
            estado["anterior"] = None
            mudou_config = True
            log.append("Silva pediu para voltar à estratégia anterior. config.yaml restaurado.")

    if not atual:
        log.append("O laboratório ainda não gravou a estratégia atual; o conselho espera.")
    else:
        # 1) novas candidatas: fortes que superam a atual na validação
        em_sim = [c for c in cand.values() if c["etapa"] in ("simulacao", "conselho", "aguardando")]
        fortes = sorted((r for r in resultados.values() if r.get("forte") and r["id"] not in cand
                         and r["valid"]["pf"] > atual["valid"]["pf"] and r["valid"]["ret"] > atual["valid"]["ret"]),
                        key=lambda r: (min(r["treino"]["pf"], r["valid"]["pf"]), r["valid"]["ret"]), reverse=True)
        for r in fortes[:max(0, MAX_EM_SIMULACAO - len(em_sim))]:
            cand[r["id"]] = {**r, "etapa": "simulacao", "desde": agora().strftime("%Y-%m-%d"), "pareceres": {}}
            log.append(f"Nova candidata em simulação: {r['par']} {r['nome']}.")

        # 2) simulação em dados novos e votação
        dados = {}
        for c in cand.values():
            if c["etapa"] not in ("simulacao", "conselho"):
                continue
            tf, params = params_de(c)
            if (c["par"], tf) not in dados:
                dados[(c["par"], tf)] = baixar_dados("bitstamp", c["par"], tf, BAIXAR_DESDE)
            c["simulacao"] = avaliar_desde(base, dados[(c["par"], tf)], tf, params, c["desde"])
            dias = (agora().date() - datetime.strptime(c["desde"], "%Y-%m-%d").date()).days
            c["dias_simulacao"] = dias
            if dias < DIAS_SIMULACAO:
                continue
            c["etapa"] = "conselho"
            outro = next(p for p in PARES if p != c["par"])
            if (outro, tf) not in dados:
                dados[(outro, tf)] = baixar_dados("bitstamp", outro, tf, BAIXAR_DESDE)
            outro_val = avaliar_desde(base, dados[(outro, tf)], tf, params, "2024-01-01")
            c["outro_mercado"] = {"par": outro, **outro_val}
            votos = votos_por_regra(c, atual, outro_val)
            for nome, (ok, motivo) in votos.items():
                texto = motivo
                if chave_ia and chamadas < MAX_CHAMADAS_IA:
                    try:
                        texto = parecer_ia(nome, CONSELHEIROS[nome], c, atual, ok, motivo, chave_ia) or motivo
                        chamadas += 1
                    except Exception as e:
                        log.append(f"IA indisponível para {nome}: {e}")
                c["pareceres"][nome] = {"voto": ok, "texto": texto, "ia": texto != motivo}
            if all(ok for ok, _ in votos.values()):
                c["etapa"] = "aguardando"
                log.append(f"Conselho aprovou por unanimidade: {c['nome']}. Aguardando o Silva.")
            else:
                c["etapa"], c["motivo"] = "reprovada", "reprovada pelo conselho"
                log.append(f"Conselho reprovou: {c['nome']}.")

    estado["historico"] = (log + estado.get("historico", []))[:30]
    estado["atualizado_em"] = agora().isoformat()
    arm.gravar("estado", estado)
    ordem = {"aguardando": 0, "conselho": 1, "simulacao": 2, "aprovada": 3, "reprovada": 4, "substituida": 5, "revertida": 6}
    vitrine = sorted(cand.values(), key=lambda c: (ordem.get(c["etapa"], 9), c.get("desde", "")))[:12]
    arm.gravar("status", {
        "atualizado_em": estado["atualizado_em"], "candidatas": vitrine, "historico": estado["historico"][:10],
        "atual": atual, "pode_voltar": bool(estado.get("anterior")), "ia": bool(chave_ia), "chamadas_ia": chamadas,
        "conselheiros": [{"nome": n, "foco": f} for n, f in CONSELHEIROS.items()],
        "regras": {"dias_simulacao": DIAS_SIMULACAO, "max_em_simulacao": MAX_EM_SIMULACAO},
    })
    for linha in log or ["Nada novo para o conselho nesta rodada."]:
        print(linha)
    if mudou_config:
        open(os.path.join(PASTA, ".config_mudou"), "w").close()


if __name__ == "__main__":
    main()

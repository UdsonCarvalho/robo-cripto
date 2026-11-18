"""Leitura e validação do config.yaml."""
import os
import sys

import yaml

PASTA = os.path.dirname(os.path.abspath(__file__))
MODOS = {"paper", "demo", "testnet", "real"}


def carregar_config(caminho=None):
    caminho = caminho or os.path.join(PASTA, "config.yaml")
    with open(caminho, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    validar(cfg)
    return cfg


def validar(cfg):
    erros = []
    if cfg.get("modo") not in MODOS:
        erros.append(f"modo deve ser um de {sorted(MODOS)}")
    r = cfg["risco"]
    if not 0 < r["risco_por_trade"] <= 0.05:
        erros.append("risco_por_trade deve ficar entre 0 e 0.05 (5%)")
    if not 0 < r["exposicao_maxima"] <= 0.95:
        erros.append("exposicao_maxima deve ficar entre 0 e 0.95")
    if not 0 < r["perda_diaria_maxima"] <= 0.10:
        erros.append("perda_diaria_maxima deve ficar entre 0 e 0.10")
    e = cfg["estrategia"]
    if e.get("tipo") not in ("ema_cruzamento", "rompimento", "tendencia_mm", "reversao_rsi"):
        erros.append("estrategia.tipo deve ser ema_cruzamento, rompimento, tendencia_mm ou reversao_rsi")
    elif e["tipo"] == "ema_cruzamento" and not e["ema_rapida"] < e["ema_lenta"]:
        erros.append("ema_rapida precisa ser menor que ema_lenta")
    if e["stop_atr"] <= 0 or e["alvo_atr"] < 0 or e.get("trailing_atr", 0) < 0:
        erros.append("stop_atr precisa ser positivo; alvo_atr e trailing_atr >= 0")
    if erros:
        sys.exit("Erro no config.yaml:\n - " + "\n - ".join(erros))
    if r["risco_por_trade"] > 0.02:
        print("AVISO: risco_por_trade acima de 2% (aceitável com capital bem pequeno; agressivo para valores maiores).")
